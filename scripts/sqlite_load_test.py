"""Teste de carga isolado do SQLite/WAL. Não abre nem modifica DATABASE_PATH.

Uso: python scripts/sqlite_load_test.py --workers 4 --writes 500
"""
import argparse
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Benchmark SQLite isolado do PIT PRÊMIOS")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--writes", type=int, default=500, help="Total de transações de escrita")
    args = parser.parse_args()
    if not 1 <= args.workers <= 16 or not 1 <= args.writes <= 100000:
        parser.error("Use workers entre 1 e 16 e writes entre 1 e 100000.")
    with tempfile.TemporaryDirectory(prefix="pit-sqlite-load-") as folder:
        path = Path(folder) / "load-test.db"
        with sqlite3.connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE counter(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)")
            db.execute("INSERT INTO counter VALUES(1,0)")
        started = time.perf_counter()

        def worker(count):
            with sqlite3.connect(path, timeout=30) as db:
                db.execute("PRAGMA busy_timeout=30000")
                for _ in range(count):
                    db.execute("BEGIN IMMEDIATE")
                    db.execute("UPDATE counter SET value=value+1 WHERE id=1")
                    db.commit()

        base, remainder = divmod(args.writes, args.workers)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(worker, base + (i < remainder)) for i in range(args.workers)]
            for future in futures:
                future.result()
        elapsed = time.perf_counter() - started
        with sqlite3.connect(path) as db:
            actual = db.execute("SELECT value FROM counter WHERE id=1").fetchone()[0]
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        if actual != args.writes or integrity != "ok":
            raise SystemExit(f"FALHA: esperado={args.writes}, obtido={actual}, integrity={integrity}")
        print(f"APROVADO: {actual} transações; {args.workers} workers; {elapsed:.2f}s; {actual/elapsed:.1f} transações/s.")
        print("Teste executado em banco temporário isolado; não mede limites reais da Discloud.")


if __name__ == "__main__":
    main()
