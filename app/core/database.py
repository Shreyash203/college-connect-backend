"""Run complete synchronous database operations without blocking the event loop."""
from typing import Callable, TypeVar

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.db.session import SessionLocal

T = TypeVar("T")


async def run_db(operation: Callable[[Session], T]) -> T:
    """Own the session in one worker; return serialized data, never ORM objects.

    The operation controls commits. Closing the session also rolls back any
    unfinished transaction if the operation raises.
    """
    def execute() -> T:
        with SessionLocal() as db:
            return operation(db)

    return await run_in_threadpool(execute)
