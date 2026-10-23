"""Durable, atomic request reservations. Never reset automatically."""
from pathlib import Path
import sqlite3
from contextlib import closing

LIMIT = 700
LEDGER = Path(__file__).resolve().parents[3] / ".cache" / "request-budget.sqlite3"

def reserve():
    # A missing/corrupt ledger fails closed; provisioning is an explicit setup step.
    if not LEDGER.is_file():
        raise RuntimeError("Request budget ledger missing; requests are blocked.")
    with closing(sqlite3.connect(str(LEDGER), timeout=10)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        used = db.execute("SELECT used FROM budget WHERE id=1").fetchone()[0]
        if not isinstance(used, int) or used < 0 or used >= LIMIT:
            raise RuntimeError("Request budget exhausted or invalid; requests are blocked.")
        db.execute("UPDATE budget SET used=used+1 WHERE id=1")
        return used + 1
