import asyncio
import inspect
import re
from pyrogram.errors import ChatSendInlineForbidden
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent
)
from app.config import (
    AI_API_KEY, AI_API_URL, AI_MODEL, FONT_KEYS_ORDER, PANEL_PHOTO_PATH, UI_DIVIDER,
    panel_text, ui_err, ui_status, ui_toggle, ui_warn
)
from app.features.activity import keep_online_task
from app.features.clock import bio_update_task, perform_clock_update_now, restore_clock_lastname, stylize_time
from app.state import (
    ACTIVE_BOTS, AI_ASSISTANT_STATUS, ANTI_DELETE_STATUS,
    AUTO_TRANSLATE_TARGET, BIO_DATE_FORMAT, BIO_TIME_STATUS, BIO_UPDATE_TASKS,
    BOLD_MODE_STATUS, CHAR_MODE_STATUS, CLOCK_STATUS, COMMENT_MODE_STATUS,
    HASHTAG_MODE_STATUS, ONLINE_MODE_STATUS, ONLINE_MODE_TASKS,
    PLAYING_MODE_STATUS, SINGLE_MODE_STATUS, STRIKETHROUGH_MODE_STATUS,
    TTS_VOICE_GENDER, TYPING_MODE_STATUS, USER_FONT_CHOICES
)
from app.storage.db import data_manager

_SUPPORTS_INLINE_STYLE = "style" in inspect.signature(InlineKeyboardButton.__init__).parameters


def btn(text: str, callback_data: str, style: str = None) -> InlineKeyboardButton:
    """ساخت دکمه شیشه‌ای با پشتیبانی خودکار از دکمه‌های رنگی تلگرام (primary/success/danger)."""
    if style and _SUPPORTS_INLINE_STYLE:
        return InlineKeyboardButton(text, callback_data=callback_data, style=style)
    return InlineKeyboardButton(text, callback_data=callback_data)


def toggle_style(state: bool) -> str:
    return "success" if state else "danger"


HELP_SECTIONS = [
    (
        "هوش مصنوعی و ابزارهای جدید",
        "• `.ربات [سؤال]` — پاسخ هوش مصنوعی (فقط پیام‌های خودتان)\n"
        "• `.id` یا `.ایدی` — اطلاعات خودتان یا فرد ریپلای‌شده + تخمین زمان ساخت\n"
        "• `.ping` یا `.پینگ` — پینگ تلگرام و مشخصات CPU/RAM سرور\n"
        "• `.ویس [متن]` یا ریپلای `.ویس` — تبدیل متن به ویس فارسی\n"
        "• `.اهنگ [نام]` / `.آهنگ [نام]` — در دسترس نیست"
    ),
    (
        "ذخیره پیوی و حالت‌های خودکار",
        "• `ذخیره پیوی روشن/خاموش` — آرشیو پیام‌های حذف‌شده و مدیای تایم‌دار پیوی اشخاص\n"
        "• `تایپینگ روشن/خاموش` — نمایش وضعیت در حال تایپ\n"
        "• `بازی روشن/خاموش` — نمایش وضعیت در حال بازی\n"
        "• `آنلاین روشن/خاموش` — آنلاین نگه‌داشتن هوشمند اکانت\n"
        "• `دستیار روشن/خاموش` — فعال/غیرفعال کردن `.ربات`"
    ),
    (
        "ساعت، تاریخ و ظاهر پیام",
        "• `ساعت روشن/خاموش` — نمایش ساعت روی نام خانوادگی\n"
        "• `ساعت بیو روشن/خاموش` / `تنظیم بیو` (ریپلای)\n"
        "• `شمسی روشن` / `میلادی روشن` / `تاریخ خاموش`\n"
        "• `ضخیم` / `هشتک` / `خط خورده` / `تکی` / `مود` (`روشن`/`خاموش`)"
    ),
    (
        "مدیریت چت و ابزارهای دیگر",
        "• `حذف [تعداد]` / `ذخیره` (ریپلای) / `تکرار [تعداد]` (ریپلای)\n"
        "• `دشمن` / `بلاک` / `سکوت` / `ریاکشن [شکلک]` (ریپلای)\n"
        "• `تاس` / `بولینگ` / `قیمت ارز` / `فال` / `تاریخ امروز` / `رم`\n"
        "• `پنل` — باز کردن پنل شیشه‌ای تنظیمات"
    ),
]

