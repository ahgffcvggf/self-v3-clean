import asyncio
import html
import logging
import os
from datetime import datetime
from pyrogram.enums import ChatType, ParseMode
from app.config import PRIVATE_CACHE_DIR, MAX_CACHE_FILE_BYTES, TEHRAN_TIMEZONE, UI_DIVIDER, ui_toggle
from app.state import ACTIVE_BOTS, ANTI_DELETE_STATUS, is_generated_message, safe_call
from app.storage.db import data_manager


def _is_valid_pv_message(client, message):
    if not message or not message.chat or message.chat.type != ChatType.PRIVATE: return False
    owner_id = client.me.id
    return (message.chat.id != owner_id and message.from_user and not message.from_user.is_bot and not message.from_user.is_self and message.from_user.id != owner_id and not is_generated_message(owner_id, message.chat.id, message.id) and not message.service)


def _detect_media_info(message):
    for attr, label in (("photo", "عکس"), ("video", "فیلم"), ("voice", "ویس"), ("video_note", "ویدیو مسیج"), ("audio", "آهنگ/صدا"), ("animation", "گیف"), ("sticker", "استیکر"), ("document", "فایل")):
        obj = getattr(message, attr, None)
        if obj:
            ttl = getattr(obj, "ttl_seconds", None) if attr in ("photo", "video") else None
            return label + (" تایم‌دار" if ttl else ""), obj, getattr(obj, "file_size", 0) or 0, bool(ttl)
    if message.location or message.venue: return "موقعیت مکانی", None, 0, False
    if message.contact: return "مخاطب", None, 0, False
    if message.poll: return "نظرسنجی", None, 0, False
    if message.text: return "متن", None, 0, False
    return "سایر", None, 0, False


def _format_header(label, sender_name, sender_username, sender_id, msg_type, sent_time):
    uname = f"@{sender_username}" if sender_username else "ندارد"
    return (f"<b>{html.escape(label)}</b>\n{UI_DIVIDER}\n• <b>فرستنده:</b> {html.escape(sender_name or 'ناشناس')} (<code>{sender_id}</code> | {html.escape(uname)})\n• <b>نوع محتوا:</b> {html.escape(msg_type)}\n• <b>زمان:</b> {html.escape(sent_time)}")


def _text_chunks(text, limit=4000):
    """Escape per character, never split an entity or UTF-16 surrogate pair."""
    chunk, size = [], 0
    for char in text or "":
        escaped = html.escape(char)
        units = len(escaped.encode("utf-16-le")) // 2
        if size + units > limit:
            yield "".join(chunk)
            chunk, size = [], 0
        chunk.append(escaped)
        size += units
    if chunk:
        yield "".join(chunk)


async def _send_text(client, header_html, text_content):
    chunks = list(_text_chunks(text_content))
    body = header_html + ("\n\n<blockquote>" + chunks[0] + "</blockquote>" if chunks else "")
    if len(chunks) <= 1 and len(body.encode("utf-16-le")) // 2 <= 4096:
        await safe_call(client.send_message, "me", body, parse_mode=ParseMode.HTML)
        return
    await safe_call(client.send_message, "me", header_html, parse_mode=ParseMode.HTML)
    for chunk in chunks:
        await safe_call(client.send_message, "me", "<blockquote>" + chunk + "</blockquote>", parse_mode=ParseMode.HTML)


