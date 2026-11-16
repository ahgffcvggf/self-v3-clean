import json
import logging
import os
import sqlite3
import threading
import time
from app.config import DATA_FILE, CACHE_TTL_DAYS, MAX_CACHE_TOTAL_BYTES


class DataManager:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.file_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        logging.info(f"✅ اتصال به دیتابیس SQLite برقرار شد: {self.file_path}")

    def _init_schema(self):
        with self._lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    phone TEXT,
                    session_string TEXT,
                    data TEXT NOT NULL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    chat_id INTEGER DEFAULT 0,
                    message_type TEXT,
                    content TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # مهاجرت ایمن برای دیتابیس‌های قدیمی که ستون chat_id ندارند
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(chat_history)").fetchall()]
            if "chat_id" not in cols:
                self.conn.execute("ALTER TABLE chat_history ADD COLUMN chat_id INTEGER DEFAULT 0")

            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS pv_cache (
                    account_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    sender_name TEXT,
                    sender_username TEXT,
                    msg_type TEXT,
                    text_content TEXT,
                    media_path TEXT,
                    size_bytes INTEGER DEFAULT 0,
                    is_timed INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'CACHED',
                    created_at REAL NOT NULL,
                    PRIMARY KEY (account_id, chat_id, message_id)
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_hist_acc_chat ON chat_history(user_id, chat_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pv_cache_msg ON pv_cache(account_id, message_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pv_cache_created ON pv_cache(created_at)")
            self.conn.commit()

    def _default_user_structure(self, user_id):
        return {
            "user_id": user_id,
            "phone": "",
            "first_name": "",
            "username": "",
            "session_string": "",
            "settings": {
                "font": "stylized",
                "clock": True,
                "bio_time": False,
                "bio_text": "",
                "bio_date_format": None,
                "bold": False,
                "hashtag": False,
                "strikethrough": False,
                "single_mode": False,
                "char_mode": False,
                "anti_delete": False,
                "typing": False,
                "playing": False,
                "online_mode": False,
                "comment_mode": False,
                "comment_text": "کامنت تنظیم نشده",
                "translate": None,
                "ai_assistant": False,
                "tts_voice": "female",
                "copy_mode": False,
                "global_enemy": False,
            },
            "enemies": [],
            "muted": [],
            "reactions": {},
            "enemy_queue": [],
        }

    def _write_user(self, user_id, user_data):
        phone = user_data.get("phone") or None
        session_string = user_data.get("session_string") or None
        self.conn.execute(
            """
            INSERT INTO users (user_id, phone, session_string, data)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                phone=excluded.phone,
                session_string=excluded.session_string,
                data=excluded.data
            """,
            (int(user_id), phone, session_string, json.dumps(user_data, ensure_ascii=False)),
        )
        self.conn.commit()

    def get_user_data(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT data FROM users WHERE user_id=?", (int(user_id),)).fetchone()
            default_structure = self._default_user_structure(user_id)
            if row is None:
                self._write_user(user_id, default_structure)
                return default_structure

            user_data = json.loads(row[0])
            changed = False
            for key, value in default_structure.items():
                if key not in user_data:
                    user_data[key] = value
                    changed = True
                elif key == "settings" and isinstance(value, dict):
                    if not isinstance(user_data.get("settings"), dict):
                        user_data["settings"] = {}
                        changed = True
                    for sk, sv in value.items():
                        if sk not in user_data["settings"]:
                            user_data["settings"][sk] = sv
                            changed = True
            if changed:
                self._write_user(user_id, user_data)
            return user_data

    def update_user_data(self, user_id, updates):
        with self._lock:
            user_data = self.get_user_data(user_id)
            for key, value in updates.items():
                if key == "settings" and isinstance(value, dict):
                    user_data.setdefault("settings", {})
                    for sk, sv in value.items():
                        user_data["settings"][sk] = sv
                else:
                    user_data[key] = value
            self._write_user(user_id, user_data)
            return user_data

    def save_session(self, phone, session_string, user_id, first_name="", username=""):
        with self._lock:
            user_data = self.get_user_data(user_id)
            user_data["phone"] = phone
            user_data["session_string"] = session_string
            user_data["first_name"] = first_name
            user_data["username"] = username
            self._write_user(user_id, user_data)

    def get_all_sessions(self):
        with self._lock:
            rows = self.conn.execute(
                "SELECT phone, session_string, user_id FROM users "
                "WHERE phone IS NOT NULL AND phone != '' "
                "AND session_string IS NOT NULL AND session_string != ''"
            ).fetchall()
            return [(r[0], {"string": r[1], "user_id": r[2]}) for r in rows]

    def get_all_users(self):
        with self._lock:
            rows = self.conn.execute("SELECT user_id, data FROM users").fetchall()
            return {str(r[0]): json.loads(r[1]) for r in rows}

    def delete_user(self, user_id):
        with self._lock:
            self.conn.execute("DELETE FROM users WHERE user_id=?", (int(user_id),))
            self.conn.commit()

    def get_stats(self):
        with self._lock:
            total_users = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            total_sessions = self.conn.execute(
                "SELECT COUNT(*) FROM users WHERE phone IS NOT NULL AND phone != '' "
                "AND session_string IS NOT NULL AND session_string != ''"
            ).fetchone()[0]
            return total_users, total_sessions

    # ==== حافظه چت AI (جدا به ازای account و chat) ====
    def save_chat_message(self, user_id: int, chat_id: int, message_type: str, content: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO chat_history (user_id, chat_id, message_type, content) VALUES (?, ?, ?, ?)",
                (int(user_id), int(chat_id), message_type, content),
            )
            self.conn.commit()

    def get_chat_history(self, user_id: int, chat_id: int, limit: int = 10):
        with self._lock:
            rows = self.conn.execute(
                "SELECT message_type, content FROM chat_history "
                "WHERE user_id = ? AND chat_id = ? ORDER BY id DESC LIMIT ?",
                (int(user_id), int(chat_id), limit),
            ).fetchall()
            return list(reversed(rows))

    def clear_chat_history(self, user_id: int, chat_id: int = None):
        with self._lock:
            if chat_id is None:
                self.conn.execute("DELETE FROM chat_history WHERE user_id = ?", (int(user_id),))
            else:
                self.conn.execute("DELETE FROM chat_history WHERE user_id = ? AND chat_id = ?", (int(user_id), int(chat_id)))
            self.conn.commit()

    # ==== کش ذخیره پیوی (آنتی‌حذف + مدیای تایم‌دار) ====
    def upsert_pv_cache(
        self,
        account_id: int,
        chat_id: int,
        message_id: int,
        sender_id: int,
        sender_name: str,
        sender_username: str,
        msg_type: str,
        text_content: str,
        media_path: str = None,
        size_bytes: int = 0,
        is_timed: bool = False,
        status: str = "CACHED",
    ):
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO pv_cache (
                    account_id, chat_id, message_id, sender_id, sender_name,
                    sender_username, msg_type, text_content, media_path,
                    size_bytes, is_timed, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, chat_id, message_id) DO UPDATE SET
                    media_path=COALESCE(excluded.media_path, pv_cache.media_path),
                    size_bytes=CASE WHEN excluded.size_bytes > 0 THEN excluded.size_bytes ELSE pv_cache.size_bytes END,
                    status=excluded.status
                """,
                (
                    int(account_id), int(chat_id), int(message_id),
                    sender_id, sender_name, sender_username, msg_type,
                    text_content, media_path, int(size_bytes),
                    1 if is_timed else 0, status, time.time(),
                ),
            )
            self.conn.commit()

    def get_pv_cache_item(self, account_id: int, chat_id: int, message_id: int):
        with self._lock:
            return self.conn.execute(
                "SELECT text_content FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=? AND status='CACHED'",
                (int(account_id), int(chat_id), int(message_id)),
            ).fetchone()

    def update_pv_cache_text(self, account_id: int, chat_id: int, message_id: int, new_text: str):
        with self._lock:
            self.conn.execute(
                "UPDATE pv_cache SET text_content=? WHERE account_id=? AND chat_id=? AND message_id=?",
                (new_text, int(account_id), int(chat_id), int(message_id)),
            )
            self.conn.commit()

    def pop_pv_cache_by_message_ids(self, account_id: int, message_ids: list):
        if not message_ids:
            return []
        with self._lock:
            placeholders = ",".join("?" for _ in message_ids)
            rows = self.conn.execute(
                f"SELECT account_id, chat_id, message_id, sender_id, sender_name, "
                f"sender_username, msg_type, text_content, media_path, size_bytes, is_timed, status, created_at "
                f"FROM pv_cache WHERE account_id = ? AND message_id IN ({placeholders}) AND status = 'CACHED'",
                [int(account_id), *[int(m) for m in message_ids]],
            ).fetchall()
            if rows:
                self.conn.execute(
                    f"UPDATE pv_cache SET status = 'ARCHIVED' WHERE account_id = ? AND message_id IN ({placeholders})",
                    [int(account_id), *[int(m) for m in message_ids]],
                )
                self.conn.commit()
            return rows

    def get_cache_stats(self, account_id: int = None):
        with self._lock:
            if account_id is not None:
                count, total_bytes = self.conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM pv_cache WHERE account_id=? AND status='CACHED'",
                    (int(account_id),),
                ).fetchone()
            else:
                count, total_bytes = self.conn.execute(
                    "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM pv_cache WHERE status='CACHED'"
                ).fetchone()
            return count, total_bytes

    def enforce_cache_limits(self):
        with self._lock:
            cutoff = time.time() - (CACHE_TTL_DAYS * 86400)
            expired = self.conn.execute(
                "SELECT account_id, chat_id, message_id, media_path FROM pv_cache WHERE created_at < ?",
                (cutoff,),
            ).fetchall()
            for acc_id, chat_id, msg_id, mpath in expired:
                if mpath and os.path.isfile(mpath):
                    try:
                        os.remove(mpath)
                    except OSError:
                        pass
                self.conn.execute(
                    "DELETE FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=?",
                    (acc_id, chat_id, msg_id),
                )

            total_bytes = self.conn.execute(
                "SELECT COALESCE(SUM(size_bytes), 0) FROM pv_cache WHERE status='CACHED'"
            ).fetchone()[0]

            if total_bytes > MAX_CACHE_TOTAL_BYTES:
                oldest = self.conn.execute(
                    "SELECT account_id, chat_id, message_id, media_path, size_bytes "
                    "FROM pv_cache WHERE status='CACHED' ORDER BY created_at ASC"
                ).fetchall()
                for acc_id, chat_id, msg_id, mpath, sz in oldest:
                    if total_bytes <= MAX_CACHE_TOTAL_BYTES:
                        break
                    if mpath and os.path.isfile(mpath):
                        try:
                            os.remove(mpath)
                        except OSError:
                            pass
                    self.conn.execute(
                        "DELETE FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=?",
                        (acc_id, chat_id, msg_id),
                    )
                    total_bytes -= (sz or 0)
            self.conn.commit()

    def clear_account_cache(self, account_id: int):
        with self._lock:
            rows = self.conn.execute(
                "SELECT media_path FROM pv_cache WHERE account_id=?", (int(account_id),)
            ).fetchall()
            for (mpath,) in rows:
                if mpath and os.path.isfile(mpath):
                    try:
                        os.remove(mpath)
                    except OSError:
                        pass
            self.conn.execute("DELETE FROM pv_cache WHERE account_id=?", (int(account_id),))
            self.conn.commit()

    # ==== لیست‌های دشمن / سکوت / ریاکشن / پروفایل ====
    def save_enemies(self, user_id, enemies_set):
        with self._lock:
            ud = self.get_user_data(user_id)
            ud["enemies"] = [list(i) for i in enemies_set]
            self._write_user(user_id, ud)

    def save_muted(self, user_id, muted_set):
        with self._lock:
            ud = self.get_user_data(user_id)
            ud["muted"] = [list(i) for i in muted_set]
            self._write_user(user_id, ud)

    def save_reactions(self, user_id, reactions_dict):
        with self._lock:
            ud = self.get_user_data(user_id)
            ud["reactions"] = reactions_dict
            self._write_user(user_id, ud)

    def save_enemy_queue(self, user_id, queue_list):
        with self._lock:
            ud = self.get_user_data(user_id)
            ud["enemy_queue"] = queue_list
            self._write_user(user_id, ud)

    def save_original_profile(self, user_id, profile_data):
        with self._lock:
            ud = self.get_user_data(user_id)
            ud["original_profile"] = profile_data
            self._write_user(user_id, ud)


data_manager = DataManager(DATA_FILE)
