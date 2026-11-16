import os
import platform
import re
import shutil
import time
import psutil
from pyrogram.enums import ParseMode
from app.config import DATA_DIR, START_MONOTONIC, UI_DIVIDER


def _format_uptime(seconds: float) -> str:
    sec = int(seconds)
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if minutes:
        parts.append(f"{minutes} دقیقه")
    parts.append(f"{secs} ثانیه")
    return " و ".join(parts)


async def ping_command_handler(client, message):
    raw = (message.text or "").strip().lower()
    if not re.match(r"^\.(?:ping|پینگ)$", raw):
        return

    t0 = time.monotonic()
    await client.get_me()
    tg_ping_ms = (time.monotonic() - t0) * 1000

    proc = psutil.Process(os.getpid())
    proc_ram_mb = proc.memory_info().rss / (1024 * 1024)
    vm = psutil.virtual_memory()
    sys_ram_used_mb = vm.used / (1024 * 1024)
    sys_ram_total_mb = vm.total / (1024 * 1024)
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_cores = psutil.cpu_count(logical=True) or 1

    try:
        disk = shutil.disk_usage(DATA_DIR)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)
        disk_str = f"{disk_free_gb:.2f} GB آزاد از {disk_total_gb:.2f} GB"
    except Exception:
        disk_str = "ناموجود"

    uptime_str = _format_uptime(time.monotonic() - START_MONOTONIC)
    py_ver = platform.python_version()
    sys_os = platform.system()

    text = (
        f"<b>🏓 وضعیت سرویس و پینگ</b>\n"
        f"{UI_DIVIDER}\n"
        f"• <b>پینگ تلگرام:</b> <code>{tg_ping_ms:.1f} ms</code>\n"
        f"• <b>آپتایم:</b> {uptime_str}\n"
        f"• <b>پردازنده (CPU):</b> <code>{cpu_percent:.1f}%</code> ({cpu_cores} هسته)\n"
        f"• <b>رم برنامه:</b> <code>{proc_ram_mb:.1f} MB</code>\n"
        f"• <b>رم کانتینر:</b> <code>{sys_ram_used_mb:.0f} / {sys_ram_total_mb:.0f} MB</code> ({vm.percent:.0f}%)\n"
        f"• <b>فضای Volume:</b> {disk_str}\n"
        f"• <b>محیط اجرا:</b> {sys_os} | Python {py_ver}"
    )
    await message.edit_text(text, parse_mode=ParseMode.HTML)
