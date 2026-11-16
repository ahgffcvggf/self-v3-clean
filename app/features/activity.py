import asyncio
import random
import time
from pyrogram.enums import ChatAction, ChatType
from pyrogram.raw import functions
from app.config import ui_toggle
from app.state import (
    ACTIVE_BOTS, ONLINE_MODE_STATUS, ONLINE_MODE_TASKS,
    PLAYING_MODE_STATUS, TYPING_MODE_STATUS, safe_call
)
from app.storage.db import data_manager


# Only chats explicitly selected by a command receive activity; never scan dialogs.
ACTIVITY_CHAT_TARGETS = {}
ACTIVITY_TARGET_TTL = 300


async def status_action_task(client, user_id: int):
    chat_ids = []
    last_fetch = 0
    while user_id in ACTIVE_BOTS:
        try:
            typing = TYPING_MODE_STATUS.get(user_id, False)
            playing = PLAYING_MODE_STATUS.get(user_id, False)
            if not typing and not playing:
                await asyncio.sleep(2)
                continue
            action = ChatAction.TYPING if typing else ChatAction.PLAYING
            now = time.monotonic()
            targets = ACTIVITY_CHAT_TARGETS.get(user_id, {})
            chat_ids = [chat_id for chat_id, expires in targets.items() if expires > now][:5]
            ACTIVITY_CHAT_TARGETS[user_id] = {chat_id: targets[chat_id] for chat_id in chat_ids}
            for chat_id in chat_ids:
                try:
                    await client.send_chat_action(chat_id, action)
                except Exception:
                    pass
            await asyncio.sleep(random.uniform(8, 15))
        except Exception:
            await asyncio.sleep(60)


async def keep_online_task(client, user_id: int):
    while ONLINE_MODE_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS:
        try:
            await safe_call(client.invoke, functions.account.UpdateStatus(offline=False))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(240, 420))
        if not (ONLINE_MODE_STATUS.get(user_id, False) and user_id in ACTIVE_BOTS):
            break
        try:
            await safe_call(client.invoke, functions.account.UpdateStatus(offline=True))
        except Exception:
            pass
        await asyncio.sleep(random.uniform(30, 90))


async def online_mode_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    ONLINE_MODE_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"online_mode": is_on}})
    if is_on:
        t = ONLINE_MODE_TASKS.get(user_id)
        if not t or t.done():
            ONLINE_MODE_TASKS[user_id] = asyncio.create_task(keep_online_task(client, user_id))
    else:
        t = ONLINE_MODE_TASKS.pop(user_id, None)
        if t:
            t.cancel()
    await message.edit_text(ui_toggle("حالت آنلاین", is_on))


async def activity_mode_toggle_handler(client, message):
    user_id = client.me.id
    text = message.text
    is_on = "روشن" in text
    if is_on:
        ACTIVITY_CHAT_TARGETS[user_id] = {message.chat.id: time.monotonic() + ACTIVITY_TARGET_TTL}
    else:
        ACTIVITY_CHAT_TARGETS.pop(user_id, None)
    if text.startswith("تایپینگ"):
        TYPING_MODE_STATUS[user_id] = is_on
        if is_on:
            PLAYING_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"typing": is_on, "playing": PLAYING_MODE_STATUS.get(user_id, False)}})
        await message.edit_text(ui_toggle("حالت تایپینگ", is_on))
    elif text.startswith("بازی"):
        PLAYING_MODE_STATUS[user_id] = is_on
        if is_on:
            TYPING_MODE_STATUS[user_id] = False
        data_manager.update_user_data(user_id, {"settings": {"playing": is_on, "typing": TYPING_MODE_STATUS.get(user_id, False)}})
        await message.edit_text(ui_toggle("حالت بازی", is_on))
