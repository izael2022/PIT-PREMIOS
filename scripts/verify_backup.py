"""Valida e restaura um backup PITBKP1 em diretório temporário, sem tocar no banco ativo.

Uso: BACKUP_ENCRYPTION_KEY=<chave> python scripts/verify_backup.py caminho/backup.pitbackup
"""
import argparse
from contextlib import closing
import os
import sqlite3
import tempfile
from pathlib import Path

from backup_utils import restore_backup_archive


def main():
    parser = argparse.ArgumentParser(description="Teste isolado de restauração de backup PIT PRÊMIOS")
    parser.add_argument("backup", type=Path, help="Arquivo .pitbackup recebido pelo Telegram")
    args = parser.parse_args()
    if not args.backup.is_file():
        parser.error("Arquivo de backup não encontrado.")
    key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        parser.error("Configure BACKUP_ENCRYPTION_KEY no ambiente antes do teste.")
    with tempfile.TemporaryDirectory(prefix="pit-restore-check-") as folder:
        restored = restore_backup_archive(args.backup.read_bytes(), Path(folder) / "restored.db", key)
        # sqlite3.Connection.__exit__ does not close the handle; close it explicitly
        # before TemporaryDirectory tries to remove the database (required on Windows).
        with closing(sqlite3.connect(restored)) as db:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = db.execute("PRAGMA foreign_key_check").fetchall()
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )]
            counts = {}
            for table in tables:
                safe = '"' + table.replace('"', '""') + '"'
                counts[table] = db.execute(f"SELECT COUNT(*) FROM {safe}").fetchone()[0]
        if integrity != "ok" or foreign_keys:
            raise SystemExit("FALHA: banco restaurado não passou nas verificações SQLite.")
        print("APROVADO: descriptografia, restauração temporária, integrity_check e foreign_key_check.")
        print("Tabelas e registros:")
        for table, count in counts.items():
            print(f"  {table}: {count}")
        print("O arquivo restaurado será descartado ao encerrar; nenhum banco de produção foi alterado.")


if __name__ == "__main__":
    main()
