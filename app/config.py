import os
import re
from zoneinfo import ZoneInfo

# ==== تنظیمات حساس از Environment Variables ====
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

_god_admin_env = os.environ.get("GOD_ADMIN_IDS", "")
GOD_ADMIN_IDS = [int(x) for x in _god_admin_env.split(",") if x.strip().isdigit()]

# ==== دستیار AI ====
AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_API_URL = os.environ.get("AI_API_URL", "")
AI_MODEL = os.environ.get("AI_MODEL", "")
AI_SYSTEM_PROMPT = (
    "تو یک دستیار هوش مصنوعی شخصی برای صاحب اکانت هستی. "
    "نام صاحب اکانت ابوالفضل است. "
    "خصوصیات پاسخ‌گویی:\n"
    "- جواب‌های کوتاه، دقیق، شفاف و کاربردی بده\n"
    "- لحن محترمانه، گرم و صمیمی بدون زیاده‌گویی\n"
    "- اگر چیزی را نمی‌دانی صادقانه بگو\n"
    "- پاسخ‌های فارسی روان و بدون خطای دستوری بنویس"
)

# ==== مسیرهای پایدار روی Railway Volume ====
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", BASE_DIR)
DATA_FILE = os.path.join(DATA_DIR, "bot_data.db")
PRIVATE_CACHE_DIR = os.path.join(DATA_DIR, "private-cache")
WORK_DIR = os.path.join(DATA_DIR, "work")

PANEL_PHOTO_PATH = os.path.join(BASE_DIR, "bot.jpg")
PERSIAN_FONT_PATH = os.path.join(BASE_DIR, "Vazirmatn-Regular.ttf")

for _d in (DATA_DIR, PRIVATE_CACHE_DIR, WORK_DIR):
    os.makedirs(_d, exist_ok=True)

# ==== سقف‌های کش ذخیره پیوی (Railway) ====
MAX_CACHE_FILE_BYTES = 50 * 1024 * 1024       # ۵۰ مگابایت برای هر فایل
MAX_CACHE_TOTAL_BYTES = 1024 * 1024 * 1024    # ۱ گیگابایت کل کش
CACHE_TTL_DAYS = 7                            # ۷ روز نگهداری کش موقت

# ==== تنظیمات ویس فارسی (edge-tts) ====
TTS_VOICES = {
    "female": "fa-IR-DilaraNeural",
    "male": "fa-IR-FaridNeural",
}
MAX_TTS_CHARS = 1500

# ==== زمان و فونت ساعت ====
TEHRAN_TIMEZONE = ZoneInfo("Asia/Tehran")
START_MONOTONIC = __import__("time").monotonic()

FONT_STYLES = {
    "cursive":      {'0':'𝟎','1':'𝟏','2':'𝟐','3':'𝟑','4':'𝟒','5':'𝟓','6':'𝟔','7':'𝟕','8':'𝟖','9':'𝟗',':':':'},
    "stylized":     {'0':'𝟬','1':'𝟭','2':'𝟮','3':'𝟯','4':'𝟰','5':'𝟱','6':'𝟲','7':'𝟳','8':'𝟴','9':'𝟵',':':':'},
    "doublestruck": {'0':'𝟘','1':'𝟙','2':'𝟚','3':'𝟛','4':'𝟜','5':'𝟝','6':'𝟞','7':'𝟟','8':'𝟠','9':'𝟡',':':':'},
    "monospace":    {'0':'𝟶','1':'𝟷','2':'𝟸','3':'𝟹','4':'𝟺','5':'𝟻','6':'𝟼','7':'𝟽','8':'𝟾','9':'𝟿',':':':'},
    "normal":       {'0':'0','1':'1','2':'2','3':'3','4':'4','5':'5','6':'6','7':'7','8':'8','9':'9',':':':'},
    "circled":      {'0':'⓪','1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨',':':'∶'},
    "fullwidth":    {'0':'０','1':'１','2':'２','3':'３','4':'４','5':'５','6':'６','7':'７','8':'８','9':'９',':':'：'},
    "filled":       {'0':'⓿','1':'❶','2':'❷','3':'❸','4':'❹','5':'❺','6':'❻','7':'❼','8':'❽','9':'❾',':':':'},
    "sans":         {'0':'𝟢','1':'𝟣','2':'𝟤','3':'𝟥','4':'𝟦','5':'𝟧','6':'𝟨','7':'𝟩','8':'𝟪','9':'𝟫',':':':'},
    "inverted":     {'0':'0','1':'Ɩ','2':'ᄅ','3':'Ɛ','4':'ㄣ','5':'ϛ','6':'9','7':'ㄥ','8':'8','9':'6',':':':'},
}
FONT_KEYS_ORDER = [
    "cursive", "stylized", "doublestruck", "monospace",
    "normal", "circled", "fullwidth", "filled", "sans", "inverted"
]
ALL_CLOCK_CHARS = "".join(set(char for font in FONT_STYLES.values() for char in font.values()))
CLOCK_CHARS_REGEX_CLASS = f"[{re.escape(ALL_CLOCK_CHARS)}]"

