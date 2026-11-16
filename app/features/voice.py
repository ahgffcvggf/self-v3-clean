"""Text-to-voice command and process lifecycle handling."""
import asyncio
import logging
import os
import re
import uuid

from pyrogram.enums import ChatAction
from app.config import MAX_TTS_CHARS, TTS_VOICES, WORK_DIR, ui_warn
from app.state import TTS_VOICE_GENDER, record_generated_message, safe_call

try:
    import edge_tts
except ImportError:
    edge_tts = None

log = logging.getLogger(__name__)


async def _stop_process(proc):
    if proc.returncode is None:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    try:
        await proc.communicate()
    except Exception:
        pass


async def _synthesize_ogg_voice(text: str, voice_name: str, out_ogg_path: str):
    if edge_tts is None:
        raise RuntimeError("کتابخانه edge-tts نصب نیست.")
    mp3_path = out_ogg_path + ".mp3"
    proc = None
    try:
        await asyncio.wait_for(edge_tts.Communicate(text, voice_name).save(mp3_path), timeout=30)
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", mp3_path, "-c:a", "libopus", "-b:a", "48k", "-vbr", "on", out_ogg_path,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            await _stop_process(proc)
            raise
        if proc.returncode != 0 or not os.path.isfile(out_ogg_path):
            detail = stderr.decode(errors="ignore")[:200] if stderr else ""
            raise RuntimeError(f"تبدیل صوت ناموفق بود: {detail}")
    finally:
        if proc is not None and proc.returncode is None:
            await _stop_process(proc)
        try:
            os.remove(mp3_path)
        except FileNotFoundError:
            pass
        except OSError:
            log.warning("could not remove temporary audio file", exc_info=True)


async def voice_command_handler(client, message):
    raw = (message.text or "").strip()
    match = re.match(r"^\.ویس(?:\s+(.*))?$", raw, re.DOTALL)
    if not match:
        return
    explicit = (match.group(1) or "").strip()
    target = explicit
    reply_to_id = message.reply_to_message.id if message.reply_to_message else None
    if not target and message.reply_to_message:
        target = (message.reply_to_message.text or message.reply_to_message.caption or "").strip()
    if not target:
        await message.edit_text(ui_warn("متنی برای تبدیل به ویس وارد کنید یا روی یک پیام متنی ریپلای بزنید."))
        return
    if len(target) > MAX_TTS_CHARS:
        await message.edit_text(ui_warn(f"طول متن نباید بیشتر از {MAX_TTS_CHARS} کاراکتر باشد."))
        return
    owner_id = client.me.id
    voice_name = TTS_VOICES.get(TTS_VOICE_GENDER.get(owner_id, "female"), TTS_VOICES["female"])
    token = uuid.uuid4().hex
    ogg_path = os.path.join(WORK_DIR, f"tts_{owner_id}_{token}.ogg")
    try:
        try: await client.send_chat_action(message.chat.id, ChatAction.RECORD_AUDIO)
        except Exception: pass
        await _synthesize_ogg_voice(target, voice_name, ogg_path)
        # Keep the command until Telegram confirms the audio upload.
        sent = await safe_call(client.send_voice, message.chat.id, ogg_path, reply_to_message_id=reply_to_id)
        if not sent:
            raise RuntimeError("ارسال ویس ناموفق بود")
        record_generated_message(owner_id, message.chat.id, sent.id)
        try: await message.delete()
        except Exception: pass
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("voice synthesis/upload failed")
        await safe_call(message.reply_text, "❌ خطا در ساخت یا ارسال ویس.")
    finally:
        try: os.remove(ogg_path)
        except FileNotFoundError: pass
        except OSError: log.warning("could not remove temporary voice", exc_info=True)


async def music_placeholder_handler(client, message):
    raw = (message.text or "").strip()
    if not re.match(r"^\.(?:اهنگ|آهنگ)(?:\s+.*)?$", raw, re.DOTALL): return
    await message.edit_text("🎵 بخش دانلود آهنگ **به زودی تکمیل می‌شود**.")
