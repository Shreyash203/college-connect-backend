# Chat WebSocket load test

This test opens one authenticated WebSocket per virtual user. It waits until
all configured users are connected before sending messages, staggers initial
messages over 30 seconds, then each sends a message every 25–35 seconds. It
records successful connections, send failures, peer message delivery failures,
and peer-delivery latency.

## Test setup

Run against a local or staging backend only. Use disposable, verified test
accounts and existing one-to-one conversations. For **40 connected users**,
prepare 40 different users/tokens and 20 conversations; each conversation ID
must be assigned to exactly two users. The test accounts must be authorized
members of their specified conversations.

Create `tests/load_tests/chat-test-accounts.local.json` and do not commit it:

```json
[
  {"token": "<access-token-user-1>", "user_id": 1, "conversation_id": 101},
  {"token": "<access-token-user-2>", "user_id": 2, "conversation_id": 101},
  {"token": "<access-token-user-3>", "user_id": 3, "conversation_id": 102},
  {"token": "<access-token-user-4>", "user_id": 4, "conversation_id": 102}
]
```

Replace the sample IDs with IDs from your test database. Use one row per user.
For 40 conversations, prepare 80 users and use `--users 80`.

Access tokens appear in WebSocket query strings during the run. Do not use
production tokens or share output/logs that could contain credentials.

## Install and run (PowerShell)

From the repository root:

```powershell
python -m pip install "locust>=2.24,<3.0" "websocket-client>=1.8,<2.0"
locust -f tests/load_tests/chat_locustfile.py --host http://127.0.0.1:8000 --users 40 --spawn-rate 0.33 --run-time 17m --headless --csv tests/load_tests/results/chat-40
```

Start the backend and Redis before the test. The 0.33 users/second spawn rate
takes about two minutes to reach 40 users; the remainder of the 17-minute run
holds the target for roughly 15 minutes. Each user sends about two messages a
minute (about 80 messages/minute in total at 40 users).

Review Locust's summary and CSV files. `WebSocket connect` failures indicate
connection problems; `Peer message delivery` reports delivery latency and
errors. Compare sent-message and peer-delivery counts (each sent message should
arrive at the other participant). Monitor backend CPU/memory, Redis connection
errors/connections, and database connection and query metrics during the run.
Stop the test if the local or staging service becomes unhealthy.

The results describe only the tested configuration and workload; they are not
a universal capacity guarantee.
