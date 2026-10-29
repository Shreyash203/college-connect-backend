import json
import os
import queue
import random
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import websocket
from gevent.event import Event
from gevent import sleep, spawn
from gevent.lock import Semaphore
from locust import User, between, events, task
from locust.exception import StopUser


def _load_accounts():
    accounts_file = Path(
        os.environ.get(
            "CHAT_TEST_ACCOUNTS_FILE",
            "tests/load_tests/chat-test-accounts.local.json",
        )
    )
    accounts_json = os.environ.get("CHAT_TEST_ACCOUNTS")

    if accounts_json:
        accounts = json.loads(accounts_json)
    elif accounts_file.is_file():
        accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
    else:
        raise RuntimeError(
            "Configure CHAT_TEST_ACCOUNTS or "
            f"{accounts_file} with disposable test-user tokens."
        )

    if not isinstance(accounts, list) or not accounts:
        raise RuntimeError("Chat load-test accounts must be a non-empty JSON array.")

    for index, account in enumerate(accounts):
        if (
            not isinstance(account, dict)
            or not isinstance(account.get("token"), str)
            or not account["token"]
            or not isinstance(account.get("user_id"), int)
            or not isinstance(account.get("conversation_id"), int)
        ):
            raise RuntimeError(
                f"Account {index} must contain token, integer user_id, "
                "and integer conversation_id."
            )

    if len({account["token"] for account in accounts}) != len(accounts):
        raise RuntimeError("Each virtual user must have a unique access token.")
    if len({account["user_id"] for account in accounts}) != len(accounts):
        raise RuntimeError("Each virtual user must have a unique user_id.")

    conversations = {}
    for account in accounts:
        conversations.setdefault(account["conversation_id"], []).append(account)
    if any(
        len(pair) != 2 or pair[0]["user_id"] == pair[1]["user_id"]
        for pair in conversations.values()
    ):
        raise RuntimeError(
            "Each conversation_id must appear for exactly two distinct test users."
        )

    return accounts


ACCOUNTS = _load_accounts()
AVAILABLE_ACCOUNTS = queue.Queue()
for account_index, account in enumerate(ACCOUNTS):
    AVAILABLE_ACCOUNTS.put((account_index, account))
ACCOUNT_LOCK = Semaphore()
USERS_READY = Event()
CONNECTED_USER_COUNT = 0


class ChatUser(User):
    wait_time = between(25, 35)

    def on_start(self):
        global CONNECTED_USER_COUNT

        with ACCOUNT_LOCK:
            try:
                self.account_index, self.account = AVAILABLE_ACCOUNTS.get_nowait()
            except queue.Empty as exc:
                raise RuntimeError(
                    "Locust user count exceeds configured test accounts."
                ) from exc

        self.socket = None
        self.receiver = None
        self.receiver_error = None
        self.conversation_id = self.account["conversation_id"]
        started = time.perf_counter()
        try:
            self.socket = websocket.create_connection(
                self._websocket_url(),
                timeout=1,
                enable_multithread=True,
            )
        except Exception as exc:
            self._report("WebSocket connect", started, 0, exc)
            raise StopUser() from exc

        self._report("WebSocket connect", started, 0, None)
        self.receiver = spawn(self._receive_messages)
        with ACCOUNT_LOCK:
            CONNECTED_USER_COUNT += 1
            if CONNECTED_USER_COUNT == len(ACCOUNTS):
                USERS_READY.set()
        if not USERS_READY.wait(timeout=120):
            raise RuntimeError(
                "Not all configured test users connected; refusing to send "
                "messages before every conversation peer is online."
            )
        sleep(random.uniform(0, 30))

    def on_stop(self):
        if self.receiver is not None:
            self.receiver.kill(block=False)
        if self.socket is not None:
            try:
                self.socket.close()
            except Exception:
                pass
        if hasattr(self, "account"):
            with ACCOUNT_LOCK:
                AVAILABLE_ACCOUNTS.put((self.account_index, self.account))

    @task
    def send_message(self):
        if self.receiver_error is not None:
            raise StopUser()

        sent_at_ns = time.time_ns()
        content = f"cc-loadtest:{uuid.uuid4().hex}:{sent_at_ns}"
        payload = json.dumps(
            {"conversation_id": self.conversation_id, "content": content}
        )
        started = time.perf_counter()
        try:
            self.socket.send(payload)
            self._report("Chat message send", started, len(payload), None)
        except Exception as exc:
            self._report("Chat message send", started, len(payload), exc)
            self.receiver_error = exc
            raise StopUser() from exc

    def _receive_messages(self):
        while True:
            try:
                raw_message = self.socket.recv()
                if not raw_message:
                    continue
                payload = json.loads(raw_message)
                content = payload.get("content")
                if (
                    not isinstance(content, str)
                    or not content.startswith("cc-loadtest:")
                    or payload.get("sender_id") == self.account["user_id"]
                ):
                    continue

                prefix, _, sent_at_ns = content.split(":", 2)
                if prefix != "cc-loadtest" or payload.get(
                    "conversation_id"
                ) != self.conversation_id:
                    raise ValueError("Received an invalid load-test delivery.")

                latency_ms = (time.time_ns() - int(sent_at_ns)) / 1_000_000
                events.request.fire(
                    request_type="WS",
                    name="Peer message delivery",
                    response_time=latency_ms,
                    response_length=len(raw_message),
                    exception=None,
                    context={},
                )
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:
                self.receiver_error = exc
                self._report("Peer message delivery", time.perf_counter(), 0, exc)
                return

    def _websocket_url(self):
        parsed = urlsplit(self.host)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        path = f"{parsed.path.rstrip('/')}/api/ws/chat"
        return urlunsplit(
            (
                scheme,
                parsed.netloc,
                path,
                urlencode({"token": self.account["token"]}),
                "",
            )
        )

    @staticmethod
    def _report(name, started, response_length, exception):
        events.request.fire(
            request_type="WS",
            name=name,
            response_time=(time.perf_counter() - started) * 1000,
            response_length=response_length,
            exception=exception,
            context={},
        )
