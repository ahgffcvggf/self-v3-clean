import json
import logging
import os
import re
import time
import aiohttp
from pyrogram.enums import ChatAction, ParseMode
from app.config import (
    AI_API_KEY, AI_API_URL, AI_MODEL, AI_SYSTEM_PROMPT,
    PERSIAN_FONT_PATH, WORK_DIR, ui_toggle, ui_warn
)
from app.state import AI_ASSISTANT_STATUS, record_generated_message, safe_call
from app.storage.db import data_manager

try:
    from docx import Document
except ImportError:
    Document = None

try:
    from fpdf import FPDF
except ImportError:
    FPDF = None

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    _PERSIAN_SHAPING_AVAILABLE = True
except ImportError:
    _PERSIAN_SHAPING_AVAILABLE = False


async def get_ai_reply(
    user_message: str,
    replied_message: str = None,
    client=None,
    account_id: int = None,
    chat_id: int = None,
    save_history: bool = True,
):
    if not AI_API_KEY or not AI_API_URL or not AI_MODEL:
        logging.warning("تنظیمات AI_API_KEY / AI_API_URL / AI_MODEL کامل نیست.")
        return None
    if not user_message:
        return None

    messages = [{"role": "system", "content": AI_SYSTEM_PROMPT}]

    if account_id is not None and chat_id is not None and save_history:
        history = data_manager.get_chat_history(account_id, chat_id, limit=8)
        for msg_type, content in history:
            role = "user" if msg_type == "user" else "assistant"
            messages.append({"role": role, "content": content})

    if replied_message:
        messages.append({"role": "user", "content": f"پیام ریپلای‌شده:\n{replied_message}"})

    messages.append({"role": "user", "content": user_message})

    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": AI_MODEL,
        "messages": messages,
        "max_tokens": 1200,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                AI_API_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as response:
                raw_body = await response.text()
                if response.status != 200:
                    logging.error(f"خطای API دستیار AI ({response.status}): {raw_body[:500]}")
                    return None

                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" in content_type or raw_body.lstrip().startswith("data:"):
                    full_text = ""
                    for line in raw_body.splitlines():
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if chunk == "[DONE]" or not chunk:
                            continue
                        try:
                            chunk_json = json.loads(chunk)
                            delta = chunk_json["choices"][0]
                            piece = (
                                delta.get("delta", {}).get("content")
                                or delta.get("message", {}).get("content")
                                or ""
                            )
                            full_text += piece
                        except Exception:
                            continue
                    result = full_text.strip()
                else:
                    data = json.loads(raw_body)
                    result = data["choices"][0]["message"]["content"].strip()

                if result and account_id is not None and chat_id is not None and save_history:
                    data_manager.save_chat_message(account_id, chat_id, "user", user_message)
                    data_manager.save_chat_message(account_id, chat_id, "ai", result)
                return result or None
    except Exception as e:
        logging.error(f"خطا در ارتباط با API دستیار AI: {type(e).__name__}: {e}")
        return None


async def ai_robot_command_handler(client, message):
    """
    فقط پیام‌های خود صاحب اکانت که دقیقاً با `.ربات` شروع شوند پردازش می‌شوند.
    `ربات ...` یا `.رباتی` یا وجود `.ربات` در وسط جمله نادیده گرفته می‌شود.
    """
    owner_id = client.me.id
    if not AI_ASSISTANT_STATUS.get(owner_id, False):
        return
    if not message.text:
        return

    text = message.text.strip()
    m = re.match(r"^\.ربات(?:\s+(.*))?$", text, re.DOTALL)
    if not m:
        return

    query = (m.group(1) or "").strip()
    if not query:
        sent = await safe_call(
            message.reply_text,
            "🤖 برای پرسیدن سؤال، متن را بعد از دستور بنویسید.\nمثال: <code>.ربات امروز هوا چطوره؟</code>",
            parse_mode=ParseMode.HTML,
        )
        if sent:
            record_generated_message(owner_id, message.chat.id, sent.id)
        return

    try:
        await client.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:
        pass

    replied_text = None
    if message.reply_to_message:
        replied_text = message.reply_to_message.text or message.reply_to_message.caption

    reply = await get_ai_reply(
        query,
        replied_message=replied_text,
        client=client,
        account_id=owner_id,
        chat_id=message.chat.id,
        save_history=True,
    )
    if reply:
        sent = await safe_call(message.reply_text, reply)
        if sent:
            record_generated_message(owner_id, message.chat.id, sent.id)
    else:
        sent = await safe_call(message.reply_text, "❌ پاسخی از سرویس AI دریافت نشد.")
        if sent:
            record_generated_message(owner_id, message.chat.id, sent.id)


