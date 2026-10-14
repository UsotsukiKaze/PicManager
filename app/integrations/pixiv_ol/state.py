"""Short account transactions shared by foreground and background workers."""

import threading
from contextlib import contextmanager

from ...database import get_db_context as database_context

ACCOUNT_LOCK = threading.RLock()


@contextmanager
def get_db_context():
    # sync_state is a JSON document. Serialize its read/modify/write transaction,
    # never the network work between transactions, to avoid losing another lane's keys.
    with ACCOUNT_LOCK, database_context() as db:
        yield db