CATEGORY_META = {
    "main": ("پنل مدیریت سلف‌تلتون", "یک بخش را برای تنظیم انتخاب کنید."),
    "time": ("ساعت و تاریخ", "تنظیم ساعت نام، بیو، فونت و تاریخ."),
    "auto": ("حالت‌های خودکار", "تایپینگ، بازی، آنلاین و کامنت خودکار."),
    "archive": ("ذخیره پیوی (آنتی‌حذف + تایم‌دار)", "آرشیو پیام‌های حذف‌شده و عکس/فیلم تایم‌دار در پیوی اشخاص."),
    "ai": ("دستیار هوش مصنوعی (.ربات)", "پاسخ‌گویی فقط به پیام‌های خودتان با پیشوند .ربات"),
    "lang": ("ترجمه خودکار", "ترجمه خودکار پیام‌های ارسالی عادی (فرمان‌ها ترجمه نمی‌شوند)."),
    "voice": ("صدا", "تنظیم صدای ویس فارسی (.ویس)."),
    "format": ("ظاهر پیام‌ها و ابزارها", "استایل پیام‌های ارسالی و راهنمای .id / .ping."),
    "account": ("وضعیت حساب و سرویس", "خلاصه وضعیت اتصال و تنظیمات فعال."),
}


def generate_main_menu(user_id: int) -> InlineKeyboardMarkup:
    n_time = sum(1 for d in [CLOCK_STATUS, BIO_TIME_STATUS] if d.get(user_id, False))
    n_auto = sum(1 for d in [TYPING_MODE_STATUS, PLAYING_MODE_STATUS, ONLINE_MODE_STATUS, COMMENT_MODE_STATUS] if d.get(user_id, False))
    n_arch = 1 if ANTI_DELETE_STATUS.get(user_id, False) else 0
    n_ai = 1 if AI_ASSISTANT_STATUS.get(user_id, False) else 0
    n_lang = 1 if AUTO_TRANSLATE_TARGET.get(user_id) else 0

    def lbl(base, count):
        return f"{base} ({count})" if count else base

    return InlineKeyboardMarkup([
        [btn(lbl("⏰ ساعت و تاریخ", n_time), f"cat_time_{user_id}", "primary"),
         btn(lbl("⚙️ حالت‌های خودکار", n_auto), f"cat_auto_{user_id}", "primary")],
        [btn(lbl("💾 ذخیره پیوی", n_arch), f"cat_archive_{user_id}", toggle_style(bool(n_arch))),
         btn(lbl("🤖 دستیار AI", n_ai), f"cat_ai_{user_id}", toggle_style(bool(n_ai)))],
        [btn(lbl("🌐 ترجمه خودکار", n_lang), f"cat_lang_{user_id}", toggle_style(bool(n_lang))),
         btn("🎵 موسیقی و صدا", f"cat_voice_{user_id}", "primary")],
        [btn("🎨 ظاهر و ابزارها", f"cat_format_{user_id}"),
         btn("📊 وضعیت حساب", f"cat_account_{user_id}")],
        [btn("📖 راهنما", f"help_0_{user_id}", "primary"),
         btn("✕ بستن پنل", f"close_panel_{user_id}", "danger")],
    ])


