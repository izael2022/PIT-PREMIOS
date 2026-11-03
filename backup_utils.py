import base64
import os
import sqlite3
import tempfile
import zipfile
from io import BytesIO
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BACKUP_MEMBER = "pit_premios.db"
MAX_DATABASE_BYTES = 512 * 1024 * 1024
ENVELOPE_MAGIC = b"PITBKP1"
NONCE_BYTES = 12
KEY_ENV = "BACKUP_ENCRYPTION_KEY"


def _load_key(key=None):
    raw = key if key is not None else os.getenv(KEY_ENV, "")
    if isinstance(raw, bytes):
        decoded = raw
    else:
        try:
            decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception as exc:
            raise ValueError(f"{KEY_ENV} inválida: use Base64 URL-safe de uma chave de 32 bytes.") from exc
    if len(decoded) != 32:
        raise ValueError(f"{KEY_ENV} ausente ou inválida. Configure uma chave Base64 URL-safe de 32 bytes.")
    return decoded


def encrypt_backup_archive(payload, key=None):
    secret = _load_key(key)
    nonce = os.urandom(NONCE_BYTES)
    encrypted = AESGCM(secret).encrypt(nonce, payload, ENVELOPE_MAGIC)
    return ENVELOPE_MAGIC + nonce + encrypted


def decrypt_backup_archive(payload, key=None):
    secret = _load_key(key)
    minimum = len(ENVELOPE_MAGIC) + NONCE_BYTES + 16
    if not isinstance(payload, (bytes, bytearray)) or len(payload) < minimum:
        raise ValueError("Backup criptografado inválido ou incompleto.")
    if not payload.startswith(ENVELOPE_MAGIC):
        raise ValueError("Formato de backup não reconhecido; backups sem criptografia são rejeitados.")
    start = len(ENVELOPE_MAGIC)
    nonce = payload[start:start + NONCE_BYTES]
    ciphertext = payload[start + NONCE_BYTES:]
    try:
        return AESGCM(secret).decrypt(nonce, ciphertext, ENVELOPE_MAGIC)
    except InvalidTag as exc:
        raise ValueError("Não foi possível autenticar o backup. Verifique a chave e a integridade do arquivo.") from exc


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


def validate_backup_archive(payload, encryption_key=None):
    archive_payload = decrypt_backup_archive(payload, encryption_key)
    try:
        with zipfile.ZipFile(BytesIO(archive_payload), "r") as archive:
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


def create_backup_archive(database_path, encryption_key=None):
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
        archive_payload = buffer.getvalue()
        # Validar o ZIP antes de cifrar; a função pública só devolve bytes cifrados.
        with tempfile.TemporaryDirectory() as validation_folder:
            candidate = Path(validation_folder) / BACKUP_MEMBER
            with zipfile.ZipFile(BytesIO(archive_payload), "r") as archive:
                if archive.namelist() != [BACKUP_MEMBER]:
                    raise ValueError("Estrutura interna do backup inválida.")
                candidate.write_bytes(archive.read(BACKUP_MEMBER))
            _check_database(candidate)
        encrypted = encrypt_backup_archive(archive_payload, encryption_key)
        # Verificação ponta a ponta antes de disponibilizar o arquivo.
        validate_backup_archive(encrypted, encryption_key)
        return encrypted


def restore_backup_archive(payload, destination, encryption_key=None):
    """Restaura backup autenticado para arquivo novo; nunca sobrescreve banco existente."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = validate_backup_archive(payload, encryption_key)
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
