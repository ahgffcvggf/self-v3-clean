import html
import re
from pyrogram.enums import ParseMode
from app.config import UI_DIVIDER


def estimate_account_creation(user_id: int) -> str:
    """Telegram numeric IDs do not reliably encode account creation time."""
    return "نامشخص (از شناسه قابل تعیین نیست)"


async def id_command_handler(client, message):
    if not re.match(r"^\.(?:id|ایدی)$", (message.text or "").strip().lower()): return
    target_user = target_chat = None
    if message.reply_to_message:
        target_user = message.reply_to_message.from_user
        if not target_user: target_chat = message.reply_to_message.sender_chat
    else:
        target_user = await client.get_me()
    if target_user:
        full_name = " ".join(p for p in [target_user.first_name, target_user.last_name] if p).strip() or "بدون نام"
        username = f"@{target_user.username}" if target_user.username else "ندارد"
        text = (f"<b>🪪 اطلاعات کاربری</b>\n{UI_DIVIDER}\n• <b>نام:</b> {html.escape(full_name)}\n"
                f"• <b>شناسه عددی:</b> <code>{target_user.id}</code>\n• <b>نام کاربری:</b> {html.escape(username)}\n"
                f"• <b>زمان ساخت اکانت:</b> {estimate_account_creation(target_user.id)}")
        await message.edit_text(text, parse_mode=ParseMode.HTML); return
    if target_chat:
        title = getattr(target_chat, "title", None) or "کانال/ناشناس"
        username = f"@{target_chat.username}" if getattr(target_chat, "username", None) else "ندارد"
        await message.edit_text(f"<b>🪪 اطلاعات فرستنده (کانال/ناشناس)</b>\n{UI_DIVIDER}\n• <b>عنوان:</b> {html.escape(title)}\n• <b>شناسه عددی:</b> <code>{target_chat.id}</code>\n• <b>نام کاربری:</b> {html.escape(username)}", parse_mode=ParseMode.HTML); return
    await message.edit_text("❌ اطلاعات فرستنده در دسترس نیست.")
