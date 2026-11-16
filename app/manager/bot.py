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
    ACTIVE_BOTS, ADMIN_STATES, BIO_UPDATE_TASKS, CLOCK_STATUS, LOGIN_STATES,
    clear_runtime_state, safe_call
)
from app.storage.db import data_manager
from app.ui.panel import register_manager_panel_handlers

try:
    from app.config import ALLOWED_USER_IDS
except ImportError:
    ALLOWED_USER_IDS = []

LOGIN_TIMEOUT = 300
MAX_LOGIN_ATTEMPTS = 3

_SUPPORTS_REPLY_BTN_STYLE = "style" in inspect.signature(KeyboardButton.__init__).parameters


def _rbtn(text: str, style: str = None, **kwargs) -> KeyboardButton:
    if style and _SUPPORTS_REPLY_BTN_STYLE:
        return KeyboardButton(text, style=style, **kwargs)
    return KeyboardButton(text, **kwargs)


def create_manager_bot() -> Client:
    return Client("manager_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


def is_onboarding_allowed(user_id: int) -> bool:
    """Fail closed: only explicitly configured operators may onboard."""
    return bool(GOD_ADMIN_IDS or ALLOWED_USER_IDS) and user_id in set(GOD_ADMIN_IDS) | set(ALLOWED_USER_IDS)


async def stop_active_bot(user_id: int):
    """Stop a user's client and every task owned by its runtime state."""
    entry = ACTIVE_BOTS.pop(user_id, None)
    tasks = list(entry[1]) if entry else []
    for mapping in (BIO_UPDATE_TASKS,):
        task = mapping.pop(user_id, None)
        if task is not None:
            tasks.append(task)
    try:
        from app.state import ONLINE_MODE_TASKS
        task = ONLINE_MODE_TASKS.pop(user_id, None)
        if task is not None:
            tasks.append(task)
    except ImportError:
        pass
    for task in set(tasks):
        if task and not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if entry:
        client = entry[0]
        try:
            await client.stop()
        except Exception:
            logging.exception("Failed stopping client for %s", user_id)


async def cache_cleanup_loop(dm=data_manager, interval=60):
    from app.features.archive import archive_maintenance
    while True:
        try:
            await archive_maintenance(dm)
        except Exception:
            logging.exception("Cache maintenance failed")
        await asyncio.sleep(interval)


async def _expire_login(chat_id):
    await asyncio.sleep(LOGIN_TIMEOUT)
    state = LOGIN_STATES.pop(chat_id, None)
    if state:
        try:
            await state["client"].disconnect()
        except Exception:
            pass


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
            await stop_active_bot(target_user_id)
            clear_runtime_state(target_user_id)
            if target_user_id not in ACTIVE_BOTS:
                try:
                    await client.stop()
                except Exception:
                    pass

        asyncio.create_task(perform_logout())


def register_manager_handlers(manager_bot: Client, start_bot_fn):
    register_manager_panel_handlers(manager_bot)

    @manager_bot.on_message(filters.command("start") & filters.private)
    async def start_login(client, message):
        if not message.from_user or not is_onboarding_allowed(message.from_user.id):
            return
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
        if (not message.from_user or not is_onboarding_allowed(message.from_user.id)
                or not message.contact
                or message.contact.user_id != message.from_user.id):
            await message.reply_text(ui_warn("لطفاً شماره متعلق به خودتان را ارسال کنید."))
            return

        phone = message.contact.phone_number
        await message.reply_text("در حال اتصال...", reply_markup=ReplyKeyboardRemove())
        user_client = Client(f"login_{chat_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True, no_updates=True)
        await user_client.connect()
        try:
            sent_code = await user_client.send_code(phone)
            old = LOGIN_STATES.pop(chat_id, None)
            if old:
                await old["client"].disconnect()
                old.get("timeout_task") and old["timeout_task"].cancel()
            timeout_task = asyncio.create_task(_expire_login(chat_id))
            LOGIN_STATES[chat_id] = {"step": "code", "phone": phone, "client": user_client,
                                     "hash": sent_code.phone_code_hash, "attempts": 0,
                                     "timeout_task": timeout_task}
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
        if (message.text or "").strip().lower() in {"لغو", "cancel"}:
            LOGIN_STATES.pop(chat_id, None)
            if state.get("timeout_task"):
                state["timeout_task"].cancel()
            await user_c.disconnect()
            await message.reply_text(ui_warn("ورود لغو شد."))
            return
        state["attempts"] = state.get("attempts", 0) + 1
        try:
            await message.delete()
        except Exception:
            pass
        if state["attempts"] > MAX_LOGIN_ATTEMPTS:
            LOGIN_STATES.pop(chat_id, None)
            await user_c.disconnect()
            await message.reply_text(ui_err("تعداد تلاش‌های ورود بیش از حد مجاز است."))
            return
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
    try:
        s_str = await user_c.export_session_string()
        me = await user_c.get_me()
        data_manager.save_session(phone, s_str, me.id, me.first_name or "", me.username or "")
        await user_c.disconnect()
        await start_bot_fn(s_str, phone, me.id)
    finally:
        state = LOGIN_STATES.pop(message.chat.id, None)
        if state and state.get("timeout_task"):
            state["timeout_task"].cancel()
        if getattr(user_c, "is_connected", False):
            try:
                await user_c.disconnect()
            except Exception:
                pass
    await message.reply_text(ui_ok("اکانت با موفقیت متصل شد.") + "\nبرای مدیریت تنظیمات، دستور `پنل` را در همان اکانت ارسال کنید.")
