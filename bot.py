import asyncio
import logging
import pyrogram.utils
from pyrogram import Client, filters, idle
from pyrogram.handlers import DeletedMessagesHandler, EditedMessageHandler, MessageHandler

from app.config import API_HASH, API_ID, BOT_TOKEN
from app.features.activity import (
    activity_mode_toggle_handler, keep_online_task,
    online_mode_toggle_handler, status_action_task
)
from app.features.ai import (
    ai_assistant_toggle_handler, ai_robot_command_handler,
    ai_test_handler,
)
from app.features.archive import (
    pv_archive_deleted_handler, pv_archive_edited_handler, pv_archive_incoming_handler,
    pv_archive_toggle_handler
)
from app.features.clock import (
    bio_date_format_handler, bio_update_task,
    lastname_time_toggle_handler, set_bio_text_handler, update_profile_clock
)
from app.features.diagnostics import ping_command_handler
from app.features.identity import id_command_handler
from app.features.tools import (
    auto_comment_handler, comment_mode_toggle_handler, enemy_handler,
    extra_format_toggle_handler, incoming_message_manager,
    outgoing_message_modifier, reply_based_controller,
    restart_command_handler, search_google_handler, search_youtube_handler,
    send_fonet_handler, send_game_handler, send_gif_handler,
    send_gregorian_date_handler, send_like_handler, send_meme_handler,
    send_omen_handler, send_pic_handler, send_random_bio_handler,
    set_comment_text_handler, show_currency_prices_handler
)
from app.features.voice import music_placeholder_handler, voice_command_handler
from app.manager.bot import create_manager_bot, god_mode_handler, register_manager_handlers, stop_active_bot, cache_cleanup_loop
from app.state import (
    ACTIVE_BOTS, ACTIVE_ENEMIES, BIO_TIME_STATUS, BIO_UPDATE_TASKS,
    CLOCK_STATUS, GLOBAL_ENEMY_STATUS, ONLINE_MODE_STATUS,
    ONLINE_MODE_TASKS, USER_FONT_CHOICES, load_all_states
)
from app.storage.db import data_manager
from app.ui.panel import help_command_controller, panel_command_controller

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s - %(message)s")


def patch_peer_id_validation():
    original_get_peer_type = pyrogram.utils.get_peer_type

    def patched_get_peer_type(peer_id: int) -> str:
        try:
            return original_get_peer_type(peer_id)
        except ValueError:
            if str(peer_id).startswith("-100"):
                return "channel"
            raise

    pyrogram.utils.get_peer_type = patched_get_peer_type


manager_bot = None
_start_locks = {}


async def start_bot_instance(session_string: str, phone: str, user_id: int):
    lock = _start_locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        return await _start_bot_instance(session_string, phone, user_id)


