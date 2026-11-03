import os
import sqlite3
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

BACKUP_MEMBER = "pit_premios.db"
MAX_DATABASE_BYTES = 512 * 1024 * 1024


def _check_database(path):
    connection = sqlite3.connect(str(path), timeout=30)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError("Banco falhou no integrity_check.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Banco contém referências inválidas.")
    finally:
        connection.close()


def validate_backup_archive(payload):
    try:
        with zipfile.ZipFile(BytesIO(payload), "r") as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != BACKUP_MEMBER:
                raise ValueError("ZIP deve conter somente pit_premios.db.")
            info = members[0]
            if info.is_dir() or info.file_size <= 0 or info.file_size > MAX_DATABASE_BYTES:
                raise ValueError("Tamanho do banco no backup é inválido.")
            if archive.testzip() is not None:
                raise ValueError("ZIP corrompido.")
            data = archive.read(BACKUP_MEMBER)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ValueError("Backup inválido ou corrompido.") from exc
    with tempfile.TemporaryDirectory() as folder:
        candidate = Path(folder) / BACKUP_MEMBER
        candidate.write_bytes(data)
        _check_database(candidate)
    return data


def create_backup_archive(database_path):
    source_path = Path(database_path)
    if not source_path.is_file():
        raise FileNotFoundError("Banco de dados não encontrado.")
    with tempfile.TemporaryDirectory(prefix="pit-premios-backup-") as folder:
        snapshot = Path(folder) / BACKUP_MEMBER
        source = sqlite3.connect(str(source_path), timeout=30)
        target = sqlite3.connect(str(snapshot), timeout=30)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
        _check_database(snapshot)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, BACKUP_MEMBER)
        payload = buffer.getvalue()
        validate_backup_archive(payload)
        return payload


def restore_backup_archive(payload, destination):
    """Restaura para arquivo novo; nunca sobrescreve banco existente."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = validate_backup_archive(payload)
    try:
        with target.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        raise FileExistsError("Destino já existe e não será sobrescrito: " + str(target))
    try:
        _check_database(target)
    except Exception:
        try:
            target.unlink()
        except OSError:
            pass
        raise
    return target