async def ai_assistant_toggle_handler(client, message):
    user_id = client.me.id
    is_on = "روشن" in message.text
    AI_ASSISTANT_STATUS[user_id] = is_on
    data_manager.update_user_data(user_id, {"settings": {"ai_assistant": is_on}})
    await message.edit_text(ui_toggle("دستیار AI (.ربات)", is_on))


async def ai_test_handler(client, message):
    try:
        await message.edit_text("⏳ در حال تست اتصال دستیار AI...")
        reply = await get_ai_reply("سلام، فقط یک جمله کوتاه بنویس.", save_history=False)
        if reply:
            await message.edit_text(f"✅ سرویس AI متصل است:\n{reply}")
        else:
            await message.edit_text("❌ سرویس AI پاسخ نداد؛ تنظیمات API را بررسی کنید.")
    except Exception as e:
        await message.edit_text(f"❌ خطا در تست AI: {type(e).__name__}: {e}")


def _shape_persian(text: str) -> str:
    if not _PERSIAN_SHAPING_AVAILABLE:
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


async def create_word_file_handler(client, message):
    instruction = message.text.split("ساخت ورد ", 1)[1].strip() if "ساخت ورد " in message.text else ""
    if Document is None:
        await safe_call(message.reply_text, "❌ کتابخانه `python-docx` نصب نیست.")
        return
    if not instruction:
        await safe_call(message.reply_text, ui_warn("توضیح فایل ورد را بنویسید. مثال: `ساخت ورد گزارش هوش مصنوعی`"))
        return

    await safe_call(message.edit_text, "⏳ در حال ساخت فایل Word...")
    content = await get_ai_reply(
        f"متن کامل و نهایی زیر را برای فایل Word آماده کن (بدون Markdown اضافه):\n{instruction}",
        save_history=False,
    )
    if not content:
        await safe_call(message.reply_text, "❌ محتوایی از AI دریافت نشد.")
        return

    doc = Document()
    for line in content.split("\n"):
        doc.add_paragraph(line)

    output_path = os.path.join(WORK_DIR, f"word_{client.me.id}_{int(time.time())}.docx")
    try:
        doc.save(output_path)
        sent = await safe_call(client.send_document, message.chat.id, output_path, caption="✅ فایل Word ساخته شد.")
        if sent:
            record_generated_message(client.me.id, message.chat.id, sent.id)
    finally:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


async def create_pdf_file_handler(client, message):
    instruction = message.text.split("ساخت پی دی اف ", 1)[1].strip() if "ساخت پی دی اف " in message.text else ""
    if FPDF is None:
        await safe_call(message.reply_text, "❌ کتابخانه `fpdf2` نصب نیست.")
        return
    if not instruction:
        await safe_call(message.reply_text, ui_warn("توضیح فایل PDF را بنویسید. مثال: `ساخت پی دی اف خلاصه معماری کامپیوتر`"))
        return

    await safe_call(message.edit_text, "⏳ در حال ساخت فایل PDF...")
    content = await get_ai_reply(
        f"متن کامل و نهایی زیر را برای فایل PDF آماده کن (بدون Markdown اضافه):\n{instruction}",
        save_history=False,
    )
    if not content:
        await safe_call(message.reply_text, "❌ محتوایی از AI دریافت نشد.")
        return

    pdf = FPDF()
    pdf.add_page()
    use_persian_font = os.path.isfile(PERSIAN_FONT_PATH)
    if not use_persian_font:
        await safe_call(message.reply_text, ui_warn("فونت فارسی Vazirmatn-Regular.ttf یافت نشد؛ خروجی PDF ممکن است حروف فارسی را درست نمایش ندهد."))
    if use_persian_font:
        pdf.add_font("Vazir", "", PERSIAN_FONT_PATH, uni=True)
        pdf.set_font("Vazir", size=13)
    else:
        pdf.set_font("Arial", size=12)

    for line in content.split("\n"):
        display_line = _shape_persian(line) if use_persian_font else line
        pdf.multi_cell(0, 8, display_line, align="R" if use_persian_font else "L")

    output_path = os.path.join(WORK_DIR, f"pdf_{client.me.id}_{int(time.time())}.pdf")
    try:
        pdf.output(output_path)
        sent = await safe_call(client.send_document, message.chat.id, output_path, caption="✅ فایل PDF ساخته شد.")
        if sent:
            record_generated_message(client.me.id, message.chat.id, sent.id)
    finally:
        if os.path.isfile(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
