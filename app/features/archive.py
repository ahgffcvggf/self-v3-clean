import html
import logging
import os
from datetime import datetime
from pyrogram.enums import ChatType, ParseMode
from app.config import (
    PRIVATE_CACHE_DIR, MAX_CACHE_FILE_BYTES, TEHRAN_TIMEZONE,
    UI_DIVIDER, ui_toggle
)
from app.state import ANTI_DELETE_STATUS, is_generated_message, safe_call
from app.storage.db import data_manager


def _is_valid_pv_message(client, message) -> bool:
    if not message or not message.chat:
        return False
    if message.chat.type != ChatType.PRIVATE:
        return False
    owner_id = client.me.id
    if message.chat.id == owner_id:
        return False  # Saved Messages
    if not message.from_user or message.from_user.is_bot or message.from_user.is_self:
        return False
    if message.from_user.id == owner_id:
        return False
    if is_generated_message(owner_id, message.chat.id, message.id):
        return False
    if message.service:
        return False
    return True


def _detect_media_info(message):
    """نوع پیام، آبجکت مدیا، حجم و وضعیت تایم‌دار بودن را برمی‌گرداند."""
    if message.photo:
        ttl = getattr(message.photo, "ttl_seconds", None)
        return "عکس" + (" تایم‌دار" if ttl else ""), message.photo, getattr(message.photo, "file_size", 0) or 0, bool(ttl)
    if message.video:
        ttl = getattr(message.video, "ttl_seconds", None)
        return "فیلم" + (" تایم‌دار" if ttl else ""), message.video, getattr(message.video, "file_size", 0) or 0, bool(ttl)
    if message.voice:
        return "ویس", message.voice, getattr(message.voice, "file_size", 0) or 0, False
    if message.video_note:
        return "ویدیو مسیج", message.video_note, getattr(message.video_note, "file_size", 0) or 0, False
    if message.audio:
        return "آهنگ/صدا", message.audio, getattr(message.audio, "file_size", 0) or 0, False
    if message.animation:
        return "گیف", message.animation, getattr(message.animation, "file_size", 0) or 0, False
    if message.sticker:
        return "استیکر", message.sticker, getattr(message.sticker, "file_size", 0) or 0, False
    if message.document:
        return "فایل", message.document, getattr(message.document, "file_size", 0) or 0, False
    if message.location or message.venue:
        return "موقعیت مکانی", None, 0, False
    if message.contact:
        return "مخاطب", None, 0, False
    if message.poll:
        return "نظرسنجی", None, 0, False
    if message.text:
        return "متن", None, 0, False
    return "سایر", None, 0, False


def _format_header(label: str, sender_name: str, sender_username: str, sender_id: int, msg_type: str, sent_time: str) -> str:
    uname = f"@{sender_username}" if sender_username else "ندارد"
    safe_name = html.escape(sender_name or "ناشناس")
    safe_uname = html.escape(uname)
    return (
        f"<b>{html.escape(label)}</b>\n"
        f"{UI_DIVIDER}\n"
        f"• <b>فرستنده:</b> {safe_name} (<code>{sender_id}</code> | {safe_uname})\n"
        f"• <b>نوع محتوا:</b> {html.escape(msg_type)}\n"
        f"• <b>زمان:</b> {html.escape(sent_time)}"
    )


