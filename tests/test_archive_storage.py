import asyncio
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from app.storage.db import DataManager
from app.features.archive import _send_archived_item, archive_maintenance


class ArchiveStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = DataManager(os.path.join(self.tmp.name, "data.db"))

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def test_claim_is_pending_until_explicit_success_and_can_retry(self):
        self.db.upsert_pv_cache(1, 10, 7, 2, "n", "u", "متن", "body")
        row = self.db.pop_pv_cache_by_message_ids(1, [7], chat_id=10)
        self.assertEqual(row[0][11], "PENDING")
        self.assertEqual(self.db.pop_pv_cache_by_message_ids(1, [7], chat_id=10)[0][2], 7)
        self.db.mark_archive_success(1, 10, 7)
        self.assertEqual(self.db.pop_pv_cache_by_message_ids(1, [7], chat_id=10), [])

    def test_same_message_id_in_two_chats_is_isolated(self):
        for chat in (10, 20):
            self.db.upsert_pv_cache(1, chat, 7, 2, "n", "u", "متن", str(chat))
        rows = self.db.pop_pv_cache_by_message_ids(1, [7], chat_id=20)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 20)
        self.assertEqual(self.db.pop_pv_cache_by_message_ids(1, [7], chat_id=10)[0][1], 10)

    def test_delete_user_removes_history_cache_and_media(self):
        media = Path(self.tmp.name) / "secret.bin"
        media.write_bytes(b"x")
        self.db.save_chat_message(4, 99, "user", "history")
        self.db.upsert_pv_cache(4, 8, 1, 2, "n", "u", "file", "", str(media), 1)
        self.db.delete_user(4)
        self.assertFalse(media.exists())
        self.assertEqual(self.db.get_chat_history(4, 99), [])
        self.assertEqual(self.db.get_cache_stats(4), (0, 0))

    def test_empty_edit_is_archived_and_html_is_escaped(self):
        client = type("C", (), {})()
        client.send_message = AsyncMock()
        asyncio.run(_send_archived_item(client, "<b>h</b>", "متن", "<danger> & full", None))
        body = client.send_message.call_args.args[1]
        self.assertIn("&lt;danger&gt; &amp; full", body)

    def test_sessions_encrypted_and_legacy_migrated(self):
        from cryptography.fernet import Fernet
        from unittest.mock import patch
        key = Fernet.generate_key().decode()
        with patch.dict(os.environ, {"SESSION_ENCRYPTION_KEY": key}):
            self.db.save_session("123", "SESSION_SECRET", 1)
            raw = self.db.conn.execute("SELECT session_string,data FROM users").fetchone()
            self.assertNotIn("SESSION_SECRET", str(raw))
            self.assertEqual(self.db.get_all_sessions()[0][1]["string"], "SESSION_SECRET")
            self.db.conn.execute("INSERT INTO users VALUES (2,'234','LEGACY',?)", ('{"session":"LEGACY","session_string":"LEGACY"}',))
            self.db.conn.commit()
            self.db.get_all_sessions()
            raw = self.db.conn.execute("SELECT session_string,data FROM users WHERE user_id=2").fetchone()
            self.assertNotIn("LEGACY", str(raw))
        with patch.dict(os.environ, {"SESSION_ENCRYPTION_KEY": ""}):
            with self.assertRaises(RuntimeError): self.db.get_all_sessions()

    def test_history_and_file_permissions_are_bounded(self):
        for n in range(150): self.db.save_chat_message(1, 1, "user", str(n))
        self.assertLessEqual(self.db.conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0], 100)
        self.assertEqual(os.stat(self.db.file_path).st_mode & 0o777, 0o600)

    def test_full_text_html_not_truncated(self):
        client = type("C", (), {})()
        client.send_message = AsyncMock()
        text = "<&😀" * 4000
        asyncio.run(_send_archived_item(client, "<b>h</b>", "متن", text))
        import html
        sent = "".join(c.args[1] for c in client.send_message.call_args_list)
        self.assertEqual(sent.count("&lt;"), 4000)
        self.assertTrue(all(len(c.args[1].encode('utf-16-le')) // 2 <= 4096 for c in client.send_message.call_args_list))

    def test_maintenance_retries_pending_for_active_account(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from app.features import archive
        media = Path(self.tmp.name) / "retry.bin"
        media.write_bytes(b"saved")
        self.db.upsert_pv_cache(1, 10, 7, 2, "n", "u", "فایل", "body", str(media), 5, True, "PENDING")
        client = SimpleNamespace(me=SimpleNamespace(id=1), send_document=AsyncMock(side_effect=OSError("offline")), send_message=AsyncMock())
        with patch.dict(archive.ANTI_DELETE_STATUS, {1: True}):
            asyncio.run(archive_maintenance(self.db, clients={1: client}))
            self.assertTrue(media.exists())
            self.assertEqual(self.db.get_cache_stats(1), (1, 5))
            client.send_document.side_effect = None
            with patch.dict(archive.ACTIVE_BOTS, {1: (client, [])}, clear=True):
                asyncio.run(archive_maintenance(self.db))
        self.assertFalse(media.exists())
        self.assertEqual(self.db.get_cache_stats(1), (0, 0))

    def test_maintenance_is_awaitable(self):
        asyncio.run(archive_maintenance(self.db))


if __name__ == "__main__":
    unittest.main()