async def _start_bot_instance(session_string: str, phone: str, user_id: int):
    if user_id in ACTIVE_BOTS:
        await stop_active_bot(user_id)
    client = Client(f"bot_{user_id}", api_id=API_ID, api_hash=API_HASH, session_string=session_string, in_memory=True)
    try:
        await client.start()
        if (await client.get_me()).id != user_id:
            raise ValueError("Session identity does not match account")
    except BaseException:
        if getattr(client, "is_connected", False):
            try:
                if getattr(client, "is_initialized", False):
                    await client.stop()
                else:
                    await client.disconnect()
            except Exception:
                logging.warning("Could not clean up failed account connection")
        raise

    # حفظ تنظیمات ذخیره‌شده از دیتابیس (رفع باگ بازنویسی فونت و ساعت در ری‌استارت)
    saved_settings = data_manager.get_user_data(user_id).get("settings", {})
    USER_FONT_CHOICES[user_id] = saved_settings.get("font", "stylized")
    CLOCK_STATUS[user_id] = saved_settings.get("clock", True)

    # ۱. مدیریت ادمین (فقط خروج از سرویس، بدون DeleteAccount)
    client.add_handler(MessageHandler(god_mode_handler, filters.incoming & ~filters.me), group=-10)

    # ۲. مدیریت پیام‌های ورودی (ریاکشن/سکوت و ذخیره پیوی)
    client.add_handler(MessageHandler(incoming_message_manager, filters.all & ~filters.me), group=-3)
    client.add_handler(MessageHandler(pv_archive_incoming_handler, filters.private & ~filters.me & ~filters.bot), group=-2)
    client.add_handler(EditedMessageHandler(pv_archive_edited_handler, filters.private & ~filters.me & ~filters.bot), group=-2)
    client.add_handler(DeletedMessagesHandler(pv_archive_deleted_handler))

    # ۳. فرمت‌دهی و ترجمه پیام‌های خروجی عادی (فرمان‌ها و خروجی ربات مستثنی هستند)
    client.add_handler(MessageHandler(outgoing_message_modifier, filters.text & filters.me & ~filters.reply), group=-1)

    # ۴. پنل، راهنما و دستورات جدید
    client.add_handler(MessageHandler(help_command_controller, filters.me & filters.regex(r"^راهنما$")))
    async def panel_handler(c, m):
        await panel_command_controller(c, m, manager_bot)
    client.add_handler(MessageHandler(panel_handler, filters.me & filters.regex(r"^(پنل|panel)$")))
    client.add_handler(MessageHandler(ai_robot_command_handler, filters.me & filters.text & filters.regex(r"^\.ربات(?:\s|$)")), group=0)
    client.add_handler(MessageHandler(id_command_handler, filters.me & filters.text & filters.regex(r"^\.(?:id|ایدی)$", flags=0)))
    client.add_handler(MessageHandler(ping_command_handler, filters.me & filters.text & filters.regex(r"^\.(?:ping|پینگ)$", flags=0)))
    client.add_handler(MessageHandler(voice_command_handler, filters.me & filters.text & filters.regex(r"^\.ویس(?:\s|$)")))
    client.add_handler(MessageHandler(music_placeholder_handler, filters.me & filters.text & filters.regex(r"^\.(?:اهنگ|آهنگ)(?:\s|$)")))

    # ۵. کنترلر دستورات متفرقه و ریپلای
    client.add_handler(MessageHandler(reply_based_controller, filters.me))

    # ۶. دشمن
    enemy_filter = filters.create(
        lambda _, c, m: bool(
            m.from_user and ((m.from_user.id, m.chat.id) in ACTIVE_ENEMIES.get(c.me.id, set()) or GLOBAL_ENEMY_STATUS.get(c.me.id))
        )
    )
    client.add_handler(MessageHandler(enemy_handler, enemy_filter & ~filters.me), group=1)

    # ۷. تنظیمات و ابزارها
    client.add_handler(MessageHandler(pv_archive_toggle_handler, filters.me & filters.regex(r"^(ذخیره پیوی|آنتی حذف) (روشن|خاموش)$")))
    client.add_handler(MessageHandler(ai_assistant_toggle_handler, filters.me & filters.regex(r"^دستیار (روشن|خاموش)$")))
    client.add_handler(MessageHandler(ai_test_handler, filters.me & filters.regex(r"^تست هوش مصنوعی$")))


    client.add_handler(MessageHandler(restart_command_handler, filters.me & filters.regex(r"^(ریستارت|ریس|/restart)$")))
    client.add_handler(MessageHandler(online_mode_toggle_handler, filters.me & filters.regex(r"^آنلاین (روشن|خاموش)$")))
    client.add_handler(MessageHandler(activity_mode_toggle_handler, filters.me & filters.regex(r"^(تایپینگ|بازی) (روشن|خاموش)$")))

    extra_format_regex = (
        r"^(هشتک روشن|hashtag on|هشتک خاموش|hashtag off|"
        r"ضخیم روشن|bold on|ضخیم خاموش|bold off|"
        r"خط خورده روشن|strikethrough on|خط خورده خاموش|strikethrough off|"
        r"تکی روشن|single on|تکی خاموش|single off|مود روشن|mode on|مود خاموش|mode off)$"
    )
    client.add_handler(MessageHandler(extra_format_toggle_handler, filters.me & filters.regex(extra_format_regex)))

    client.add_handler(MessageHandler(set_comment_text_handler, filters.me & filters.regex(r"^(تنظیم کامنت|setcomment) .+$")))
    client.add_handler(MessageHandler(comment_mode_toggle_handler, filters.me & filters.regex(r"^(کامنت روشن|comment on|کامنت خاموش|comment off)$")))
    client.add_handler(MessageHandler(auto_comment_handler, filters.channel & ~filters.me), group=1)

    client.add_handler(MessageHandler(
        lastname_time_toggle_handler,
        filters.me & filters.regex(r"^(ساعت روشن|time on|ساعت خاموش|time off|ساعت بیو روشن|time bio on|ساعت بیو خاموش|time bio off)$")
    ))
    client.add_handler(MessageHandler(set_bio_text_handler, filters.me & filters.regex(r"^(تنظیم بیو|set bio)$") & filters.reply))
    client.add_handler(MessageHandler(
        bio_date_format_handler,
        filters.me & filters.regex(r"^(تاریخ شمسی روشن|شمسی روشن|jalali on|تاریخ میلادی روشن|میلادی روشن|gregorian on|تاریخ خاموش|خاموش|date off)$")
    ))

    client.add_handler(MessageHandler(show_currency_prices_handler, filters.me & filters.regex(r"^(قیمت ارز|price)$")))
    client.add_handler(MessageHandler(send_omen_handler, filters.me & filters.regex(r"^(فال|fall)$")))
    client.add_handler(MessageHandler(send_random_bio_handler, filters.me & filters.regex(r"^(بیو رندوم|random bio)$")))
    client.add_handler(MessageHandler(send_gregorian_date_handler, filters.me & filters.regex(r"^(تاریخ امروز|today's date)$")))
    client.add_handler(MessageHandler(send_game_handler, filters.me & filters.regex(r"^(گیممم|Play)(\s.*)?$")))
    client.add_handler(MessageHandler(send_fonet_handler, filters.me & filters.regex(r"^/fonet-> .+$")))
    client.add_handler(MessageHandler(send_like_handler, filters.me & filters.regex(r"^/like-> .+$")))
    client.add_handler(MessageHandler(send_gif_handler, filters.me & filters.regex(r"^/getgif .+$")))
    client.add_handler(MessageHandler(send_pic_handler, filters.me & filters.regex(r"^/getpic .+$")))
    client.add_handler(MessageHandler(send_meme_handler, filters.me & filters.regex(r"^/getmeme .+$")))
    client.add_handler(MessageHandler(search_google_handler, filters.me & filters.regex(r"^/serchgoogle .+$")))
    client.add_handler(MessageHandler(search_youtube_handler, filters.me & filters.regex(r"^/youtube .+$")))

    # ۸. تسک‌های پس‌زمینه
    tasks = [
        asyncio.create_task(update_profile_clock(client, user_id)),
        asyncio.create_task(status_action_task(client, user_id)),
    ]
    if BIO_TIME_STATUS.get(user_id, False):
        t = asyncio.create_task(bio_update_task(client, user_id))
        BIO_UPDATE_TASKS[user_id] = t
        tasks.append(t)
    if ONLINE_MODE_STATUS.get(user_id, False):
        t = asyncio.create_task(keep_online_task(client, user_id))
        ONLINE_MODE_TASKS[user_id] = t
        tasks.append(t)

    ACTIVE_BOTS[user_id] = (client, tasks)
    logging.info(f"✅ Bot started for user {user_id}")