async def _send_archived_item(client, header_html: str, msg_type: str, text_content: str, media_path: str = None):
    caption_body = ""
    if text_content:
        safe_txt = html.escape(text_content[:3000])
        caption_body = f"\n\n<blockquote>{safe_txt}</blockquote>"

    full_caption = header_html + caption_body

    if media_path and os.path.isfile(media_path):
        try:
            if "عکس" in msg_type:
                await safe_call(client.send_photo, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            elif "فیلم" in msg_type:
                await safe_call(client.send_video, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            elif msg_type == "ویس":
                await safe_call(client.send_voice, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            elif msg_type == "ویدیو مسیج":
                await safe_call(client.send_message, "me", header_html, parse_mode=ParseMode.HTML)
                await safe_call(client.send_video_note, "me", media_path)
            elif msg_type == "آهنگ/صدا":
                await safe_call(client.send_audio, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            elif msg_type == "گیف":
                await safe_call(client.send_animation, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            else:
                await safe_call(client.send_document, "me", media_path, caption=full_caption[:1024], parse_mode=ParseMode.HTML)
            return True
        except Exception as e:
            logging.error(f"خطا در ارسال مدیای آرشیوشده به Saved Messages: {e}")

    await safe_call(client.send_message, "me", full_caption[:4096], parse_mode=ParseMode.HTML)
    return True


async def pv_archive_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    ANTI_DELETE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"anti_delete": is_on}})
    await message.edit_text(ui_toggle("ذخیره پیوی (آنتی‌حذف + مدیای تایم‌دار)", is_on))


async def pv_archive_incoming_handler(client, message):
    """
    دریافت پیام‌های پیوی اشخاص وقتی ذخیره پیوی روشن است:
    - مدیای تایم‌دار: بلافاصله دانلود و در Saved Messages ذخیره می‌شود.
    - پیام/مدیای عادی: در کش موقت ذخیره می‌شود تا فقط در صورت حذف یا ویرایش به Saved Messages برود.
    """
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False):
        return
    if not _is_valid_pv_message(client, message):
        return

    msg_type, media_obj, file_size, is_timed = _detect_media_info(message)
    sender = message.from_user
    sender_name = " ".join(p for p in [sender.first_name, sender.last_name] if p).strip() or "ناشناس"
    sender_username = sender.username or ""
    text_content = message.text or message.caption or ""
    if message.poll and not text_content:
        text_content = f"نظرسنجی: {message.poll.question}"
    elif message.contact and not text_content:
        text_content = f"مخاطب: {message.contact.first_name} ({message.contact.phone_number})"
    elif message.location and not text_content:
        text_content = f"موقعیت: {message.location.latitude}, {message.location.longitude}"

    sent_time = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S")
    media_path = None
    actual_size = 0

    if media_obj is not None:
        if file_size > MAX_CACHE_FILE_BYTES:
            note = f"\n[فایل با حجم بیش از ۵۰ مگابایت کش نشد: {file_size // (1024*1024)} MB]"
            text_content = (text_content + note).strip()
        else:
            acc_dir = os.path.join(PRIVATE_CACHE_DIR, str(owner_id))
            os.makedirs(acc_dir, exist_ok=True)
            target_prefix = os.path.join(acc_dir, f"{message.chat.id}_{message.id}_")
            try:
                downloaded = await client.download_media(message, file_name=target_prefix)
                if downloaded and os.path.isfile(downloaded):
                    media_path = downloaded
                    actual_size = os.path.getsize(downloaded)
            except Exception as e:
                logging.warning(f"دانلود مدیا برای کش پیوی ناموفق بود ({message.id}): {e}")

    if is_timed:
        header = _format_header(
            "⏳ ذخیرهٔ خودکار محتوای تایم‌دار",
            sender_name, sender_username, sender.id, msg_type, sent_time
        )
        await _send_archived_item(client, header, msg_type, text_content, media_path)
        if media_path and os.path.isfile(media_path):
            try:
                os.remove(media_path)
            except OSError:
                pass
        data_manager.upsert_pv_cache(
            owner_id, message.chat.id, message.id,
            sender.id, sender_name, sender_username,
            msg_type, text_content, None, 0, True, "ARCHIVED"
        )
        return

    data_manager.upsert_pv_cache(
        owner_id, message.chat.id, message.id,
        sender.id, sender_name, sender_username,
        msg_type, text_content, media_path, actual_size, False, "CACHED"
    )
    data_manager.enforce_cache_limits()


async def pv_archive_edited_handler(client, message):
    """اگر پیامی در پیوی ویرایش شود و متن آن تغییر کرده باشد، متن قبلی و جدید در Saved Messages ثبت می‌شود."""
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False):
        return
    if not _is_valid_pv_message(client, message):
        return

    new_text = message.text or message.caption or ""
    old_row = data_manager.get_pv_cache_item(owner_id, message.chat.id, message.id)
    if not old_row:
        return

    old_text = old_row[0] or ""
    if not old_text or old_text == new_text:
        return

    sender = message.from_user
    sender_name = " ".join(p for p in [sender.first_name, sender.last_name] if p).strip() or "ناشناس"
    sender_username = sender.username or ""
    edit_time = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S")

    header = _format_header(
        "✏️ پیام ویرایش‌شده در پیوی",
        sender_name, sender_username, sender.id, "ویرایش متن", edit_time
    )
    body = (
        f"{header}\n\n"
        f"<b>متن قبلی:</b>\n<blockquote>{html.escape(old_text[:1500])}</blockquote>\n"
        f"<b>متن جدید:</b>\n<blockquote>{html.escape(new_text[:1500])}</blockquote>"
    )
    await safe_call(client.send_message, "me", body[:4096], parse_mode=ParseMode.HTML)

    data_manager.update_pv_cache_text(owner_id, message.chat.id, message.id, new_text)


async def pv_archive_deleted_handler(client, messages):
    """وقتی پیامی در پیوی حذف می‌شود، از کش برداشته و در Saved Messages آرشیو می‌کند."""
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False):
        return
    msg_ids = [dm.id for dm in messages if getattr(dm, "id", None)]
    if not msg_ids:
        return

    rows = data_manager.pop_pv_cache_by_message_ids(owner_id, msg_ids)
    del_time = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S")

    for row in rows:
        (
            _acc_id, _chat_id, _msg_id, sender_id, sender_name,
            sender_username, msg_type, text_content, media_path,
            _sz, is_timed, _status, _created
        ) = row
        if is_timed:
            continue
        header = _format_header(
            "🗑 پیام حذف‌شده",
            sender_name, sender_username, sender_id or 0, msg_type, del_time
        )
        try:
            await _send_archived_item(client, header, msg_type, text_content, media_path)
        finally:
            if media_path and os.path.isfile(media_path):
                try:
                    os.remove(media_path)
                except OSError:
                    pass
