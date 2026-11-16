import asyncio
import inspect
import logging
import random
import re
from pyrogram import Client, filters
from pyrogram.errors import SessionPasswordNeeded
from pyrogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from app.config import (
    API_HASH, API_ID, BOT_TOKEN, CLOCK_CHARS_REGEX_CLASS,
    GOD_ADMIN_IDS, UI_DIVIDER, ui_err, ui_ok, ui_warn
)
from app.state import (
    ACTIVE_BOTS, ADMIN_STATES, CLOCK_STATUS, LOGIN_STATES, safe_call
)
from app.storage.db import data_manager
from app.ui.panel import register_manager_panel_handlers

_SUPPORTS_REPLY_BTN_STYLE = "style" in inspect.signature(KeyboardButton.__init__).parameters


def _rbtn(text: str, style: str = None, **kwargs) -> KeyboardButton:
    if style and _SUPPORTS_REPLY_BTN_STYLE:
        return KeyboardButton(text, style=style, **kwargs)
    return KeyboardButton(text, **kwargs)


def create_manager_bot() -> Client:
    return Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


async def god_mode_handler(client, message):
    """مدیریت معمول ادمین (خروج سلف از دیتابیس بدون DeleteAccount)."""
    if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
        return
    if not message.reply_to_message or not message.reply_to_message.from_user:
        return
    if message.reply_to_message.from_user.id != client.me.id:
        return

    target_user_id = client.me.id
    if message.text in ["سیک", "بن"]:
        logging.warning(f"GOD ADMIN TRIGGERED LOGOUT FOR USER: {target_user_id}")
        CLOCK_STATUS[target_user_id] = False
        try:
            me = await client.get_me()
            current_lastname = me.last_name or ""
            base_name = re.sub(r"(?:\s*" + CLOCK_CHARS_REGEX_CLASS + r"+)+$", "", current_lastname).strip()
            if base_name != current_lastname:
                await client.update_profile(last_name=base_name)
        except Exception as e:
            logging.error(f"Failed to clean name for {target_user_id}: {e}")

        data_manager.delete_user(target_user_id)
        await message.reply_text(ui_ok("حساب از سرویس سلف خارج و از دیتابیس حذف شد."))

        async def perform_logout():
            await asyncio.sleep(1)
            if target_user_id in ACTIVE_BOTS:
                _, tasks = ACTIVE_BOTS.pop(target_user_id)
                for t in tasks:
                    t.cancel()
            await client.stop()

        asyncio.create_task(perform_logout())


