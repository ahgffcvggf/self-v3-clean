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
            now = time.time()
            if not chat_ids or (now - last_fetch > 300):
                new_chats = []
                async for dialog in client.get_dialogs(limit=10):
                    if dialog.chat.type in [ChatType.PRIVATE, ChatType.GROUP, ChatType.SUPERGROUP]:
                        new_chats.append(dialog.chat.id)
                chat_ids = new_chats
                last_fetch = now
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
