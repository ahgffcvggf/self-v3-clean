import asyncio
import logging
import random
import re
from datetime import datetime
from persiantools.jdatetime import JalaliDate
from app.config import (
    CLOCK_CHARS_REGEX_CLASS, FONT_STYLES, TEHRAN_TIMEZONE, ui_ok, ui_toggle
)
from app.state import (
    ACTIVE_BOTS, BIO_CUSTOM_TEXT, BIO_DATE_FORMAT, BIO_TIME_STATUS,
    BIO_UPDATE_TASKS, CLOCK_STATUS, COPY_MODE_STATUS, USER_FONT_CHOICES
)
from app.storage.db import data_manager


def stylize_time(time_str: str, style: str) -> str:
    font_map = FONT_STYLES.get(style, FONT_STYLES["stylized"])
    return "".join(font_map.get(ch, ch) for ch in time_str)


async def perform_clock_update_now(client, user_id: int):
    try:
        if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
            style = USER_FONT_CHOICES.get(user_id, "stylized")
            me = await client.get_me()
            current_lastname = me.last_name or ""
            base_name = re.sub(r"(?:\s*" + CLOCK_CHARS_REGEX_CLASS + r"+)+$", "", current_lastname).strip()
            now_str = datetime.now(TEHRAN_TIMEZONE).strftime("%H:%M")
            new_lastname = f"{base_name} {stylize_time(now_str, style)}".strip()
            if new_lastname != current_lastname:
                await client.update_profile(last_name=new_lastname)
    except Exception as e:
        logging.error(f"Immediate clock update failed: {e}")


async def update_profile_clock(client, user_id: int):
    while user_id in ACTIVE_BOTS:
        try:
            if CLOCK_STATUS.get(user_id, True) and not COPY_MODE_STATUS.get(user_id, False):
                await perform_clock_update_now(client, user_id)
            now = datetime.now(TEHRAN_TIMEZONE)
            await asyncio.sleep(60 - now.second + 0.1)
        except Exception:
            await asyncio.sleep(60)


async def bio_update_task(client, user_id: int):
    while BIO_TIME_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS:
        try:
            style = USER_FONT_CHOICES.get(user_id, "stylized")
            now = datetime.now(TEHRAN_TIMEZONE)
            stylized = stylize_time(now.strftime("%H:%M"), style)
            date_fmt = BIO_DATE_FORMAT.get(user_id)
            if date_fmt == "jalali":
                current_date = JalaliDate.today().strftime("امروز (%d) %B ☀️ %Y")
            elif date_fmt == "gregorian":
                current_date = now.strftime("امروز (%d) %B ☀️ %Y")
            else:
                current_date = ""

            custom = BIO_CUSTOM_TEXT.get(user_id, "")
            if custom:
                emojis = random.choice(["⛅", "🌥️", "☀️", "💫", "🌙", "🌠", "🌎"])
                new_bio = f"{custom} | {stylized} | {current_date} {emojis}"
            else:
                new_bio = f"{current_date} {stylized}".strip()
            await client.update_profile(bio=new_bio[:70])
        except Exception:
            pass
        await asyncio.sleep(60)


async def lastname_time_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text

    if "بیو" in text or "bio" in text:
        is_on = ("روشن" in text) or ("on" in text and "off" not in text)
        BIO_TIME_STATUS[user_id] = is_on
        data_manager.update_user_data(user_id, {"settings": {"bio_time": is_on}})
        if is_on:
            t = BIO_UPDATE_TASKS.get(user_id)
            if not t or t.done():
                BIO_UPDATE_TASKS[user_id] = asyncio.create_task(bio_update_task(client, user_id))
        else:
            t = BIO_UPDATE_TASKS.pop(user_id, None)
            if t:
                t.cancel()
        await message.edit_text(ui_toggle("ساعت بیو", is_on))
    else:
        is_on = ("روشن" in text) or ("on" in text and "off" not in text)
        CLOCK_STATUS[user_id] = is_on
        data_manager.update_user_data(user_id, {"settings": {"clock": is_on}})
        if is_on:
            asyncio.create_task(perform_clock_update_now(client, user_id))
        else:
            try:
                me = await client.get_me()
                current_lastname = me.last_name or ""
                clean_name = re.sub(r"(?:\s*" + CLOCK_CHARS_REGEX_CLASS + r"+)+$", "", current_lastname).strip()
                await client.update_profile(last_name=clean_name)
            except Exception:
                pass
        await message.edit_text(ui_toggle("ساعت روی نام", is_on))


async def set_bio_text_handler(client, message):
    user_id = client.me.id
    if message.reply_to_message and message.reply_to_message.text:
        new_bio_text = message.reply_to_message.text
        BIO_CUSTOM_TEXT[user_id] = new_bio_text
        data_manager.update_user_data(user_id, {"settings": {"bio_text": new_bio_text}})
        await message.edit_text(ui_ok("بیو تنظیم شد:") + f"\n{new_bio_text}")


async def bio_date_format_handler(client, message):
    user_id = client.me.id
    text = message.text
    if text in ["تاریخ شمسی روشن", "شمسی روشن", "jalali on"]:
        BIO_DATE_FORMAT[user_id] = "jalali"
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": "jalali"}})
        await message.edit_text(ui_ok("فرمت تاریخ بیو روی شمسی تنظیم شد."))
    elif text in ["تاریخ میلادی روشن", "میلادی روشن", "gregorian on"]:
        BIO_DATE_FORMAT[user_id] = "gregorian"
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": "gregorian"}})
        await message.edit_text(ui_ok("فرمت تاریخ بیو روی میلادی تنظیم شد."))
    elif text in ["تاریخ خاموش", "خاموش", "date off"]:
        BIO_DATE_FORMAT[user_id] = None
        data_manager.update_user_data(user_id, {"settings": {"bio_date_format": None}})
        await message.edit_text(ui_toggle("تاریخ بیو", False))