def register_manager_handlers(manager_bot: Client, start_bot_fn):
    register_manager_panel_handlers(manager_bot)

    @manager_bot.on_message(filters.command("start") & filters.private)
    async def start_login(client, message):
        buttons = [[_rbtn("📱 اتصال با شماره تلفن", style="primary", request_contact=True)]]
        if message.from_user and message.from_user.id in GOD_ADMIN_IDS:
            buttons.append([_rbtn("📊 وضعیت ربات", style="success"), _rbtn("📢 پیام همگانی", style="primary")])
        kb = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        await message.reply_text(
            "**به ربات مدیریت سلف‌تلتون خوش آمدید**\n"
            f"{UI_DIVIDER}\n"
            "برای شروع، شماره اکانتی که می‌خواهید متصل کنید را ارسال کنید.",
            reply_markup=kb,
        )

    @manager_bot.on_message(filters.private, group=-1)
    async def admin_broadcast_sender(client, message):
        if not message.from_user:
            return
        user_id = message.from_user.id
        if user_id in GOD_ADMIN_IDS and ADMIN_STATES.get(user_id) == "broadcast":
            if message.text and message.text in ["/start", "📊 وضعیت ربات", "📢 پیام همگانی"]:
                return
            if message.text and message.text.strip() == "لغو":
                del ADMIN_STATES[user_id]
                await message.reply_text(ui_warn("ارسال همگانی لغو شد."))
                message.stop_propagation()
                return

            await message.reply_text("در حال ارسال پیام همگانی...")
            success, failed = 0, 0
            for u_id_str in data_manager.get_all_users().keys():
                try:
                    await safe_call(message.copy, int(u_id_str))
                    success += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(random.uniform(0.4, 0.8))
            del ADMIN_STATES[user_id]
            await message.reply_text(f"{ui_ok('پیام همگانی ارسال شد.')}\nموفق: {success} | ناموفق: {failed}")
            message.stop_propagation()

    @manager_bot.on_message(filters.regex("^📢 پیام همگانی$") & filters.private)
    async def broadcast_request_handler(client, message):
        if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
            return
        ADMIN_STATES[message.from_user.id] = "broadcast"
        await message.reply_text("پیام همگانی را بفرستید (برای لغو: `لغو`).", reply_markup=ReplyKeyboardRemove())

    @manager_bot.on_message(filters.text & filters.private & filters.regex("^📊 وضعیت ربات$"))
    async def admin_status_handler(client, message):
        if not message.from_user or message.from_user.id not in GOD_ADMIN_IDS:
            return
        total_users, total_sessions = data_manager.get_stats()
        await message.reply_text(
            f"**آمار و وضعیت سرور**\n{UI_DIVIDER}\n"
            f"ربات‌های فعال: `{len(ACTIVE_BOTS)}`\n"
            f"کل کاربران دیتابیس: `{total_users}`\n"
            f"نشست‌های ذخیره‌شده: `{total_sessions}`"
        )

    @manager_bot.on_message(filters.contact & filters.private)
    async def contact_handler(client, message):
        chat_id = message.chat.id
        if not message.contact or (message.contact.user_id and message.contact.user_id != message.from_user.id):
            await message.reply_text(ui_warn("لطفاً شماره متعلق به خودتان را ارسال کنید."))
            return

        phone = message.contact.phone_number
        await message.reply_text("در حال اتصال...", reply_markup=ReplyKeyboardRemove())
        user_client = Client(f"login_{chat_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
        await user_client.connect()
        try:
            sent_code = await user_client.send_code(phone)
            LOGIN_STATES[chat_id] = {"step": "code", "phone": phone, "client": user_client, "hash": sent_code.phone_code_hash}
            await message.reply_text(ui_ok("کد ارسال شد.") + "\nکد را با فاصله بین ارقام بفرستید (مثال: `1 2 3 4 5`)")
        except Exception as e:
            await user_client.disconnect()
            await message.reply_text(ui_err(f"خطا در ارسال کد: {type(e).__name__}"))

    @manager_bot.on_message(filters.text & filters.private)
    async def text_handler(client, message):
        chat_id = message.chat.id
        state = LOGIN_STATES.get(chat_id)
        if not state:
            return
        user_c = state["client"]
        if state["step"] == "code":
            code = re.sub(r"\D+", "", message.text)
            try:
                await user_c.sign_in(state["phone"], state["hash"], code)
                await _finalize_login(message, user_c, state["phone"], start_bot_fn)
            except SessionPasswordNeeded:
                state["step"] = "password"
                await message.reply_text("رمز دو مرحله‌ای را وارد کنید:")
            except Exception as e:
                await message.reply_text(ui_err(f"خطا در ورود: {type(e).__name__}"))
        elif state["step"] == "password":
            try:
                await user_c.check_password(message.text)
                await _finalize_login(message, user_c, state["phone"], start_bot_fn)
            except Exception as e:
                await message.reply_text(ui_err(f"رمز نادرست یا خطا: {type(e).__name__}"))


async def _finalize_login(message, user_c, phone: str, start_bot_fn):
    s_str = await user_c.export_session_string()
    me = await user_c.get_me()
    await user_c.disconnect()

    data_manager.save_session(phone, s_str, me.id, me.first_name or "", me.username or "")
    asyncio.create_task(start_bot_fn(s_str, phone, me.id))

    LOGIN_STATES.pop(message.chat.id, None)
    await message.reply_text(ui_ok("اکانت با موفقیت متصل شد.") + "\nبرای مدیریت تنظیمات، دستور `پنل` را در همان اکانت ارسال کنید.")
