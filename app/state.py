import asyncio
import logging
from collections import deque
from pyrogram.errors import FloodWait

# وضعیت‌های فعال در حافظه برای هر اکانت (user_id)
ACTIVE_BOTS = {}
LOGIN_STATES = {}
ADMIN_STATES = {}

USER_FONT_CHOICES = {}
CLOCK_STATUS = {}
BIO_TIME_STATUS = {}
BIO_CUSTOM_TEXT = {}
BIO_DATE_FORMAT = {}
BIO_UPDATE_TASKS = {}

BOLD_MODE_STATUS = {}
HASHTAG_MODE_STATUS = {}
STRIKETHROUGH_MODE_STATUS = {}
SINGLE_MODE_STATUS = {}
CHAR_MODE_STATUS = {}

ANTI_DELETE_STATUS = {}
TYPING_MODE_STATUS = {}
PLAYING_MODE_STATUS = {}
ONLINE_MODE_STATUS = {}
ONLINE_MODE_TASKS = {}

COMMENT_MODE_STATUS = {}
COMMENT_TEXT = {}

AUTO_TRANSLATE_TARGET = {}
AI_ASSISTANT_STATUS = {}
TTS_VOICE_GENDER = {}   # "female" | "male"

COPY_MODE_STATUS = {}
ORIGINAL_PROFILE_DATA = {}
GLOBAL_ENEMY_STATUS = {}
ACTIVE_ENEMIES = {}
ENEMY_REPLY_QUEUES = {}
MUTED_USERS = {}
AUTO_REACTION_TARGETS = {}

# ثبت شناسه پیام‌های تولیدشده توسط ربات (جلوگیری از حلقه AI/ترجمه/آرشیو)
GENERATED_MSG_IDS = {}

def record_generated_message(account_id: int, chat_id: int, message_id: int):
    buf = GENERATED_MSG_IDS.setdefault(account_id, deque(maxlen=500))
    key = (chat_id, message_id)
    if key not in buf:
        buf.append(key)

def is_generated_message(account_id: int, chat_id: int, message_id: int) -> bool:
    buf = GENERATED_MSG_IDS.get(account_id)
    return bool(buf and (chat_id, message_id) in buf)

async def safe_call(coro_func, *args, max_retries=2, **kwargs):
    for attempt in range(max_retries + 1):
        try:
            return await coro_func(*args, **kwargs)
        except FloodWait as e:
            wait_for = e.value + 1
            logging.warning(f"FloodWait: صبر برای {wait_for} ثانیه (تلاش {attempt+1}/{max_retries+1})")
            if attempt == max_retries:
                raise
            await asyncio.sleep(wait_for)
    return None

def load_all_states(data_manager):
    users_data = data_manager.get_all_users()
    for user_id_str, user_data in users_data.items():
        user_id = int(user_id_str)
        settings = user_data.get("settings", {})

        USER_FONT_CHOICES[user_id] = settings.get("font", "stylized")
        CLOCK_STATUS[user_id] = settings.get("clock", True)
        BIO_TIME_STATUS[user_id] = settings.get("bio_time", False)
        BIO_CUSTOM_TEXT[user_id] = settings.get("bio_text", "")
        BIO_DATE_FORMAT[user_id] = settings.get("bio_date_format", None)

        BOLD_MODE_STATUS[user_id] = settings.get("bold", False)
        HASHTAG_MODE_STATUS[user_id] = settings.get("hashtag", False)
        STRIKETHROUGH_MODE_STATUS[user_id] = settings.get("strikethrough", False)
        SINGLE_MODE_STATUS[user_id] = settings.get("single_mode", False)
        CHAR_MODE_STATUS[user_id] = settings.get("char_mode", False)

        ANTI_DELETE_STATUS[user_id] = settings.get("anti_delete", False)
        TYPING_MODE_STATUS[user_id] = settings.get("typing", False)
        PLAYING_MODE_STATUS[user_id] = settings.get("playing", False)
        ONLINE_MODE_STATUS[user_id] = settings.get("online_mode", False)

        COMMENT_MODE_STATUS[user_id] = settings.get("comment_mode", False)
        COMMENT_TEXT[user_id] = settings.get("comment_text", "کامنت تنظیم نشده")

        AUTO_TRANSLATE_TARGET[user_id] = settings.get("translate", None)
        AI_ASSISTANT_STATUS[user_id] = settings.get("ai_assistant", False)
        TTS_VOICE_GENDER[user_id] = settings.get("tts_voice", "female")

        COPY_MODE_STATUS[user_id] = settings.get("copy_mode", False)
        GLOBAL_ENEMY_STATUS[user_id] = settings.get("global_enemy", False)
        ORIGINAL_PROFILE_DATA[user_id] = user_data.get("original_profile", {})
        ACTIVE_ENEMIES[user_id] = set(tuple(item) for item in user_data.get("enemies", []))
        MUTED_USERS[user_id] = set(tuple(item) for item in user_data.get("muted", []))
        AUTO_REACTION_TARGETS[user_id] = user_data.get("reactions", {})
        ENEMY_REPLY_QUEUES[user_id] = user_data.get("enemy_queue", [])