# ==== طراحی UI ====
UI_DIVIDER = "─────────────────"
ICON_ON = "✓"
ICON_OFF = "○"

def ui_ok(text: str) -> str:
    return f"✅ {text}"

def ui_err(text: str) -> str:
    return f"❌ {text}"

def ui_warn(text: str) -> str:
    return f"⚠️ {text}"

def ui_toggle(label: str, state: bool, on_word: str = "فعال شد", off_word: str = "غیرفعال شد") -> str:
    icon = "✅" if state else "⭕️"
    word = on_word if state else off_word
    return f"{icon} {label} {word}"

def ui_status(state: bool) -> str:
    return ICON_ON if state else ICON_OFF

def panel_text(title: str, subtitle: str = "", lines=None) -> str:
    parts = [f"**⚙️ {title}**"]
    if subtitle:
        parts.append(subtitle)
    parts.append(UI_DIVIDER)
    if lines:
        parts.append("\n".join(lines))
    return "\n".join(parts)

# ==== الگوهای فرمان‌ها (برای جلوگیری از ترجمه یا قالب‌بندی ناخواسته) ====
COMMAND_REGEX = (
    r"^(راهنما|ذخیره|تکرار \d+|حذف \d+|ریاکشن .*|ریاکشن خاموش|کپی روشن|کپی خاموش|لیست دشمن|"
    r"تاس|تاس \d+|بولینگ|پنل|panel|ریستارت|ریس|/restart|"
    r"هشتک روشن|hashtag on|هشتک خاموش|hashtag off|ضخیم روشن|bold on|ضخیم خاموش|bold off|"
    r"خط خورده روشن|strikethrough on|خط خورده خاموش|strikethrough off|"
    r"تکی روشن|single on|تکی خاموش|single off|مود روشن|mode on|مود خاموش|mode off|"
    r"تایپینگ روشن|تایپینگ خاموش|بازی روشن|بازی خاموش|آنلاین روشن|آنلاین خاموش|"
    r"تنظیم کامنت .*|setcomment .*|کامنت روشن|comment on|کامنت خاموش|comment off|"
    r"ساعت روشن|time on|ساعت خاموش|time off|ساعت بیو روشن|time bio on|ساعت بیو خاموش|time bio off|"
    r"تنظیم بیو|set bio|تاریخ شمسی روشن|شمسی روشن|jalali on|تاریخ میلادی روشن|میلادی روشن|gregorian on|"
    r"تاریخ خاموش|خاموش|date off|"
    r"قیمت ارز|price|فال|fall|بیو رندوم|random bio|تاریخ امروز|today's date|رم|"
    r"گیممم|Play|/fonet-> .*|/like-> .*|/getgif .*|/getpic .*|/getmeme .*|/serchgoogle .*|/youtube .*|"
    r"دستیار روشن|دستیار خاموش|تست هوش مصنوعی|ساخت ورد .*|ساخت پی دی اف .*|"
    r"\.ربات(?:\s+.*)?|\.id|\.ایدی|\.ping|\.پینگ|\.ویس(?:\s+.*)?|\.اهنگ(?:\s+.*)?|\.آهنگ(?:\s+.*)?|"
    r"ذخیره پیوی روشن|ذخیره پیوی خاموش|آنتی حذف روشن|آنتی حذف خاموش"
    r")$"
)