def generate_category_menu(user_id: int, category: str) -> InlineKeyboardMarkup:
    back_btn = btn("‹ بازگشت", f"back_main_{user_id}", "primary")

    if category == "time":
        c_on = CLOCK_STATUS.get(user_id, True)
        b_on = BIO_TIME_STATUS.get(user_id, False)
        fmt = BIO_DATE_FORMAT.get(user_id)
        fmt_label = {"jalali": "شمسی", "gregorian": "میلادی", None: "خاموش"}.get(fmt, "خاموش")
        preview = stylize_time("12:34", USER_FONT_CHOICES.get(user_id, "stylized"))
        return InlineKeyboardMarkup([
            [btn(f"ساعت نام {ui_status(c_on)}", f"toggle_clock_{user_id}", toggle_style(c_on)),
             btn(f"ساعت بیو {ui_status(b_on)}", f"toggle_biotime_{user_id}", toggle_style(b_on))],
            [btn(f"فونت ساعت: {preview}", f"cycle_font_{user_id}", "primary")],
            [btn(f"تاریخ بیو: {fmt_label}", f"cycle_dateformat_{user_id}")],
            [back_btn],
        ])

    if category == "auto":
        t_on = TYPING_MODE_STATUS.get(user_id, False)
        g_on = PLAYING_MODE_STATUS.get(user_id, False)
        o_on = ONLINE_MODE_STATUS.get(user_id, False)
        cm_on = COMMENT_MODE_STATUS.get(user_id, False)
        return InlineKeyboardMarkup([
            [btn(f"تایپینگ {ui_status(t_on)}", f"toggle_type_{user_id}", toggle_style(t_on)),
             btn(f"حالت بازی {ui_status(g_on)}", f"toggle_game_{user_id}", toggle_style(g_on))],
            [btn(f"آنلاین {ui_status(o_on)}", f"toggle_online_{user_id}", toggle_style(o_on)),
             btn(f"کامنت خودکار {ui_status(cm_on)}", f"toggle_comment_{user_id}", toggle_style(cm_on))],
            [back_btn],
        ])

    if category == "archive":
        a_on = ANTI_DELETE_STATUS.get(user_id, False)
        return InlineKeyboardMarkup([
            [btn(f"ذخیره پیوی {ui_status(a_on)}", f"toggle_antidel_{user_id}", toggle_style(a_on))],
            [btn("🗑 پاک‌کردن کش موقت", f"confirm_clearcache_{user_id}", "danger")],
            [back_btn],
        ])

    if category == "ai":
        ai_on = AI_ASSISTANT_STATUS.get(user_id, False)
        return InlineKeyboardMarkup([
            [btn(f"دستیار (.ربات) {ui_status(ai_on)}", f"toggle_ai_{user_id}", toggle_style(ai_on))],
            [btn("🧹 پاک‌کردن حافظه چت", f"confirm_clearai_{user_id}", "danger")],
            [back_btn],
        ])

    if category == "lang":
        cur = AUTO_TRANSLATE_TARGET.get(user_id)
        return InlineKeyboardMarkup([
            [btn(f"انگلیسی {ui_status(cur == 'en')}", f"lang_en_{user_id}", toggle_style(cur == "en")),
             btn(f"روسی {ui_status(cur == 'ru')}", f"lang_ru_{user_id}", toggle_style(cur == "ru")),
             btn(f"چینی {ui_status(cur == 'zh-CN')}", f"lang_cn_{user_id}", toggle_style(cur == "zh-CN"))],
            [back_btn],
        ])

    if category == "voice":
        gender = TTS_VOICE_GENDER.get(user_id, "female")
        return InlineKeyboardMarkup([
            [btn(f"صدای زن (دلارا) {ui_status(gender == 'female')}", f"voice_female_{user_id}", toggle_style(gender == "female")),
             btn(f"صدای مرد (فرید) {ui_status(gender == 'male')}", f"voice_male_{user_id}", toggle_style(gender == "male"))],
            [back_btn],
        ])

    if category == "format":
        b = BOLD_MODE_STATUS.get(user_id, False)
        h = HASHTAG_MODE_STATUS.get(user_id, False)
        s = STRIKETHROUGH_MODE_STATUS.get(user_id, False)
        sg = SINGLE_MODE_STATUS.get(user_id, False)
        ch = CHAR_MODE_STATUS.get(user_id, False)
        return InlineKeyboardMarkup([
            [btn(f"بولد {ui_status(b)}", f"toggle_bold_{user_id}", toggle_style(b)),
             btn(f"هشتک {ui_status(h)}", f"toggle_hashtag_{user_id}", toggle_style(h))],
            [btn(f"خط‌خورده {ui_status(s)}", f"toggle_strike_{user_id}", toggle_style(s)),
             btn(f"تکی {ui_status(sg)}", f"toggle_single_{user_id}", toggle_style(sg))],
            [btn(f"مود {ui_status(ch)}", f"toggle_charmode_{user_id}", toggle_style(ch))],
            [back_btn],
        ])

    return InlineKeyboardMarkup([[back_btn]])


