import json
import os

from overunder.config import DATA_DIR
from overunder.providers import load_history_db, save_history_db, db_add_match

HISTORY_DB = os.path.join(DATA_DIR, "history_db.json")

def add_matches():
    db = load_history_db()

    # England matches
    db_add_match(db, "England", "A", 3, 2, "2026-09-26", opp="Spain")
    db_add_match(db, "England", "H", 1, 0, "2026-09-10", opp="Germany")
    db_add_match(db, "England", "H", 2, 0, "2026-06-18", opp="Italy")

    # Switzerland matches
    db_add_match(db, "Switzerland", "A", 1, 1, "2026-09-26", opp="France")
    db_add_match(db, "Switzerland", "H", 2, 1, "2026-09-10", opp="Portugal")
    db_add_match(db, "Switzerland", "A", 1, 0, "2026-06-18", opp="Spain")

    save_history_db(db)
    print("National team matches added to history_db.json")

if __name__ == "__main__":
    add_matches()
