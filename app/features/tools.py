import asyncio
import logging
import os
import random
import re
import sys
from datetime import datetime
from urllib.parse import quote
import aiohttp
from pyrogram import ContinuePropagation
from pyrogram.enums import ChatType
from pyrogram.raw import functions
from app.config import COMMAND_REGEX, UI_DIVIDER, ui_err, ui_ok, ui_toggle
from app.state import (
    ACTIVE_ENEMIES, AUTO_REACTION_TARGETS, AUTO_TRANSLATE_TARGET,
    BOLD_MODE_STATUS, CHAR_MODE_STATUS, CLOCK_STATUS, COMMENT_MODE_STATUS,
    COMMENT_TEXT, COPY_MODE_STATUS, ENEMY_REPLY_QUEUES, HASHTAG_MODE_STATUS,
    MUTED_USERS, ORIGINAL_PROFILE_DATA, SINGLE_MODE_STATUS,
    STRIKETHROUGH_MODE_STATUS, is_generated_message
)
from app.storage.db import data_manager

ENEMY_REPLIES = [
    "لطفاً احترام خودتون رو حفظ کنید.",
    "با این لحن صحبت نکنید.",
    "بهتره آروم‌تر باشید.",
]


async def translate_text(text: str, target_lang: str) -> str:
    if not text:
        return ""
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl={target_lang}&dt=t&q={quote(text)}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return "".join(part[0] for part in data[0] if part[0])
    except Exception:
        pass
    return text


async def outgoing_message_modifier(client, message):
    user_id = client.me.id
    if is_generated_message(user_id, message.chat.id, message.id):
        return
    if not message.text or re.match(COMMAND_REGEX, message.text.strip(), re.IGNORECASE):
        return

    original_text = message.text
    modified_text = original_text
    target_lang = AUTO_TRANSLATE_TARGET.get(user_id)
    if target_lang:
        modified_text = await translate_text(modified_text, target_lang)

    if CHAR_MODE_STATUS.get(user_id, False):
        edited = ""
        try:
            for ch in modified_text:
                edited += ch
                await message.edit_text(edited + "\u200C")
                await asyncio.sleep(0.5)
        except Exception:
            pass
        return

    if SINGLE_MODE_STATUS.get(user_id, False):
        try:
            await message.edit_text(f"`{modified_text}`")
        except Exception:
            pass
        return

    if HASHTAG_MODE_STATUS.get(user_id, False):
        modified_text = f"#{modified_text}"
    if STRIKETHROUGH_MODE_STATUS.get(user_id, False):
        modified_text = f"~~{modified_text}~~"
    if BOLD_MODE_STATUS.get(user_id, False):
        if not modified_text.startswith(("`", "**", "__", "~~", "||")):
            modified_text = f"**{modified_text}**"

    if modified_text != original_text:
        try:
            await message.edit_text(modified_text)
        except Exception:
            pass


async def extra_format_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text
    mapping = {
        "هشتک روشن": ("hashtag", HASHTAG_MODE_STATUS, True, "هشتک"),
        "hashtag on": ("hashtag", HASHTAG_MODE_STATUS, True, "هشتک"),
        "هشتک خاموش": ("hashtag", HASHTAG_MODE_STATUS, False, "هشتک"),
        "hashtag off": ("hashtag", HASHTAG_MODE_STATUS, False, "هشتک"),
        "ضخیم روشن": ("bold", BOLD_MODE_STATUS, True, "حالت ضخیم"),
        "bold on": ("bold", BOLD_MODE_STATUS, True, "حالت ضخیم"),
        "ضخیم خاموش": ("bold", BOLD_MODE_STATUS, False, "حالت ضخیم"),
        "bold off": ("bold", BOLD_MODE_STATUS, False, "حالت ضخیم"),
        "خط خورده روشن": ("strikethrough", STRIKETHROUGH_MODE_STATUS, True, "حالت خط‌خورده"),
        "strikethrough on": ("strikethrough", STRIKETHROUGH_MODE_STATUS, True, "حالت خط‌خورده"),
        "خط خورده خاموش": ("strikethrough", STRIKETHROUGH_MODE_STATUS, False, "حالت خط‌خورده"),
        "strikethrough off": ("strikethrough", STRIKETHROUGH_MODE_STATUS, False, "حالت خط‌خورده"),
        "تکی روشن": ("single_mode", SINGLE_MODE_STATUS, True, "حالت تکی"),
        "single on": ("single_mode", SINGLE_MODE_STATUS, True, "حالت تکی"),
        "تکی خاموش": ("single_mode", SINGLE_MODE_STATUS, False, "حالت تکی"),
        "single off": ("single_mode", SINGLE_MODE_STATUS, False, "حالت تکی"),
        "مود روشن": ("char_mode", CHAR_MODE_STATUS, True, "مود"),
        "mode on": ("char_mode", CHAR_MODE_STATUS, True, "مود"),
        "مود خاموش": ("char_mode", CHAR_MODE_STATUS, False, "مود"),
        "mode off": ("char_mode", CHAR_MODE_STATUS, False, "مود"),
    }
    if text in mapping:
        key, status_dict, val, label = mapping[text]
        status_dict[user_id] = val
        data_manager.update_user_data(user_id, {"settings": {key: val}})
        await message.edit_text(ui_toggle(label, val))


