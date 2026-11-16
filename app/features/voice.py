import asyncio
import logging
import os
import re
import time
from pyrogram.enums import ChatAction
from app.config import MAX_TTS_CHARS, TTS_VOICES, WORK_DIR, ui_warn
from app.state import TTS_VOICE_GENDER, record_generated_message, safe_call

try:
    import edge_tts
except ImportError:
    edge_tts = None


async def _synthesize_ogg_voice(text: str, voice_name: str, out_ogg_path: str):
    if edge_tts is None:
        raise RuntimeError("کتابخانه edge-tts نصب نیست.")

    mp3_path = out_ogg_path + ".mp3"
    try:
        communicate = edge_tts.Communicate(text, voice_name)
        await asyncio.wait_for(communicate.save(mp3_path), timeout=30)

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", mp3_path,
            "-c:a", "libopus", "-b:a", "48k", "-vbr", "on",
            out_ogg_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0 or not os.path.isfile(out_ogg_path):
            raise RuntimeError(f"تبدیل ffmpeg ناموفق بود: {stderr.decode(errors='ignore')[:200]}")
    finally:
        if os.path.isfile(mp3_path):
            try:
                os.remove(mp3_path)
            except OSError:
                pass


async def voice_command_handler(client, message):
    """
    .ویس [متن] -> متن را به ویس تبدیل می‌کند.
    .ویس (روی ریپلای) -> متن یا کپشن پیام مرجع را به ویس تبدیل می‌کند.
    """
    owner_id = client.me.id
    raw = (message.text or "").strip()
    m = re.match(r"^\.ویس(?:\s+(.*))?$", raw, re.DOTALL)
    if not m:
        return

    explicit_text = (m.group(1) or "").strip()
    target_text = explicit_text
    reply_to_id = message.reply_to_message.id if message.reply_to_message else None

    if not target_text and message.reply_to_message:
        target_text = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()

    if not target_text:
        await message.edit_text(ui_warn("متنی برای تبدیل به ویس وارد کنید یا روی یک پیام متنی ریپلای بزنید."))
        return

    if len(target_text) > MAX_TTS_CHARS:
        await message.edit_text(ui_warn(f"طول متن نباید بیشتر از {MAX_TTS_CHARS} کاراکتر باشد."))
        return

    gender = TTS_VOICE_GENDER.get(owner_id, "female")
    voice_name = TTS_VOICES.get(gender, TTS_VOICES["female"])
    ogg_path = os.path.join(WORK_DIR, f"tts_{owner_id}_{int(time.time() * 1000)}.ogg")

    try:
        await client.send_chat_action(message.chat.id, ChatAction.RECORD_AUDIO)
    except Exception:
        pass

    try:
        await _synthesize_ogg_voice(target_text, voice_name, ogg_path)
        try:
            await message.delete()
        except Exception:
            pass
        sent = await safe_call(
            client.send_voice,
            message.chat.id,
            ogg_path,
            reply_to_message_id=reply_to_id,
        )
        if sent:
            record_generated_message(owner_id, message.chat.id, sent.id)
    except Exception as e:
        logging.error(f"خطا در ساخت ویس (.ویس): {e}")
        await message.edit_text(f"❌ خطا در ساخت ویس: {e}")
    finally:
        if os.path.isfile(ogg_path):
            try:
                os.remove(ogg_path)
            except OSError:
                pass


async def music_placeholder_handler(client, message):
    """جایگاه موقت برای دستور .اهنگ و .آهنگ"""
    raw = (message.text or "").strip()
    if not re.match(r"^\.(?:اهنگ|آهنگ)(?:\s+.*)?$", raw, re.DOTALL):
        return
    await message.edit_text("🎵 بخش دانلود آهنگ **به زودی تکمیل می‌شود**.")
