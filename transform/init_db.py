"""Initialize the curated DuckDB database from schema.sql.

Usage: .venv/Scripts/python.exe transform/init_db.py
"""
from pathlib import Path
import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "curated.duckdb"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def main() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    tables = con.execute("SHOW TABLES").fetchall()
    con.close()
    print(f"Initialized {DB_PATH}")
    print("Tables:", ", ".join(t[0] for t in tables))


if __name__ == "__main__":
    main()
