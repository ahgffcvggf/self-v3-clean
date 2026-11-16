import json
import logging
import os
import sqlite3
import threading
import time
from cryptography.fernet import Fernet, InvalidToken
from app.config import DATA_FILE, CACHE_TTL_DAYS, MAX_CACHE_TOTAL_BYTES


class DataManager:
    def __init__(self, file_path=DATA_FILE):
        self.file_path = file_path
        self._lock = threading.RLock()
        if str(self.file_path) != ":memory:":
            fd = os.open(self.file_path, os.O_CREAT | os.O_RDWR, 0o600)
            os.fchmod(fd, 0o600)
            os.close(fd)
        self.conn = sqlite3.connect(self.file_path, check_same_thread=False)
        self.conn.execute("PRAGMA secure_delete=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        logging.info("SQLite database connected: %s", self.file_path)

    def _init_schema(self):
        with self._lock:
            self.conn.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, phone TEXT, session_string TEXT, data TEXT NOT NULL)""")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chat_id INTEGER DEFAULT 0,
                message_type TEXT, content TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cols = [r[1] for r in self.conn.execute("PRAGMA table_info(chat_history)").fetchall()]
            if "chat_id" not in cols:
                self.conn.execute("ALTER TABLE chat_history ADD COLUMN chat_id INTEGER DEFAULT 0")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS pv_cache (
                account_id INTEGER NOT NULL, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL,
                sender_id INTEGER, sender_name TEXT, sender_username TEXT, msg_type TEXT,
                text_content TEXT, media_path TEXT, size_bytes INTEGER DEFAULT 0,
                is_timed INTEGER DEFAULT 0, status TEXT DEFAULT 'CACHED', created_at REAL NOT NULL,
                PRIMARY KEY (account_id, chat_id, message_id))""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_hist_acc_chat ON chat_history(user_id, chat_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pv_cache_msg ON pv_cache(account_id, message_id)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_pv_cache_created ON pv_cache(created_at)")
            self.conn.commit()

    @staticmethod
    def _default_user_structure(user_id):
        return {"user_id": user_id, "phone": "", "first_name": "", "username": "",
                "session_string": "", "settings": {"font": "stylized", "clock": True,
                "bio_time": False, "bio_text": "", "bio_date_format": None, "bold": False,
                "hashtag": False, "strikethrough": False, "single_mode": False, "char_mode": False,
                "anti_delete": False, "typing": False, "playing": False, "online_mode": False,
                "comment_mode": False, "comment_text": "کامنت تنظیم نشده", "translate": None,
                "ai_assistant": False, "tts_voice": "female", "copy_mode": False, "global_enemy": False},
                "enemies": [], "muted": [], "reactions": {}, "enemy_queue": []}

    @staticmethod
    def _fernet(required=False):
        key = os.environ.get("SESSION_ENCRYPTION_KEY", "")
        if required and not key:
            raise RuntimeError("SESSION_ENCRYPTION_KEY is required to save a real session")
        if not key:
            return None
        try:
            return Fernet(key.encode())
        except Exception as exc:
            raise RuntimeError("SESSION_ENCRYPTION_KEY is invalid") from exc

    def _decrypt_session(self, value):
        if not value:
            return ""
        if not value.startswith("enc:"):
            return value
        f = self._fernet(required=True)
        try:
            return f.decrypt(value[4:].encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("SESSION_ENCRYPTION_KEY is missing or cannot decrypt stored session") from exc

    def _write_user(self, user_id, user_data):
        plain = user_data.get("session_string") or ""
        encrypted = ""
        if plain:
            encrypted = "enc:" + self._fernet(required=True).encrypt(plain.encode()).decode()
        stored = dict(user_data)
        stored["session_string"] = ""
        stored.pop("session", None)
        self.conn.execute("""INSERT INTO users (user_id, phone, session_string, data) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone, session_string=excluded.session_string,
            data=excluded.data""", (int(user_id), user_data.get("phone") or None, encrypted,
            json.dumps(stored, ensure_ascii=False)))
        self.conn.commit()

    def get_user_data(self, user_id):
        with self._lock:
            row = self.conn.execute("SELECT session_string, data, phone FROM users WHERE user_id=?", (int(user_id),)).fetchone()
            default = self._default_user_structure(user_id)
            if row is None:
                self._write_user(user_id, default)
                return default
            user_data = json.loads(row[1])
            db_session = self._decrypt_session(row[0] or "")
            legacy = user_data.get("session_string") or user_data.get("session") or ""
            user_data["phone"] = row[2] or user_data.get("phone", "")
            session = db_session or legacy
            user_data["session_string"] = session
            changed = False
            for key, value in default.items():
                if key not in user_data:
                    user_data[key] = value
                    changed = True
                elif key == "settings":
                    if not isinstance(user_data.get("settings"), dict):
                        user_data["settings"] = {}
                        changed = True
                    for sk, sv in value.items():
                        if sk not in user_data["settings"]:
                            user_data["settings"][sk] = sv
                            changed = True
            if legacy or changed or (row[0] and not row[0].startswith("enc:")):
                self._write_user(user_id, user_data)
            user_data.pop("session", None)
            return user_data

    def update_user_data(self, user_id, updates):
        with self._lock:
            data = self.get_user_data(user_id)
            for key, value in updates.items():
                if key == "settings" and isinstance(value, dict):
                    data.setdefault("settings", {}).update(value)
                else:
                    data[key] = value
            self._write_user(user_id, data)
            return data

    def save_session(self, phone, session_string, user_id, first_name="", username=""):
        with self._lock:
            data = self.get_user_data(user_id)
            data.update(phone=phone, session_string=session_string, first_name=first_name, username=username)
            self._write_user(user_id, data)

    def get_all_sessions(self):
        with self._lock:
            rows = self.conn.execute("SELECT user_id FROM users").fetchall()
            sessions = []
            for (user_id,) in rows:
                data = self.get_user_data(user_id)
                if data.get("phone") and data.get("session_string"):
                    sessions.append((data["phone"], {"string": data["session_string"], "user_id": user_id}))
            return sessions

    def get_all_users(self):
        with self._lock:
            return {str(r[0]): self.get_user_data(r[0]) for r in self.conn.execute("SELECT user_id FROM users").fetchall()}

    def delete_user(self, user_id):
        with self._lock:
            self.clear_chat_history(user_id)
            self.clear_account_cache(user_id)
            self.conn.execute("DELETE FROM users WHERE user_id=?", (int(user_id),))
            self.conn.commit()

    def get_stats(self):
        with self._lock:
            return (self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], self.conn.execute("SELECT COUNT(*) FROM users WHERE phone IS NOT NULL AND phone != '' AND session_string IS NOT NULL AND session_string != ''").fetchone()[0])

    def save_chat_message(self, user_id, chat_id, message_type, content):
        with self._lock:
            self.conn.execute("INSERT INTO chat_history (user_id, chat_id, message_type, content) VALUES (?, ?, ?, ?)", (int(user_id), int(chat_id), message_type, content))
            self.conn.execute("DELETE FROM chat_history WHERE user_id=? AND chat_id=? AND id NOT IN (SELECT id FROM chat_history WHERE user_id=? AND chat_id=? ORDER BY id DESC LIMIT 100)", (int(user_id), int(chat_id), int(user_id), int(chat_id)))
            self.conn.commit()

    def get_chat_history(self, user_id, chat_id, limit=10):
        limit = max(0, min(int(limit), 100))
        with self._lock:
            rows = self.conn.execute("SELECT message_type, content FROM chat_history WHERE user_id=? AND chat_id=? ORDER BY id DESC LIMIT ?", (int(user_id), int(chat_id), limit)).fetchall()
            return list(reversed(rows))

    def clear_chat_history(self, user_id, chat_id=None):
        with self._lock:
            sql, args = ("DELETE FROM chat_history WHERE user_id=?", (int(user_id),)) if chat_id is None else ("DELETE FROM chat_history WHERE user_id=? AND chat_id=?", (int(user_id), int(chat_id)))
            self.conn.execute(sql, args); self.conn.commit()

    def upsert_pv_cache(self, account_id, chat_id, message_id, sender_id, sender_name, sender_username, msg_type, text_content, media_path=None, size_bytes=0, is_timed=False, status="CACHED"):
        with self._lock:
            self.conn.execute("""INSERT INTO pv_cache (account_id,chat_id,message_id,sender_id,sender_name,sender_username,msg_type,text_content,media_path,size_bytes,is_timed,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(account_id,chat_id,message_id) DO UPDATE SET text_content=excluded.text_content, media_path=COALESCE(excluded.media_path,pv_cache.media_path), size_bytes=CASE WHEN excluded.size_bytes>0 THEN excluded.size_bytes ELSE pv_cache.size_bytes END, status=excluded.status""", (int(account_id),int(chat_id),int(message_id),sender_id,sender_name,sender_username,msg_type,text_content,media_path,int(size_bytes),int(bool(is_timed)),status,time.time()))
            self.conn.commit()

    def get_pv_cache_item(self, account_id, chat_id, message_id):
        with self._lock:
            return self.conn.execute("SELECT text_content FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=? AND status IN ('CACHED','PENDING')", (int(account_id),int(chat_id),int(message_id))).fetchone()

    def update_pv_cache_text(self, account_id, chat_id, message_id, new_text):
        with self._lock:
            self.conn.execute("UPDATE pv_cache SET text_content=? WHERE account_id=? AND chat_id=? AND message_id=?", (new_text,int(account_id),int(chat_id),int(message_id))); self.conn.commit()

    def pop_pv_cache_by_message_ids(self, account_id, message_ids, chat_id=None):
        if not message_ids: return []
        with self._lock:
            args = [int(account_id)] + [int(m) for m in message_ids]
            where = f"account_id=? AND message_id IN ({','.join('?' for _ in message_ids)}) AND status IN ('CACHED','PENDING')"
            if chat_id is not None: where += " AND chat_id=?"; args.append(int(chat_id))
            rows = self.conn.execute(f"SELECT account_id,chat_id,message_id,sender_id,sender_name,sender_username,msg_type,text_content,media_path,size_bytes,is_timed,status,created_at FROM pv_cache WHERE {where}", args).fetchall()
            if rows:
                self.conn.execute(f"UPDATE pv_cache SET status='PENDING' WHERE {where}", args); self.conn.commit()
            return [tuple(r[:11]) + ("PENDING", r[12]) for r in rows]

    def get_pending_archives(self, account_id, limit=100):
        with self._lock:
            return self.conn.execute("SELECT account_id,chat_id,message_id,sender_id,sender_name,sender_username,msg_type,text_content,media_path,size_bytes,is_timed,status,created_at FROM pv_cache WHERE account_id=? AND status='PENDING' ORDER BY created_at LIMIT ?", (int(account_id), max(0, min(int(limit), 100)))).fetchall()

    def mark_archive_success(self, account_id, chat_id, message_id):
        with self._lock:
            self.conn.execute("DELETE FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=? AND status='PENDING'", (int(account_id),int(chat_id),int(message_id))); self.conn.commit()

    def get_cache_stats(self, account_id=None):
        with self._lock:
            clause, args = ("", ()) if account_id is None else (" AND account_id=?", (int(account_id),))
            return self.conn.execute(f"SELECT COUNT(*),COALESCE(SUM(size_bytes),0) FROM pv_cache WHERE status IN ('CACHED','PENDING'){clause}", args).fetchone()

    def enforce_cache_limits(self, ttl_days=None, max_bytes=None):
        ttl_days = CACHE_TTL_DAYS if ttl_days is None else max(0, float(ttl_days)); max_bytes = MAX_CACHE_TOTAL_BYTES if max_bytes is None else max(0, int(max_bytes))
        with self._lock:
            rows = self.conn.execute("SELECT account_id,chat_id,message_id,media_path FROM pv_cache WHERE created_at<?", (time.time()-ttl_days*86400,)).fetchall()
            for row in rows: self._remove_cache_row(row[:3], row[3])
            total = self.conn.execute("SELECT COALESCE(SUM(size_bytes),0) FROM pv_cache WHERE status IN ('CACHED','PENDING')").fetchone()[0]
            for acc,chat,msg,path,size in self.conn.execute("SELECT account_id,chat_id,message_id,media_path,size_bytes FROM pv_cache WHERE status IN ('CACHED','PENDING') ORDER BY created_at").fetchall():
                if total <= max_bytes: break
                self._remove_cache_row((acc,chat,msg), path); total -= size or 0
            self.conn.commit()

    def _remove_cache_row(self, key, media_path):
        if media_path and os.path.isfile(media_path):
            try: os.remove(media_path)
            except OSError: pass
        self.conn.execute("DELETE FROM pv_cache WHERE account_id=? AND chat_id=? AND message_id=?", key)

    def clear_account_cache(self, account_id):
        with self._lock:
            for (path,) in self.conn.execute("SELECT media_path FROM pv_cache WHERE account_id=?", (int(account_id),)).fetchall():
                if path and os.path.isfile(path):
                    try: os.remove(path)
                    except OSError: pass
            self.conn.execute("DELETE FROM pv_cache WHERE account_id=?", (int(account_id),)); self.conn.commit()


data_manager = DataManager(DATA_FILE)
