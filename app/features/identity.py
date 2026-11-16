import html
import re
from pyrogram.enums import ParseMode
from app.config import UI_DIVIDER

_ID_ESTIMATION_ANCHORS = [
    (2768409, "حدود ۲۰۱۳"),
    (100000000, "حدود ۲۰۱۴ تا ۲۰۱۵"),
    (300000000, "حدود ۲۰۱۶ تا ۲۰۱۷"),
    (600000000, "حدود ۲۰۱۸"),
    (1000000000, "حدود ۲۰۱۹ تا ۲۰۲۰"),
    (1800000000, "حدود ۲۰۲۱"),
    (5000000000, "حدود ۲۰۲۲"),
    (6000000000, "حدود ۲۰۲۳"),
    (7000000000, "حدود ۲۰۲۴"),
    (7800000000, "حدود ۲۰۲۵"),
]


def estimate_account_creation(user_id: int) -> str:
    if not user_id or user_id <= 0:
        return "نامشخص"
    for threshold, label in _ID_ESTIMATION_ANCHORS:
        if user_id < threshold:
            return f"تقریبی ({label})"
    return "تقریبی (۲۰۲۵ تا ۲۰۲۶)"


async def id_command_handler(client, message):
    raw = (message.text or "").strip().lower()
    if not re.match(r"^\.(?:id|ایدی)$", raw):
        return

    target_user = None
    target_chat = None

    if message.reply_to_message:
        if message.reply_to_message.from_user:
            target_user = message.reply_to_message.from_user
        elif message.reply_to_message.sender_chat:
            target_chat = message.reply_to_message.sender_chat
    else:
        target_user = await client.get_me()

    if target_user:
        full_name = " ".join(p for p in [target_user.first_name, target_user.last_name] if p).strip() or "بدون نام"
        username = f"@{target_user.username}" if target_user.username else "ندارد"
        est_date = estimate_account_creation(target_user.id)
        text = (
            f"<b>🪪 اطلاعات کاربری</b>\n"
            f"{UI_DIVIDER}\n"
            f"• <b>نام:</b> {html.escape(full_name)}\n"
            f"• <b>شناسه عددی:</b> <code>{target_user.id}</code>\n"
            f"• <b>نام کاربری:</b> {html.escape(username)}\n"
            f"• <b>زمان ساخت اکانت:</b> {html.escape(est_date)}"
        )
        await message.edit_text(text, parse_mode=ParseMode.HTML)
        return

    if target_chat:
        title = getattr(target_chat, "title", None) or "کانال/ناشناس"
        username = f"@{target_chat.username}" if getattr(target_chat, "username", None) else "ندارد"
        text = (
            f"<b>🪪 اطلاعات فرستنده (کانال/ناشناس)</b>\n"
            f"{UI_DIVIDER}\n"
            f"• <b>عنوان:</b> {html.escape(title)}\n"
            f"• <b>شناسه عددی:</b> <code>{target_chat.id}</code>\n"
            f"• <b>نام کاربری:</b> {html.escape(username)}"
        )
        await message.edit_text(text, parse_mode=ParseMode.HTML)
        return

    await message.edit_text("❌ اطلاعات فرستنده در دسترس نیست.")