async def _send_archived_item(client, header_html, msg_type, text_content, media_path=None):
    caption = header_html if len(header_html.encode("utf-16-le")) // 2 <= 1024 else ""
    if media_path and os.path.isfile(media_path):
        try:
            if "عکس" in msg_type: await safe_call(client.send_photo, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            elif "فیلم" in msg_type: await safe_call(client.send_video, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            elif msg_type == "ویس": await safe_call(client.send_voice, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            elif msg_type == "ویدیو مسیج":
                await safe_call(client.send_message, "me", header_html, parse_mode=ParseMode.HTML); await safe_call(client.send_video_note, "me", media_path)
            elif msg_type == "آهنگ/صدا": await safe_call(client.send_audio, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            elif msg_type == "گیف": await safe_call(client.send_animation, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            else: await safe_call(client.send_document, "me", media_path, caption=caption, parse_mode=ParseMode.HTML)
            await _send_text(client, header_html if not caption else "<b>متن پیام</b>", text_content)
            return True
        except Exception:
            logging.exception("Archived media delivery failed"); raise
    if media_path:
        raise FileNotFoundError("Archived media is missing; preserving pending record")
    await _send_text(client, header_html, text_content)
    return True


async def pv_archive_toggle_handler(client, message):
    user_id = client.me.id; is_on = "روشن" in message.text; ANTI_DELETE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"anti_delete": is_on}}); await message.edit_text(ui_toggle("ذخیره پیوی (آنتی‌حذف + مدیای تایم‌دار)", is_on))


async def pv_archive_incoming_handler(client, message):
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False) or not _is_valid_pv_message(client, message): return
    msg_type, media_obj, file_size, is_timed = _detect_media_info(message); sender = message.from_user
    sender_name = " ".join(p for p in [sender.first_name, sender.last_name] if p).strip() or "ناشناس"; text_content = message.text or message.caption or ""
    if message.poll and not text_content: text_content = f"نظرسنجی: {message.poll.question}"
    elif message.contact and not text_content: text_content = f"مخاطب: {message.contact.first_name} ({message.contact.phone_number})"
    elif message.location and not text_content: text_content = f"موقعیت: {message.location.latitude}, {message.location.longitude}"
    media_path, actual_size = None, 0
    if media_obj is not None and file_size <= MAX_CACHE_FILE_BYTES:
        acc_dir = os.path.join(PRIVATE_CACHE_DIR, str(owner_id)); os.makedirs(acc_dir, exist_ok=True)
        try:
            downloaded = await client.download_media(message, file_name=os.path.join(acc_dir, f"{message.chat.id}_{message.id}_"))
            if downloaded and os.path.isfile(downloaded): media_path, actual_size = downloaded, os.path.getsize(downloaded)
        except Exception as exc: logging.warning("Media cache download failed (%s): %s", message.id, exc)
    if media_obj is not None and file_size > MAX_CACHE_FILE_BYTES: text_content = (text_content + f"\n[فایل بیش از سقف کش: {file_size // (1024*1024)} MB]").strip()
    if is_timed:
        header = _format_header("⏳ ذخیرهٔ خودکار محتوای تایم‌دار", sender_name, sender.username or "", sender.id, msg_type, datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S"))
        try: await _send_archived_item(client, header, msg_type, text_content, media_path)
        finally:
            if media_path and os.path.isfile(media_path):
                try: os.remove(media_path)
                except OSError: pass
        data_manager.upsert_pv_cache(owner_id, message.chat.id, message.id, sender.id, sender_name, sender.username or "", msg_type, text_content, None, 0, True, "ARCHIVED"); return
    data_manager.upsert_pv_cache(owner_id, message.chat.id, message.id, sender.id, sender_name, sender.username or "", msg_type, text_content, media_path, actual_size); data_manager.enforce_cache_limits()


async def pv_archive_edited_handler(client, message):
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False) or not _is_valid_pv_message(client, message): return
    new_text = message.text or message.caption or ""; old_row = data_manager.get_pv_cache_item(owner_id, message.chat.id, message.id)
    if not old_row or old_row[0] == new_text: return
    sender = message.from_user; old_text = old_row[0] or ""
    header = _format_header("✏️ پیام ویرایش‌شده در پیوی", " ".join(p for p in [sender.first_name, sender.last_name] if p).strip() or "ناشناس", sender.username or "", sender.id, "ویرایش متن", datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S"))
    body = f"{header}\n\n<b>متن قبلی:</b>\n<blockquote>{html.escape(old_text)}</blockquote>\n<b>متن جدید:</b>\n<blockquote>{html.escape(new_text)}</blockquote>"
    await safe_call(client.send_message, "me", body[:4096], parse_mode=ParseMode.HTML); data_manager.update_pv_cache_text(owner_id, message.chat.id, message.id, new_text)


async def pv_archive_deleted_handler(client, messages):
    owner_id = client.me.id
    if not ANTI_DELETE_STATUS.get(owner_id, False): return
    for dm in messages:
        msg_id = getattr(dm, "id", None); chat_id = getattr(getattr(dm, "chat", None), "id", None)
        rows = data_manager.pop_pv_cache_by_message_ids(owner_id, [msg_id], chat_id=chat_id) if msg_id else []
        for row in rows:
            _, row_chat, row_msg, sender_id, sender_name, sender_username, msg_type, text_content, media_path, _, is_timed, _, _ = row
            if is_timed: continue
            header = _format_header("🗑 پیام حذف‌شده", sender_name, sender_username, sender_id or 0, msg_type, datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M:%S"))
            try: await _send_archived_item(client, header, msg_type, text_content, media_path)
            except Exception: logging.exception("Archive delivery failed for %s/%s; leaving pending", row_chat, row_msg); continue
            data_manager.mark_archive_success(owner_id, row_chat, row_msg)
            if media_path and os.path.isfile(media_path):
                try: os.remove(media_path)
                except OSError: pass


async def _deliver_pending(client, row, manager):
    account, chat, msg, sender, name, username, kind, text, path, _, timed, _, _ = row
    label = "⏳ ذخیرهٔ خودکار محتوای تایم‌دار" if timed else "🗑 پیام حذف‌شده"
    header = _format_header(label, name, username, sender or 0, kind, datetime.fromtimestamp(row[12], TEHRAN_TIMEZONE).strftime("%H:%M:%S"))
    try:
        await _send_archived_item(client, header, kind, text, path)
    except Exception:
        logging.warning("Archive delivery failed for %s/%s; leaving pending", chat, msg)
        return False
    manager.mark_archive_success(account, chat, msg)
    if path and os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            logging.warning("Could not remove delivered archive media")
    return True


async def archive_maintenance(manager=data_manager, clients=None):
    """One maintenance pass; retry up to 100 pending rows per active account.

    Call periodically from the application lifecycle. Delivery is at-least-once;
    partial multi-message delivery may be repeated after a network failure.
    Retention/quota expiration remains authoritative for pending rows too.
    """
    manager.enforce_cache_limits()
    for account, entry in list((ACTIVE_BOTS if clients is None else clients).items()):
        client = entry[0] if isinstance(entry, tuple) else entry
        if not ANTI_DELETE_STATUS.get(account, False):
            continue
        for row in manager.get_pending_archives(account):
            await _deliver_pending(client, row, manager)
    await asyncio.sleep(0)