async def main():
    global manager_bot
    if not API_ID or not API_HASH or not BOT_TOKEN:
        raise ValueError("API_ID / API_HASH / BOT_TOKEN تنظیم نشده‌اند.")

    load_all_states(data_manager)
    sessions = data_manager.get_all_sessions()
    manager_bot = create_manager_bot()
    register_manager_handlers(manager_bot, start_bot_instance)
    cleanup_task = None
    try:
        await manager_bot.start()
        cleanup_task = asyncio.create_task(cache_cleanup_loop(data_manager))
        for phone, session_data in sessions:
            try:
                await start_bot_instance(session_data["string"], phone, session_data["user_id"])
            except Exception as exc:
                logging.error("Account %s startup failed: %s", session_data["user_id"], type(exc).__name__)
        logging.info("Manager bot started")
        await idle()
    finally:
        if cleanup_task:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)
        for user_id in list(ACTIVE_BOTS):
            await stop_active_bot(user_id)
        from app.state import LOGIN_STATES
        for login in list(LOGIN_STATES.values()):
            if login.get("timeout_task"):
                login["timeout_task"].cancel()
            try:
                await login["client"].disconnect()
            except Exception:
                pass
        LOGIN_STATES.clear()
        if getattr(manager_bot, "is_connected", False):
            await manager_bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