async def incoming_message_manager(client, message):
    if not message.from_user:
        return
    user_id = client.me.id
    reactions = AUTO_REACTION_TARGETS.get(user_id, {})
    if emoji := reactions.get(str(message.from_user.id)):
        try:
            await client.send_reaction(message.chat.id, message.id, emoji)
        except Exception:
            pass
    if (message.from_user.id, message.chat.id) in MUTED_USERS.get(user_id, set()):
        try:
            await message.delete()
        except Exception:
            pass


async def enemy_handler(client, message):
    user_id = client.me.id
    if user_id not in ENEMY_REPLY_QUEUES or not ENEMY_REPLY_QUEUES[user_id]:
        ENEMY_REPLY_QUEUES[user_id] = random.sample(ENEMY_REPLIES, len(ENEMY_REPLIES))
        data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])
    reply_text = ENEMY_REPLY_QUEUES[user_id].pop(0)
    data_manager.save_enemy_queue(user_id, ENEMY_REPLY_QUEUES[user_id])
    try:
        await message.reply_text(reply_text)
    except Exception:
        pass


async def reply_based_controller(client, message):
    user_id = client.me.id
    cmd = message.text
    if cmd is None:
        return

    if cmd == "تاس":
        await client.send_dice(message.chat.id, "🎲")
    elif cmd == "بولینگ":
        await client.send_dice(message.chat.id, "🎳")
    elif cmd.startswith("تاس "):
        try:
            await client.send_dice(message.chat.id, "🎲", reply_to_message_id=message.reply_to_message_id)
        except Exception:
            pass
    elif cmd == "لیست دشمن":
        await message.edit_text(f"تعداد دشمنان فعال: {len(ACTIVE_ENEMIES.get(user_id, set()))}")
    elif message.reply_to_message:
        target_id = message.reply_to_message.from_user.id if message.reply_to_message.from_user else None

        if cmd.startswith("حذف "):
            try:
                count = int(cmd.split()[1])
                msg_ids = [
                    m.id async for m in client.get_chat_history(message.chat.id, limit=count)
                    if m.from_user and m.from_user.is_self
                ]
                if msg_ids:
                    await client.delete_messages(message.chat.id, msg_ids)
                await message.delete()
            except Exception:
                pass
        elif cmd == "ذخیره":
            await message.reply_to_message.forward("me")
            await message.edit_text(ui_ok("پیام ذخیره شد."))
        elif cmd.startswith("تکرار "):
            try:
                count = int(cmd.split()[1])
                for _ in range(min(count, 20)):
                    await message.reply_to_message.copy(message.chat.id)
                await message.delete()
            except Exception:
                pass
        elif target_id:
            if cmd == "کپی روشن":
                user = await client.get_chat(target_id)
                me = await client.get_me()
                ORIGINAL_PROFILE_DATA[user_id] = {"first_name": me.first_name, "bio": me.bio}
                COPY_MODE_STATUS[user_id] = True
                CLOCK_STATUS[user_id] = False
                target_photos = [p async for p in client.get_chat_photos(target_id, limit=1)]
                await client.update_profile(first_name=user.first_name, bio=(user.bio or "")[:70])
                if target_photos:
                    await client.set_profile_photo(photo=target_photos[0].file_id)
                data_manager.save_original_profile(user_id, ORIGINAL_PROFILE_DATA[user_id])
                data_manager.update_user_data(user_id, {"settings": {"copy_mode": True, "clock": False}})
                await message.edit_text(ui_ok("هویت کاربر اعمال شد."))
            elif cmd == "کپی خاموش":
                if user_id in ORIGINAL_PROFILE_DATA:
                    data = ORIGINAL_PROFILE_DATA[user_id]
                    COPY_MODE_STATUS[user_id] = False
                    await client.update_profile(first_name=data.get("first_name"), bio=data.get("bio"))
                    data_manager.update_user_data(user_id, {"settings": {"copy_mode": False}})
                    await message.edit_text(ui_ok("هویت اصلی بازگردانده شد."))
            elif cmd == "دشمن روشن":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.add((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                data_manager.save_enemies(user_id, s)
                await message.edit_text(ui_ok("کاربر به لیست دشمنان اضافه شد."))
            elif cmd == "دشمن خاموش":
                s = ACTIVE_ENEMIES.get(user_id, set())
                s.discard((target_id, message.chat.id))
                ACTIVE_ENEMIES[user_id] = s
                data_manager.save_enemies(user_id, s)
                await message.edit_text(ui_ok("کاربر از لیست دشمنان حذف شد."))
            elif cmd == "بلاک روشن":
                await client.block_user(target_id)
                await message.edit_text(ui_ok("کاربر بلاک شد."))
            elif cmd == "بلاک خاموش":
                await client.unblock_user(target_id)
                await message.edit_text(ui_ok("کاربر آنبلاک شد."))
            elif cmd == "سکوت روشن":
                s = MUTED_USERS.get(user_id, set())
                s.add((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                data_manager.save_muted(user_id, s)
                await message.edit_text(ui_ok("کاربر ساکت شد."))
            elif cmd == "سکوت خاموش":
                s = MUTED_USERS.get(user_id, set())
                s.discard((target_id, message.chat.id))
                MUTED_USERS[user_id] = s
                data_manager.save_muted(user_id, s)
                await message.edit_text(ui_ok("کاربر از سکوت خارج شد."))
            elif cmd.startswith("ریاکشن ") and cmd != "ریاکشن خاموش":
                emoji = cmd.split()[1]
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t[str(target_id)] = emoji
                AUTO_REACTION_TARGETS[user_id] = t
                data_manager.save_reactions(user_id, t)
                await message.edit_text(ui_ok(f"واکنش خودکار {emoji} تنظیم شد."))
            elif cmd == "ریاکشن خاموش":
                t = AUTO_REACTION_TARGETS.get(user_id, {})
                t.pop(str(target_id), None)
                AUTO_REACTION_TARGETS[user_id] = t
                data_manager.save_reactions(user_id, t)
                await message.edit_text(ui_ok("واکنش خودکار حذف شد."))
    else:
        raise ContinuePropagation


async def set_comment_text_handler(client, message):
    user_id = client.me.id
    for prefix in ["تنظیم کامنت ", "setcomment "]:
        if message.text.startswith(prefix):
            new_text = message.text[len(prefix):]
            COMMENT_TEXT[user_id] = new_text
            data_manager.update_user_data(user_id, {"settings": {"comment_text": new_text}})
            await message.edit_text(ui_ok("متن کامنت تنظیم شد."))
            return


async def comment_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = message.text in ["کامنت روشن", "comment on"]
    COMMENT_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"comment_mode": is_on}})
    await message.edit_text(ui_toggle("کامنت‌گذاری خودکار", is_on))


async def auto_comment_handler(client, message):
    user_id = client.me.id
    if not COMMENT_MODE_STATUS.get(user_id, False) or message.chat.type != ChatType.CHANNEL:
        return
    try:
        peer = await client.resolve_peer(message.chat.id)
        result = await client.invoke(functions.messages.GetDiscussionMessage(peer=peer, msg_id=message.id))
        if result.messages:
            dm = result.messages[0]
            target = await client.get_chat(dm.peer_id.channel_id if hasattr(dm.peer_id, "channel_id") else dm.peer_id)
            await client.send_message(target.id, COMMENT_TEXT.get(user_id, "کامنت تنظیم نشده"), reply_to_message_id=dm.id)
    except Exception as e:
        logging.error(f"Comment-bot error: {e}")


async def restart_command_handler(client, message):
    await message.edit_text("🔄 در حال راه‌اندازی مجدد سلف...")
    os.execl(sys.executable, sys.executable, *sys.argv)


async def show_currency_prices_handler(client, message):
    await message.edit_text("در حال دریافت قیمت ارزها...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.codebazan.ir/arz/?type=arz", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = (await resp.json())["Result"]
        show_text = "".join(f"• {item['name']}: {item['price']}\n" for item in data[:25])
        await message.edit_text(f"**قیمت لحظه‌ای ارزها**\n{UI_DIVIDER}\n{show_text}")
    except Exception as e:
        await message.edit_text(ui_err(f"خطا در دریافت قیمت ارز: {e}"))


async def send_omen_handler(client, message):
    await message.edit_text("در حال گرفتن فال...")
    media_url = f"https://www.beytoote.com/images/Hafez/{random.randint(1, 149)}.gif"
    try:
        await client.send_animation(message.chat.id, media_url, caption="فال حافظ شما")
    except Exception:
        await message.edit_text(media_url)


async def send_random_bio_handler(client, message):
    await message.edit_text("در حال دریافت بیوگرافی...")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.codebazan.ir/bio/", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                await message.edit_text(await resp.text())
    except Exception as e:
        await message.edit_text(ui_err(f"خطا: {e}"))


async def send_gregorian_date_handler(client, message):
    now = datetime.utcnow()
    await message.edit_text(
        f"**تاریخ و ساعت امروز**\n{UI_DIVIDER}\n"
        f"روز: {now.strftime('%A')}\nتاریخ: {now.strftime('%Y/%m/%d')}\n"
        f"ماه: {now.strftime('%B')}\nساعت: {now.strftime('%H:%M:%S - %p')}"
    )


async def _send_inline_result(client, message, bot_username, query, not_found_text):
    try:
        results = await client.get_inline_bot_results(bot_username, query)
        if results and results.results:
            await client.send_inline_bot_result(message.chat.id, results.query_id, random.choice(results.results).id)
        else:
            await message.edit_text(not_found_text)
    except Exception as e:
        await message.edit_text(ui_err(f"خطا: {e}"))


async def send_game_handler(client, message):
    await _send_inline_result(client, message, "bodobazibot", message.text.split(" ", 1)[1] if " " in message.text else "", "بازی‌ای پیدا نشد.")

async def send_like_handler(client, message):
    await _send_inline_result(client, message, "like", message.text.split("/like-> ", 1)[1] if "/like-> " in message.text else "", "نتیجه‌ای پیدا نشد.")

async def send_gif_handler(client, message):
    await _send_inline_result(client, message, "gif", message.text.split("/getgif ", 1)[1] if "/getgif " in message.text else "", "گیفی پیدا نشد.")

async def send_pic_handler(client, message):
    await _send_inline_result(client, message, "pic", message.text.split("/getpic ", 1)[1] if "/getpic " in message.text else "", "تصویری پیدا نشد.")

async def send_meme_handler(client, message):
    await _send_inline_result(client, message, "Persian_Meme_Bot", message.text.split("/getmeme ", 1)[1] if "/getmeme " in message.text else "", "ممی پیدا نشد.")

async def search_google_handler(client, message):
    await _send_inline_result(client, message, "GoogleDEBot", message.text.split("/serchgoogle ", 1)[1] if "/serchgoogle " in message.text else "", "نتیجه‌ای پیدا نشد.")

async def search_youtube_handler(client, message):
    await _send_inline_result(client, message, "uVidBot", message.text.split("/youtube ", 1)[1] if "/youtube " in message.text else "", "ویدیویی پیدا نشد.")

async def send_fonet_handler(client, message):
    fonet = message.text.split("/fonet-> ", 1)[1] if "/fonet-> " in message.text else ""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://api.codebazan.ir/font/?text={quote(fonet)}", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                font_names = (await resp.json())["result"]
        await message.reply_text("".join(f"{i} => {font_names[i]}\n" for i in range(1, min(100, len(font_names)))))
    except Exception as e:
        await message.edit_text(ui_err(f"خطا: {e}"))
