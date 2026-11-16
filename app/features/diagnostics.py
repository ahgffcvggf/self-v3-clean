import asyncio
import os
import platform
import re
import shutil
import time

import psutil
from pyrogram.enums import ParseMode
from app.config import DATA_DIR, START_MONOTONIC, UI_DIVIDER


def _format_uptime(seconds: float) -> str:
    sec = int(seconds); days, rem = divmod(sec, 86400); hours, rem = divmod(rem, 3600); minutes, secs = divmod(rem, 60)
    parts = ([f"{days} روز"] if days else []) + ([f"{hours} ساعت"] if hours else []) + ([f"{minutes} دقیقه"] if minutes else [])
    return " و ".join(parts + [f"{secs} ثانیه"])


def sample_system_metrics():
    proc = psutil.Process(os.getpid())
    vm = psutil.virtual_memory()
    try:
        disk = shutil.disk_usage(DATA_DIR)
        disk_values = (disk.free / 1024**3, disk.total / 1024**3)
    except OSError:
        disk_values = None
    return {"process_ram_mb": proc.memory_info().rss / 1024**2, "system_ram_used_mb": vm.used / 1024**2,
            "system_ram_total_mb": vm.total / 1024**2, "system_ram_percent": vm.percent,
            "cpu_percent": psutil.cpu_percent(interval=None), "cpu_cores": psutil.cpu_count(logical=True) or 1,
            "disk_gb": disk_values}


async def ping_command_handler(client, message):
    if not re.match(r"^\.(?:ping|پینگ)$", (message.text or "").strip().lower()): return
    start = time.monotonic()
    await client.get_me()
    ping_ms = (time.monotonic() - start) * 1000
    # No blocking interval sampling in the event loop; use psutil's cached/nonblocking sample.
    metrics = await asyncio.to_thread(sample_system_metrics)
    disk = metrics["disk_gb"]
    disk_str = f"{disk[0]:.2f} GB آزاد از {disk[1]:.2f} GB" if disk else "ناموجود"
    text = (f"<b>🏓 وضعیت سرویس و پینگ</b>\n{UI_DIVIDER}\n"
            f"• <b>پینگ تلگرام:</b> <code>{ping_ms:.1f} ms</code>\n"
            f"• <b>آپتایم:</b> {_format_uptime(time.monotonic()-START_MONOTONIC)}\n"
            f"• <b>پردازنده:</b> <code>{metrics['cpu_percent']:.1f}%</code> ({metrics['cpu_cores']} هسته)\n"
            f"• <b>رم برنامه:</b> <code>{metrics['process_ram_mb']:.1f} MB</code>\n"
            f"• <b>رم سیستم:</b> <code>{metrics['system_ram_used_mb']:.0f} / {metrics['system_ram_total_mb']:.0f} MB</code> ({metrics['system_ram_percent']:.0f}%)\n"
            f"• <b>فضای Volume:</b> {disk_str}\n• <b>محیط اجرا:</b> {platform.system()} | Python {platform.python_version()}")
    await message.edit_text(text, parse_mode=ParseMode.HTML)
