"""AI assistant handlers with bounded, private service integration."""
import asyncio
import json
import logging
import re
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

import aiohttp
from pyrogram.enums import ChatAction, ParseMode

from app.config import AI_API_KEY, AI_API_URL, AI_MODEL, AI_SYSTEM_PROMPT, ui_toggle
from app.state import AI_ASSISTANT_STATUS, record_generated_message, safe_call
from app.storage.db import data_manager

log = logging.getLogger(__name__)
MAX_AI_INPUT_CHARS = 12_000
MAX_AI_REPLY_CHARS = 100_000
TELEGRAM_TEXT_LIMIT = 4096
AI_MAX_CONCURRENT_PER_ACCOUNT = 2
AI_RATE_WINDOW_SECONDS = 60.0
AI_MAX_REQUESTS_PER_WINDOW = 10
_account_semaphores = defaultdict(lambda: asyncio.Semaphore(AI_MAX_CONCURRENT_PER_ACCOUNT))
_rate_history = defaultdict(deque)
_rate_lock = asyncio.Lock()


def _valid_https_url(url: str) -> bool:
    parsed = urlparse(url or "")
    return parsed.scheme == "https" and bool(parsed.netloc)


def _chunks(text: str, limit: int = TELEGRAM_TEXT_LIMIT):
    """Split without exceeding Telegram's limit, preferring newline/space boundaries."""
    text = str(text)
    while text:
        if len(text) <= limit:
            yield text
            return
        cut = text.rfind("\n", 0, limit + 1)
        if cut < max(1, limit // 2):
            cut = text.rfind(" ", 0, limit + 1)
        if cut < 1:
            cut = limit
        yield text[:cut]
        text = text[cut:]
        if text.startswith(("\n", " ")):
            text = text[1:]


async def _take_rate_slot(account_id):
    key = account_id if account_id is not None else "global"
    now = time.monotonic()
    async with _rate_lock:
        history = _rate_history[key]
        while history and now - history[0] >= AI_RATE_WINDOW_SECONDS:
            history.popleft()
        if len(history) >= AI_MAX_REQUESTS_PER_WINDOW:
            return False
        history.append(now)
        return True


def _extract_response(raw_body: str, content_type: str) -> str:
    if "text/event-stream" in content_type or raw_body.lstrip().startswith("data:"):
        pieces = []
        for line in raw_body.splitlines():
            if not line.strip().startswith("data:"):
                continue
            item = line.strip()[5:].strip()
            if not item or item == "[DONE]":
                continue
            try:
                choice = json.loads(item).get("choices", [{}])[0]
                pieces.append(choice.get("delta", {}).get("content") or choice.get("message", {}).get("content") or "")
            except (ValueError, KeyError, IndexError, TypeError):
                continue
        return "".join(pieces).strip()
    data = json.loads(raw_body)
    return str(data["choices"][0]["message"]["content"]).strip()


async def get_ai_reply(user_message: str, replied_message: str = None, client=None,
                      account_id: int = None, chat_id: int = None, save_history: bool = True):
    """Return an answer; history is read only. Persistence happens after delivery."""
    if not user_message or len(user_message) > MAX_AI_INPUT_CHARS:
        return None
    if not AI_API_KEY or not AI_API_URL or not AI_MODEL or not _valid_https_url(AI_API_URL):
        log.warning("AI configuration is incomplete or not HTTPS")
        return None
    if not await _take_rate_slot(account_id):
        return None
    key = account_id if account_id is not None else "global"
    async with _account_semaphores[key]:
        messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}]
        if account_id is not None and chat_id is not None and save_history:
            for msg_type, content in data_manager.get_chat_history(account_id, chat_id, limit=8):
                messages.append({"role": "user" if msg_type == "user" else "assistant", "content": content})
        if replied_message:
            messages.append({"role": "user", "content": f"پیام ریپلای‌شده:\n{replied_message[:MAX_AI_INPUT_CHARS]}"})
        messages.append({"role": "user", "content": user_message})
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession() as session:
                async with session.post(AI_API_URL, headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
                                        json={"model": AI_MODEL, "messages": messages, "max_tokens": 1200, "stream": False}, timeout=timeout) as response:
                    if response.status != 200:
                        log.error("AI service returned HTTP %s", response.status)
                        return None
                    result = _extract_response(await response.text(), response.headers.get("Content-Type", ""))
                    return result[:MAX_AI_REPLY_CHARS] or None
        except Exception:
            log.exception("AI service request failed")
            return None


async def _persist_delivered(account_id, chat_id, user_message, answer):
    if account_id is not None and chat_id is not None and answer:
        data_manager.save_chat_message(account_id, chat_id, "user", user_message)
        data_manager.save_chat_message(account_id, chat_id, "ai", answer)


async def ai_robot_command_handler(client, message):
    owner_id = client.me.id
    if not AI_ASSISTANT_STATUS.get(owner_id, False) or not message.text:
        return
    match = re.match(r"^\.ربات(?:\s+(.*))?$", message.text.strip(), re.DOTALL)
    if not match:
        return
    query = (match.group(1) or "").strip()
    if not query:
        sent = await safe_call(message.reply_text, "🤖 برای پرسیدن سؤال، متن را بعد از دستور بنویسید.", parse_mode=ParseMode.HTML)
        if sent: record_generated_message(owner_id, message.chat.id, sent.id)
        return
    try: await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception: pass
    replied = None
    if message.reply_to_message:
        replied = message.reply_to_message.text or message.reply_to_message.caption
    answer = await get_ai_reply(query, replied, client, owner_id, message.chat.id)
    if not answer:
        sent = await safe_call(message.reply_text, "❌ سرویس AI در دسترس نیست یا درخواست محدود شده است.")
        if sent: record_generated_message(owner_id, message.chat.id, sent.id)
        return
    delivered = True
    for part in _chunks(answer):
        sent = await safe_call(message.reply_text, part)
        if not sent:
            delivered = False
            break
        record_generated_message(owner_id, message.chat.id, sent.id)
    if delivered:
        await _persist_delivered(owner_id, message.chat.id, query, answer)


async def ai_assistant_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    AI_ASSISTANT_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"ai_assistant": is_on}})
    await message.edit_text(ui_toggle("دستیار AI (.ربات)", is_on))


async def ai_test_handler(client, message):
    await message.edit_text("⏳ در حال تست اتصال دستیار AI...")
    answer = await get_ai_reply("سلام، فقط یک جمله کوتاه بنویس.", save_history=False)
    await message.edit_text(f"✅ سرویس AI متصل است:\n{answer}" if answer else "❌ سرویس AI پاسخ نداد؛ تنظیمات API را بررسی کنید.")
