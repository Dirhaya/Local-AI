"""Storage/privacy tests that also run without the optional web dependencies."""
from pathlib import Path
import tempfile
import time
import unittest

from app.vault import Vault, LockedError


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.vault = Vault(self.temp.name)
        self.token = self.vault.setup("correct horse battery staple")

    def tearDown(self):
        self.vault.lock()
        self.temp.cleanup()

    def test_encryption_persistence_and_lock(self):
        record = self.vault.put("note", {"body": "unique-private-content-7391", "title": "secret meeting"})
        self.assertEqual(self.vault.get("note", record["id"])["body"], "unique-private-content-7391")
        self.assertNotIn(b"unique-private-content-7391", self.vault.path.read_bytes())
        self.assertNotIn(b"secret meeting", self.vault.path.read_bytes())
        self.assertNotIn(b"correct horse battery staple", self.vault.path.read_bytes())
        self.vault.lock()
        with self.assertRaises(LockedError):
            self.vault.list("note")
        other = Vault(self.temp.name)
        other.unlock("correct horse battery staple")
        self.assertEqual(other.get("note", record["id"])["title"], "secret meeting")
        other.lock()

    def test_wrong_passphrase_and_short_setup(self):
        self.vault.lock()
        with self.assertRaises(ValueError):
            self.vault.unlock("wrong passphrase")
        self.assertFalse(self.vault.unlocked)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                Vault(directory).setup("short")

    def test_idle_expiry_and_old_session_rejected(self):
        self.vault._last = time.monotonic() - 1000
        self.assertFalse(self.vault.unlocked)
        with self.assertRaises(LockedError):
            self.vault.authenticate(self.token)
        new_token = self.vault.unlock("correct horse battery staple")
        self.assertNotEqual(new_token, self.token)
        with self.assertRaises(LockedError):
            self.vault.authenticate(self.token)
        self.vault.authenticate(new_token)

    def test_export_excludes_credentials_and_includes_personal_data(self):
        self.vault.put("memory", {"text": "I prefer concrete examples"})
        for kind in ("mail_account", "calendar_account", "integration_config"):
            self.vault.put(kind, {"password": "never-export-this"})
        exported = self.vault.export()
        self.assertEqual(exported["records"]["memory"][0]["text"], "I prefer concrete examples")
        self.assertNotIn("never-export-this", str(exported))
        self.assertNotIn("settings", exported["records"])

    def test_updates_preserve_creation_and_clear_removes_account_secrets(self):
        first = self.vault.put("task", {"title": "Do research", "status": "ready"})
        second = self.vault.put("task", {**first, "status": "done"})
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertEqual(len(self.vault.list("task")), 1)
        self.vault.put("mail_account", {"password": "credential"})
        self.vault.clear_content()
        self.assertEqual(self.vault.list("task"), [])
        self.assertEqual(self.vault.list("mail_account"), [])
        self.assertEqual(self.vault.settings()["network_enabled"], False)

    def test_ciphertext_tampering_cannot_change_content(self):
        from cryptography.exceptions import InvalidTag
        record = self.vault.put("memory", {"text": "original"})
        with self.vault._connect() as connection:
            blob = connection.execute("SELECT payload FROM records WHERE kind='memory'").fetchone()[0]
            corrupted = blob[:-1] + bytes([blob[-1] ^ 1])
            connection.execute("UPDATE records SET payload=? WHERE kind='memory'", (corrupted,))
        with self.assertRaises(InvalidTag):
            self.vault.get("memory", record["id"])

    def test_old_vault_memory_survives_schema_marker_upgrade(self):
        item=self.vault.put('memory',{'text':'preserve my prior memory'})
        with self.vault._connect() as con: con.execute("DELETE FROM meta WHERE key='schema_version'")
        self.vault.lock()
        upgraded=Vault(self.temp.name)
        upgraded.unlock('correct horse battery staple')
        self.assertEqual(upgraded.get('memory',item['id'])['text'],'preserve my prior memory')
        upgraded.lock()

    def test_atomic_batch_rolls_back_on_serialization_failure(self):
        with self.assertRaises(TypeError):
            self.vault.put_many([('study_document',{'id':'doc','name':'valid'}),('study_pdf',{'id':'doc','bad':set()})])
        self.assertIsNone(self.vault.get('study_document','doc'))

    def test_encrypted_backup_can_be_unlocked_with_existing_passphrase(self):
        import shutil
        item=self.vault.put('study_course',{'title':'Linear algebra'})
        backup=self.vault.encrypted_backup()
        self.assertNotIn(b'Linear algebra',backup.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            shutil.copy2(backup,Path(directory)/'vault.sqlite3')
            restored=Vault(directory);restored.unlock('correct horse battery staple')
            self.assertEqual(restored.get('study_course',item['id'])['title'],'Linear algebra')
            restored.lock()


if __name__ == "__main__":
    unittest.main()
