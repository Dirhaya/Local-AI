"""Encrypted record storage. The passphrase and derived key are never persisted."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

DEFAULTS = {
    "model": os.environ.get("SULTAN_DEFAULT_MODEL", ""), "use_memory": False, "network_enabled": False,
    "auto_lock_minutes": 15, "speech_model_path": os.environ.get("SULTAN_DEFAULT_SPEECH_PATH", ""), "language": "auto",
}


class LockedError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


class Vault:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "vault.sqlite3"
        self._mutex = threading.RLock()
        self._key = None
        self._token = None
        self._last = 0
        self._ttl = 900
        self._failures = 0
        self._retry_after = 0
        with self._connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT NOT NULL, id TEXT NOT NULL, payload BLOB NOT NULL, PRIMARY KEY(kind,id))")
            row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row and int(row[0]) > 1:
                raise RuntimeError('This vault needs a newer app. Its contents were not changed.')
            con.execute("INSERT OR IGNORE INTO meta VALUES ('schema_version','1')")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @property
    def initialized(self):
        with self._connect() as con:
            return con.execute("SELECT 1 FROM meta WHERE key='verifier'").fetchone() is not None

    @property
    def unlocked(self):
        with self._mutex:
            if self._key is not None and time.monotonic() - self._last > self._ttl:
                self.lock()
            return self._key is not None

    @staticmethod
    def _derive(passphrase, salt):
        return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))

    def setup(self, passphrase):
        if len(passphrase) < 12 or len(passphrase) > 1024:
            raise ValueError("Use a passphrase of 12–1024 characters. There is no password recovery.")
        with self._mutex:
            if self.initialized:
                raise ValueError("Vault already exists. Unlock it with your passphrase.")
            salt = secrets.token_bytes(16)
            key = self._derive(passphrase, salt)
            nonce = secrets.token_bytes(12)
            verifier = nonce + AESGCM(key).encrypt(nonce, b"sultan-vault-v1", b"verifier")
            with self._connect() as con:
                con.execute("INSERT INTO meta VALUES ('salt',?)", (base64.b64encode(salt).decode(),))
                con.execute("INSERT INTO meta VALUES ('verifier',?)", (base64.b64encode(verifier).decode(),))
            self._key = key
            self._token = secrets.token_urlsafe(32)
            self._last = time.monotonic()
            self.update_settings(DEFAULTS)
            return self._token

    def unlock(self, passphrase):
        with self._mutex:
            if time.monotonic() < self._retry_after:
                raise ValueError("Too many attempts. Wait before trying again.")
            if not self.initialized:
                raise ValueError("Create your vault first.")
            with self._connect() as con:
                meta = dict(con.execute("SELECT key,value FROM meta"))
            key = self._derive(passphrase, base64.b64decode(meta["salt"]))
            verifier = base64.b64decode(meta["verifier"])
            try:
                check = AESGCM(key).decrypt(verifier[:12], verifier[12:], b"verifier")
                if check != b"sultan-vault-v1":
                    raise InvalidTag
            except InvalidTag:
                self._failures += 1
                self._retry_after = time.monotonic() + min(30, 2 ** min(self._failures, 5))
                raise ValueError("Incorrect passphrase.") from None
            self._key = key
            self._token = secrets.token_urlsafe(32)
            self._last = time.monotonic()
            self._failures = 0
            self._retry_after = 0
            self._ttl = int(self.settings()["auto_lock_minutes"]) * 60
            return self._token

    def authenticate(self, token):
        with self._mutex:
            if not self.unlocked or not token or not secrets.compare_digest(token, self._token):
                raise LockedError("Vault is locked. Unlock it to continue.")
            self._last = time.monotonic()

    def check_unlocked(self):
        if not self.unlocked:
            raise LockedError("Vault locked during this operation. Unlock and try again.")

    def lock(self):
        with self._mutex:
            self._key = None
            self._token = None

    def _decode(self, kind, ident, payload):
        return json.loads(AESGCM(self._key).decrypt(payload[:12], payload[12:], f"{kind}:{ident}".encode()))

    def list(self, kind):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                rows = con.execute("SELECT id,payload FROM records WHERE kind=?", (kind,)).fetchall()
            records = [self._decode(kind, ident, payload) for ident, payload in rows]
            return sorted(records, key=lambda r: r.get("updated_at", ""), reverse=True)

    def get(self, kind, ident):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                row = con.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, ident)).fetchone()
            return self._decode(kind, ident, row[0]) if row else None

    def put(self, kind, record):
        with self._mutex:
            self.check_unlocked()
            record = dict(record)
            ident = str(record.get("id") or uuid.uuid4())
            old = self.get(kind, ident)
            record.update(id=ident, created_at=(old or {}).get("created_at", now()), updated_at=now())
            nonce = secrets.token_bytes(12)
            raw = json.dumps(record, ensure_ascii=False).encode()
            payload = nonce + AESGCM(self._key).encrypt(nonce, raw, f"{kind}:{ident}".encode())
            with self._connect() as con:
                con.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)", (kind, ident, payload))
            return record

    def delete(self, kind, ident):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                return con.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, ident)).rowcount > 0

    def put_many(self, entries):
        """Commit related encrypted records together, or leave the vault unchanged."""
        with self._mutex:
            self.check_unlocked()
            saved = []
            with self._connect() as con:
                for kind, original in entries:
                    record = dict(original)
                    ident = str(record.get('id') or uuid.uuid4())
                    row = con.execute('SELECT payload FROM records WHERE kind=? AND id=?',(kind,ident)).fetchone()
                    old = self._decode(kind,ident,row[0]) if row else {}
                    record.update(id=ident,created_at=old.get('created_at',now()),updated_at=now())
                    nonce = secrets.token_bytes(12)
                    payload = nonce + AESGCM(self._key).encrypt(nonce,json.dumps(record,ensure_ascii=False).encode(),f'{kind}:{ident}'.encode())
                    con.execute('INSERT OR REPLACE INTO records VALUES (?,?,?)',(kind,ident,payload))
                    saved.append(record)
            return saved

    def delete_many(self, entries):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                con.executemany('DELETE FROM records WHERE kind=? AND id=?',entries)

    def encrypted_backup(self):
        """A consistent encrypted SQLite backup; no passphrase or key is written."""
        destination = self.directory / 'backups'
        destination.mkdir(exist_ok=True,mode=0o700)
        path = destination / ('vault-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.sqlite3')
        with self._mutex, self._connect() as source:
            target = sqlite3.connect(path)
            try:
                source.backup(target)
            finally:
                target.close()
        os.chmod(path,0o600)
        return path

    def settings(self):
        return {**DEFAULTS, **(self.get("settings", "main") or {})}

    def update_settings(self, updates):
        with self._mutex:
            current = self.settings()
            current.update(updates)
            current["id"] = "main"
            saved = self.put("settings", current)
            self._ttl = int(saved["auto_lock_minutes"]) * 60
            return saved

    def export(self):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                kinds = [r[0] for r in con.execute("SELECT DISTINCT kind FROM records")]
            # Export personal content, not reusable account secrets.
            return {"format": "sultan-local-ai-v1", "exported_at": now(), "records": {
                kind: self.list(kind) for kind in kinds if kind not in ("settings", "mail_account", "calendar_account", "integration_config")
            }}

    def clear_content(self):
        with self._mutex:
            self.check_unlocked()
            with self._connect() as con:
                con.execute("DELETE FROM records WHERE kind != 'settings'")
            # SQLite contents are encrypted; deleted record keys use the same vault key.