def generate_panel_view(user_id: int, category: str):
    title, subtitle = CATEGORY_META.get(category, CATEGORY_META["main"])
    lines = []
    if category == "main":
        name = data_manager.get_user_data(user_id).get("first_name") or "کاربر"
        lines = [f"حساب: `{name}` (`{user_id}`)", "وضعیت اتصال: برقرار"]
    elif category == "archive":
        cnt, total_bytes = data_manager.get_cache_stats(user_id)
        mb = total_bytes / (1024 * 1024)
        lines = [
            "پوشش: فقط پیوی اشخاص (بدون گروه، کانال، ربات و پیام خودتان)",
            "• پیام عادی فقط پس از حذف آرشیو می‌شود.",
            "• عکس و فیلم تایم‌دار بلافاصله آرشیو می‌شود.",
            f"کش فعلی: `{cnt}` مورد (`{mb:.2f} MB` / سقف 1 GB)",
        ]
    elif category == "ai":
        configured = bool(AI_API_KEY and AI_API_URL and AI_MODEL)
        cfg = "پیکربندی‌شده" if configured else "تنظیم‌نشده"
        lines = [f"پیکربندی API: {cfg}", "وضعیت اجرا: فقط هنگام پاسخ‌گویی زنده مشخص می‌شود.", "فرمان فعال: `.ربات <سؤال>` (فقط پیام خودتان)"]
    elif category == "voice":
        gender_lbl = "زن (دلارا)" if TTS_VOICE_GENDER.get(user_id, "female") == "female" else "مرد (فرید)"
        lines = [f"صدای فعلی `.ویس`: {gender_lbl}", "فرمان آهنگ در دسترس نیست."]
    elif category == "format":
        lines = ["دستورات اطلاعاتی: `.id` / `.ایدی` و `.ping` / `.پینگ`"]
    elif category == "account":
        ud = data_manager.get_user_data(user_id)
        lines = [
            f"نام: `{ud.get('first_name') or '-'}`",
            f"شناسه: `{user_id}`",
            f"سلف فعال: {'بله' if user_id in ACTIVE_BOTS else 'خیر'}",
        ]

    return panel_text(title, subtitle, lines), generate_category_menu(user_id, category) if category != "main" else generate_main_menu(user_id)


def build_help_view(page_idx: int, user_id: int):
    page_idx = max(0, min(page_idx, len(HELP_SECTIONS) - 1))
    sec_title, sec_body = HELP_SECTIONS[page_idx]
    text = f"**📖 راهنمای دستورات ({page_idx + 1}/{len(HELP_SECTIONS)})**\n{UI_DIVIDER}\n**• {sec_title}**\n{sec_body}"
    nav = []
    if page_idx > 0:
        nav.append(btn("‹ قبلی", f"help_{page_idx - 1}_{user_id}", "primary"))
    if page_idx < len(HELP_SECTIONS) - 1:
        nav.append(btn("بعدی ›", f"help_{page_idx + 1}_{user_id}", "primary"))
    rows = [nav] if nav else []
    rows.append([btn("‹ بازگشت به پنل", f"back_main_{user_id}", "primary")])
    return text, InlineKeyboardMarkup(rows)


async def panel_command_controller(client, message, manager_bot):
    bot_username = "None"
    try:
        bot_info = await manager_bot.get_me()
        bot_username = bot_info.username
        results = await client.get_inline_bot_results(bot_username, "panel")
        if results and results.results:
            await message.delete()
            await client.send_inline_bot_result(message.chat.id, results.query_id, results.results[0].id)
        else:
            await message.edit_text(ui_err("حالت Inline ربات مدیر فعال نیست."))
    except ChatSendInlineForbidden:
        await message.edit_text(ui_warn("در این چت امکان ارسال پنل اینلاین نیست؛ در Saved Messages امتحان کنید."))
    except Exception as e:
        await message.edit_text(ui_err(f"خطا در باز کردن پنل (@{bot_username}): {e}"))


async def help_command_controller(client, message):
    text, _ = build_help_view(0, client.me.id)
    await message.edit_text(text)


def register_manager_panel_handlers(manager_bot):
    @manager_bot.on_inline_query()
    async def inline_panel_handler(client, query):
        user_id = query.from_user.id
        if query.query == "panel":
            text, markup = generate_panel_view(user_id, "main")
            result = InlineQueryResultArticle(
                title="پنل مدیریت سلف‌تلتون",
                input_message_content=InputTextMessageContent(text),
                reply_markup=markup,
            )
            await query.answer([result], cache_time=0)

    @manager_bot.on_callback_query()
    async def callback_panel_handler(client, callback):
        parts = callback.data.split("_")
        if len(parts) < 2 or not parts[-1].isdigit():
            await callback.answer("دکمه قدیمی است؛ دستور پنل را دوباره بزنید.", show_alert=True)
            return

        action = "_".join(parts[:-1])
        target_user_id = int(parts[-1])

        if callback.from_user.id != target_user_id:
            await callback.answer("⛔️ دسترسی غیرمجاز!", show_alert=True)
            return

        if action == "noop":
            await callback.answer("این بخش در نسخه بعدی اضافه می‌شود.", show_alert=False)
            return

        if action == "close_panel":
            try:
                if callback.inline_message_id:
                    await client.edit_inline_text(callback.inline_message_id, "پنل بسته شد.")
                else:
                    await callback.message.delete()
            except Exception:
                pass
            await callback.answer()
            return

        if action == "back_main":
            text, markup = generate_panel_view(target_user_id, "main")
            await callback.edit_message_text(text, reply_markup=markup)
            await callback.answer()
            return

        if action.startswith("cat_"):
            text, markup = generate_panel_view(target_user_id, action[4:])
            await callback.edit_message_text(text, reply_markup=markup)
            await callback.answer()
            return

        if action.startswith("help_"):
            idx = int(action.split("_")[1])
            text, markup = build_help_view(idx, target_user_id)
            await callback.edit_message_text(text, reply_markup=markup)
            await callback.answer()
            return

        if action == "confirm_clearcache":
            kb = InlineKeyboardMarkup([
                [btn("✅ بله، پاک کن", f"do_clearcache_{target_user_id}", "danger"),
                 btn("✖️ انصراف", f"cat_archive_{target_user_id}", "primary")]
            ])
            await callback.edit_message_text(ui_warn("کش موقت مدیاهای پیوی پاک شود؟ (پیام‌های Saved Messages دست نمی‌خورند)"), reply_markup=kb)
            await callback.answer()
            return

        if action == "do_clearcache":
            data_manager.clear_account_cache(target_user_id)
            text, markup = generate_panel_view(target_user_id, "archive")
            await callback.edit_message_text(text, reply_markup=markup)
            await callback.answer("کش موقت پاک شد.", show_alert=True)
            return

        if action == "confirm_clearai":
            kb = InlineKeyboardMarkup([
                [btn("✅ بله، پاک کن", f"do_clearai_{target_user_id}", "danger"),
                 btn("✖️ انصراف", f"cat_ai_{target_user_id}", "primary")]
            ])
            await callback.edit_message_text(ui_warn("حافظه چت دستیار AI برای این حساب پاک شود؟"), reply_markup=kb)
            await callback.answer()
            return

        if action == "do_clearai":
            data_manager.clear_chat_history(target_user_id)
            text, markup = generate_panel_view(target_user_id, "ai")
            await callback.edit_message_text(text, reply_markup=markup)
            await callback.answer("حافظه AI پاک شد.", show_alert=True)
            return

        settings_update = {}
        category = "main"
        feedback = None

        if action == "toggle_clock":
            val = not CLOCK_STATUS.get(target_user_id, True)
            CLOCK_STATUS[target_user_id] = val
            settings_update["clock"] = val
            category = "time"
            feedback = ui_toggle("ساعت روی نام", val)
            if target_user_id in ACTIVE_BOTS:
                bot_c = ACTIVE_BOTS[target_user_id][0]
                if val:
                    await perform_clock_update_now(bot_c, target_user_id)
                else:
                    await restore_clock_lastname(bot_c, target_user_id)
        elif action == "cycle_font":
            cur = USER_FONT_CHOICES.get(target_user_id, "stylized")
            if cur not in FONT_KEYS_ORDER:
                cur = FONT_KEYS_ORDER[0]
            new_font = FONT_KEYS_ORDER[(FONT_KEYS_ORDER.index(cur) + 1) % len(FONT_KEYS_ORDER)]
            USER_FONT_CHOICES[target_user_id] = new_font
            CLOCK_STATUS[target_user_id] = True
            settings_update.update({"font": new_font, "clock": True})
            category = "time"
            if target_user_id in ACTIVE_BOTS:
                await perform_clock_update_now(ACTIVE_BOTS[target_user_id][0], target_user_id)
        elif action == "toggle_biotime":
            val = not BIO_TIME_STATUS.get(target_user_id, False)
            BIO_TIME_STATUS[target_user_id] = val
            settings_update["bio_time"] = val
            category = "time"
            feedback = ui_toggle("ساعت بیو", val)
            if target_user_id in ACTIVE_BOTS:
                bot_c = ACTIVE_BOTS[target_user_id][0]
                if val and (target_user_id not in BIO_UPDATE_TASKS or BIO_UPDATE_TASKS[target_user_id].done()):
                    BIO_UPDATE_TASKS[target_user_id] = asyncio.create_task(bio_update_task(bot_c, target_user_id))
                elif not val and target_user_id in BIO_UPDATE_TASKS:
                    BIO_UPDATE_TASKS.pop(target_user_id).cancel()
        elif action == "cycle_dateformat":
            order = ["jalali", "gregorian", None]
            cur = BIO_DATE_FORMAT.get(target_user_id)
            if cur not in order:
                cur = None
            new_fmt = order[(order.index(cur) + 1) % 3]
            BIO_DATE_FORMAT[target_user_id] = new_fmt
            settings_update["bio_date_format"] = new_fmt
            category = "time"
        elif action == "toggle_antidel":
            val = not ANTI_DELETE_STATUS.get(target_user_id, False)
            ANTI_DELETE_STATUS[target_user_id] = val
            settings_update["anti_delete"] = val
            category = "archive"
            feedback = ui_toggle("ذخیره پیوی", val)
        elif action == "toggle_ai":
            val = not AI_ASSISTANT_STATUS.get(target_user_id, False)
            AI_ASSISTANT_STATUS[target_user_id] = val
            settings_update["ai_assistant"] = val
            category = "ai"
            feedback = ui_toggle("دستیار AI", val)
        elif action == "toggle_type":
            val = not TYPING_MODE_STATUS.get(target_user_id, False)
            TYPING_MODE_STATUS[target_user_id] = val
            if val:
                PLAYING_MODE_STATUS[target_user_id] = False
                settings_update["playing"] = False
            settings_update["typing"] = val
            category = "auto"
            feedback = ui_toggle("تایپینگ", val)
        elif action == "toggle_game":
            val = not PLAYING_MODE_STATUS.get(target_user_id, False)
            PLAYING_MODE_STATUS[target_user_id] = val
            if val:
                TYPING_MODE_STATUS[target_user_id] = False
                settings_update["typing"] = False
            settings_update["playing"] = val
            category = "auto"
            feedback = ui_toggle("حالت بازی", val)
        elif action == "toggle_online":
            val = not ONLINE_MODE_STATUS.get(target_user_id, False)
            ONLINE_MODE_STATUS[target_user_id] = val
            settings_update["online_mode"] = val
            category = "auto"
            feedback = ui_toggle("حالت آنلاین", val)
            if target_user_id in ACTIVE_BOTS:
                bot_c = ACTIVE_BOTS[target_user_id][0]
                if val and (target_user_id not in ONLINE_MODE_TASKS or ONLINE_MODE_TASKS[target_user_id].done()):
                    ONLINE_MODE_TASKS[target_user_id] = asyncio.create_task(keep_online_task(bot_c, target_user_id))
                elif not val and target_user_id in ONLINE_MODE_TASKS:
                    ONLINE_MODE_TASKS.pop(target_user_id).cancel()
        elif action == "toggle_comment":
            val = not COMMENT_MODE_STATUS.get(target_user_id, False)
            COMMENT_MODE_STATUS[target_user_id] = val
            settings_update["comment_mode"] = val
            category = "auto"
            feedback = ui_toggle("کامنت خودکار", val)
        elif action.startswith("lang_"):
            lang_map = {"en": "en", "ru": "ru", "cn": "zh-CN"}
            actual = lang_map.get(action.split("_")[1])
            new_lang = actual if AUTO_TRANSLATE_TARGET.get(target_user_id) != actual else None
            AUTO_TRANSLATE_TARGET[target_user_id] = new_lang
            settings_update["translate"] = new_lang
            category = "lang"
        elif action in ("voice_female", "voice_male"):
            gender = "female" if action == "voice_female" else "male"
            TTS_VOICE_GENDER[target_user_id] = gender
            settings_update["tts_voice"] = gender
            category = "voice"
            feedback = "صدای زن انتخاب شد" if gender == "female" else "صدای مرد انتخاب شد"
        elif action in ("toggle_bold", "toggle_hashtag", "toggle_strike", "toggle_single", "toggle_charmode"):
            map_fmt = {
                "toggle_bold": ("bold", BOLD_MODE_STATUS, "بولد"),
                "toggle_hashtag": ("hashtag", HASHTAG_MODE_STATUS, "هشتک"),
                "toggle_strike": ("strikethrough", STRIKETHROUGH_MODE_STATUS, "خط‌خورده"),
                "toggle_single": ("single_mode", SINGLE_MODE_STATUS, "تکی"),
                "toggle_charmode": ("char_mode", CHAR_MODE_STATUS, "مود"),
            }
            k, st_dict, lbl = map_fmt[action]
            val = not st_dict.get(target_user_id, False)
            st_dict[target_user_id] = val
            settings_update[k] = val
            category = "format"
            feedback = ui_toggle(lbl, val)

        if settings_update:
            data_manager.update_user_data(target_user_id, {"settings": settings_update})

        try:
            text, markup = generate_panel_view(target_user_id, category)
            await callback.edit_message_text(text, reply_markup=markup)
        except Exception:
            pass
        await callback.answer(feedback or "")
