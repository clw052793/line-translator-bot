
import os
import re
import json
import hmac
import logging
import time
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

from linebot import LineBotApi, WebhookHandler
from linebot.models import TextMessage, MessageEvent, TextSendMessage
from linebot.exceptions import InvalidSignatureError

from deep_translator import GoogleTranslator

# --- Optional Google Sheets ---
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GS_AVAILABLE = True
except ImportError:
    GS_AVAILABLE = False

# --- Optional OpenAI ---
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ============================================================
# 1. Environment and logging
# ============================================================

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO")
)

logger = logging.getLogger("line-translator")

app = Flask(__name__)

DetectorFactory.seed = 0

MAX_TEXT_LENGTH = int(
    os.getenv("MAX_TEXT_LENGTH", "3000")
)


# ============================================================
# 2. LINE setup
# ============================================================

LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LINE_CHANNEL_SECRET = os.getenv(
    "LINE_CHANNEL_SECRET"
)

line_bot_api = (
    LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
    if LINE_CHANNEL_ACCESS_TOKEN
    else None
)

handler = (
    WebhookHandler(LINE_CHANNEL_SECRET)
    if LINE_CHANNEL_SECRET
    else None
)

if not line_bot_api or not handler:
    logger.warning("LINE credentials are missing")


# ============================================================
# 3. Google Sheets setup
# ============================================================

sheet = None

GS_KEY = os.getenv("GOOGLE_SHEET_KEY")
GS_JSON = os.getenv("GOOGLE_SHEET_JSON")

if GS_AVAILABLE and GS_KEY and GS_JSON:

    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]

    try:
        try:
            credentials_dict = json.loads(GS_JSON)

            credentials = (
                ServiceAccountCredentials
                .from_json_keyfile_dict(
                    credentials_dict,
                    scope
                )
            )

        except json.JSONDecodeError:
            credentials = (
                ServiceAccountCredentials
                .from_json_keyfile_name(
                    GS_JSON,
                    scope
                )
            )

        gc = gspread.authorize(credentials)

        sheet = gc.open_by_key(GS_KEY).sheet1

        logger.info("Google Sheets connected")

    except Exception:
        logger.exception(
            "Google Sheets initialization failed"
        )


# ============================================================
# 4. Original Indonesian dictionary
# ============================================================

indonesian_abbreviation_map = {

    # 人稱與稱謂
    "ad": "弟弟",
    "adik": "弟弟",
    "kak": "哥哥",
    "ce": "姐姐",
    "cece": "姐姐",
    "ibu": "媽媽",
    "bpk": "先生",
    "ayah": "爸爸",
    "nenek": "奶奶",
    "kakek": "爺爺",
    "cucu": "孫子",
    "tmn": "朋友",
    "tm": "他們",
    "sy": "我",
    "aku": "我",
    "saya": "我",
    "kmu": "你",
    "km": "你",
    "anda": "您",
    "dy": "他/她",
    "dia": "他/她",
    "dya": "他/她",

    # 時間與日期
    "pagi": "早上",
    "siang": "中午",
    "sore": "下午",
    "malam": "晚上",
    "bsk": "明天",
    "besok": "明天",
    "kmrn": "昨天",
    "kemarin": "昨天",
    "td": "剛才",
    "tdi": "剛才",
    "nanti": "等一下",
    "udh": "已經",
    "sudah": "已經",
    "blm": "還沒",
    "belum": "還沒",
    "hr": "假期",
    "hari": "天",
    "jam": "pukul",
    "pagi2": "早上早點",
    "siang2": "中午時候",

    # 照護與生活動作
    "makan": "吃",
    "mkn": "吃",
    "minum": "喝",
    "mandi": "洗澡",
    "mandikan": "幫洗澡",
    "ganti": "換",
    "tidur": "睡覺",
    "t": "tidur",
    "bangun": "起床",
    "temani": "陪",
    "pulang": "回家",
    "bantu": "幫忙",
    "rehabilitas": "復健",
    "bersih": "打掃",
    "cuci": "洗",
    "masak": "煮",
    "masaknya": "煮的",
    "masukan": "放進",
    "potong": "切",
    "lihat": "看見",
    "lihat2": "看看",
    "pegang": "拿著",
    "tutup": "關上",
    "buka": "打開",

    # 聊天口語縮寫
    "aj": "aja",
    "ajh": "aja",
    "aja": "就好",
    "deh": "就這樣吧",
    "bwt": "buat",
    "buat": "為了",
    "jg": "juga",
    "jgk": "juga",
    "jga": "juga",
    "jdi": "jadi",
    "jd": "jadi",
    "kl": "kalau",
    "klw": "kalau",
    "klo": "kalau",
    "krn": "karena",
    "karna": "karena",
    "iya": "ya",
    "lya": "是的",
    "yaudah": "好啦",
    "ywdh": "好啦",
    "ngga": "不",
    "ga": "不",
    "gk": "不",
    "nggak": "不",
    "nggaaa": "不",
    "gt": "gitu",
    "gtu": "gitu",
    "gitu": "那樣",
    "gtw": "不知道",
    "sm": "sama",
    "sm2": "sama-sama",
    "trs": "terus",
    "trus": "terus",
    "sja": "saja",
    "sllu": "selalu",
    "skrg": "現在",
    "dr": "醫生",
    "dok": "醫生",
    "tp": "tapi",
    "tpi": "tapi",
    "tapi": "但是",
    "ok": "好",
    "okee": "好喔",
    "okey": "好喔",
    "sip": "好",
    "mantap": "太棒了",
    "btw": "順便說一下",

    # 物件與地點
    "rumah": "家",
    "rmh": "家",
    "pintu": "門口",
    "dpn": "前面",
    "belakang": "後面",
    "mobil": "車",
    "motor": "摩托車",
    "uang": "錢",
    "sayur": "蔬菜",
    "beras": "米",
    "air": "水",
    "kursi": "椅子",
    "meja": "桌子",
    "dapur": "廚房",
    "kamar": "房間",
    "tempat tidur": "床",
    "jendela": "窗戶",
    "halaman": "院子",

    # 工作、單位與學校
    "bca": "銀行",
    "pt": "有限公司",
    "sd": "小學",
    "smp": "初中",
    "smk": "中等職業學校",
    "tk": "幼兒園",
    "rt": "居民社區",
    "rw": "社區範圍",
    "kkn": "社會服務",
    "tni": "印度尼西亞國軍",
    "polri": "印度尼西亞警察",
    "wfh": "在家工作",
    "wfo": "辦公室工作",
    "umkm": "微型企業",
    "wmm": "微型企業",

    # 其他補充
    "faq": "常見問題",
    "bkn": "不是",
    "bsa": "bisa",
    "bisa": "可以",
    "saja": "就好",
    "karena": "因為",
    "krg": "少",
    "susa": "susah",
    "habis": "吃完",
    "selesai": "結束",
    "sayang": "親愛的",
    "syg": "親愛的",
    "gpp": "沒關係",
    "nd": "下屬",
    "orang": "人",
    "wkwk": "哈哈",
    "haha": "哈哈",
    "hehe": "呵呵",
    "loh": "呀",
    "lah": "啦",
    "nih": "這個",
    "dong": "啦",
    "kok": "怎麼會",
    "lohkok": "怎麼啦",
    "lho": "呢",
    "dehh": "就這樣吧",
    "bt": "生氣",
    "pd": "自信",
    "pls": "請",
    "thx": "謝謝",
    "makasih": "謝謝",
    "terima kasih": "謝謝",
    "okelah": "好吧",
    "gapapa": "沒事",
    "okeeh": "好喔",
    "mantul": "很棒"
}


# ============================================================
# 5. Original Chinese-Indonesian vocabulary
# ============================================================

chinese_indonesian_vocab = {

    "奶奶": "nenek",
    "白天": "siang hari",
    "有": "ada",
    "排便": "buang air besar",
    "多": "banyak",
    "很少": "sangat sedikit",
    "只有": "hanya",
    "一點點": "sedikit",
    "好": "bagus",
    "姐姐": "ce",
    "吃": "makan",
    "水果": "buah",
    "切": "potong",
    "小": "kecil",
    "可以": "bisa",
    "吃下": "dapat dimakan",
    "木瓜": "pepaya",
    "牛奶": "susu",
    "日期": "tanggal",
    "喝": "minum",
    "煮": "masak",
    "秋葵": "okra",
    "熟": "matang",
    "幫": "bantu",
    "拍": "ambil foto",
    "鍋子": "pot",
    "洗": "cuci",
    "盆子": "baskom",
    "瓦斯爐": "kompor gas",
    "布": "kain",
    "下午": "sore",
    "熱": "panas",
    "晚餐": "makan malam",
    "冰": "dingin",
    "蒸熟": "dikukus",
    "順序": "urutan",
    "午餐": "makan siang",
    "卡片": "kartu",
    "BPJS": "BPJS",
    "健保卡": "kartu asuransi kesehatan",
    "忘記": "lupa",
    "帶回家": "membawa pulang",
    "更新": "diperbarui",
    "換新單": "ubah pesanan baru",
    "快": "cepat",
    "回來": "kembali",
    "蓮霧": "apel lilin",
    "冰箱": "lemari es",
    "客廳": "ruang tamu",
    "桌子": "meja",
    "紅": "merah",
    "敬拜": "ibadah",
    "祈禱": "berdoa",
    "問": "tanya",
    "按摩": "pijat",
    "貓": "kucing",
    "颱風": "topan",
    "注意": "hati-hati",
    "大聲": "keras",
    "藥": "obat",
    "屁股": "pantat",
    "狀況": "situasi",
    "塞劑": "agen plugging",
    "水": "air",
    "開水": "air rebus",
    "下大雨": "hujan deras",
    "雨停": "hujan berhenti",
    "樓上": "lantai atas",
    "外面": "luar",
    "拿": "ambil",
    "水果剝": "kupas buah",
    "損壞": "rusak",
    "梨子": "pir",
    "香瓜": "melon",
    "圓形": "bulat",
    "吃完": "habis",
    "黑": "hitam",
    "紅菠菜": "bayam merah",
    "寄": "kirim",
    "箱": "kotak",
    "送": "antar",
    "今天": "hari ini",
    "明天": "besok",
    "簽收": "tanda tangan",
    "上次": "terakhir",
    "外箱": "kotak外",
    "粉紅色": "merah muda",
    "下面": "di bawah",
    "還沒": "belum",
    "遵循": "mengikuti",
    "日期順序": "urutan tanggal",
}


# ============================================================
# 6. Abbreviation normalization
# ============================================================

# 保留完整原始詞庫，但只正規化明確縮寫。
# 不再把印尼文直接替換成中文。

indonesian_normalization_map = {

    "sy": "saya",
    "kmu": "kamu",
    "km": "kamu",
    "dy": "dia",
    "dya": "dia",
    "tmn": "teman",

    "bsk": "besok",
    "kmrn": "kemarin",
    "tdi": "tadi",
    "udh": "sudah",
    "blm": "belum",

    "mkn": "makan",

    "aj": "aja",
    "ajh": "aja",
    "bwt": "buat",
    "jg": "juga",
    "jgk": "juga",
    "jga": "juga",
    "jdi": "jadi",
    "jd": "jadi",

    "kl": "kalau",
    "klw": "kalau",
    "klo": "kalau",

    "krn": "karena",
    "karna": "karena",

    "ngga": "tidak",
    "ga": "tidak",
    "gk": "tidak",
    "nggak": "tidak",
    "nggaaa": "tidak",

    "gt": "gitu",
    "gtu": "gitu",

    "sm": "sama",
    "sm2": "sama-sama",

    "trs": "terus",
    "trus": "terus",

    "sja": "saja",
    "sllu": "selalu",
    "skrg": "sekarang",

    "tp": "tapi",
    "tpi": "tapi",

    "bkn": "bukan",
    "bsa": "bisa",

    "gpp": "tidak apa-apa",
    "gapapa": "tidak apa-apa",

    "makasih": "terima kasih",

    "rmh": "rumah",
    "dpn": "depan",

    "ywdh": "ya sudah",
    "gtw": "tidak tahu",
    "krg": "kurang",
    "susa": "susah"
}


def expand_abbreviations(text):

    keys = sorted(
        indonesian_normalization_map.keys(),
        key=len,
        reverse=True
    )

    pattern = re.compile(
        r'(?<!\w)('
        + "|".join(re.escape(k) for k in keys)
        + r')(?!\w)',
        flags=re.IGNORECASE
    )

    return pattern.sub(
        lambda m: indonesian_normalization_map.get(
            m.group(0).lower(),
            m.group(0)
        ),
        text
    )


# ============================================================
# 7. Language detection
# ============================================================

def detect_language(text):

    t = text.strip()

    if not t:
        return None, text

    # 中文優先
    if re.search(r'[\u4e00-\u9fff]', t):
        return "chinese", text

    tokens = re.findall(
        r'[A-Za-z0-9]+',
        t.lower()
    )

    # 印尼文詞庫
    if any(
        token in indonesian_abbreviation_map
        or token in indonesian_normalization_map
        for token in tokens
    ):
        return "indonesian", text

    # 印尼文常見詞
    if re.search(
        r'\b(saya|aku|kamu|nenek|makan|'
        r'tidur|sudah|belum|besok|pagi|'
        r'siang|sore|malam|terima|kasih|'
        r'berapa|kenapa|bagaimana|'
        r'bisa|tolong|jangan)\b',
        t.lower()
    ):
        return "indonesian", text

    try:
        detected = detect(t).lower()

        if detected in ("id", "in", "ms"):
            return "indonesian", text

        if detected.startswith("zh"):
            return "chinese", text

        return detected, text

    except LangDetectException:
        return None, text


# ============================================================
# 8. Time conversion
# ============================================================

def convert_jam_to_hhmm(text):

    """
    Examples:

    jam 9          -> 09:00
    jam9           -> 09:00
    jam 9:30       -> 09:30
    jam 9.30       -> 09:30
    jam 9.5        -> 09:30
    jam 3 sore     -> 15:00
    jam 9 malam    -> 21:00

    不確定的時間不強制轉換。
    """

    pattern = re.compile(
        r'(?<!\w)(?:jam|pukul)\s*'
        r'(\d{1,2})'
        r'(?:([:.,])(\d{1,2}))?'
        r'\s*(pagi|siang|sore|malam|am|pm)?'
        r'(?!\w)',
        flags=re.IGNORECASE
    )

    def replace_time(match):

        hour = int(match.group(1))

        separator = match.group(2)
        minute_part = match.group(3)

        period = (
            match.group(4) or ""
        ).lower()

        if hour > 23:
            return match.group(0)

        minute = 0

        if minute_part is not None:

            # jam 9.5 = 9:30
            if (
                separator in (".", ",")
                and len(minute_part) == 1
            ):
                minute = int(minute_part) * 6

            else:
                minute = int(minute_part)

        if minute > 59:
            return match.group(0)

        if period in ("sore", "malam", "pm"):

            if 1 <= hour <= 11:
                hour += 12

        elif period in ("pagi", "am"):

            if hour == 12:
                hour = 0

        elif period == "siang":

            if 1 <= hour <= 6:
                hour += 12

        # 有上午/下午標記卻使用不合理時間時，
        # 保留原文避免錯誤轉換。
        if period and hour > 23:
            return match.group(0)

        return f"{hour:02d}:{minute:02d}"

    return pattern.sub(replace_time, text)


def preprocess_text(text, lang):

    if lang == "indonesian":

        text = convert_jam_to_hhmm(text)

        text = expand_abbreviations(text)

    return text


# ============================================================
# 9. Optimized glossary
# ============================================================

# 完整詞庫保留，但僅傳送相關專有名詞。
# 一般詞彙交給 AI 理解。

SPECIAL_ID_TERMS = {
    "ce", "cece", "kak", "bpk",
    "rehabilitas", "bpjs",
    "gpp", "gtw", "wkwk"
}

SPECIAL_ZH_TERMS = {
    "奶奶",
    "姐姐",
    "排便",
    "復健",
    "健保卡",
    "塞劑",
    "蓮霧",
    "秋葵",
    "紅菠菜",
    "瓦斯爐",
    "BPJS"
}


def make_glossary(text, source_lang):

    pairs = []

    if source_lang == "Indonesian":

        for key in SPECIAL_ID_TERMS:

            pattern = (
                r'(?<!\w)'
                + re.escape(key)
                + r'(?!\w)'
            )

            if re.search(
                pattern,
                text,
                flags=re.IGNORECASE
            ):

                meaning = (
                    indonesian_abbreviation_map.get(key)
                )

                if meaning:
                    pairs.append(
                        f"{key}: {meaning}"
                    )

    else:

        for key in SPECIAL_ZH_TERMS:

            if key in text:

                meaning = (
                    chinese_indonesian_vocab.get(key)
                )

                if meaning:
                    pairs.append(
                        f"{key}: {meaning}"
                    )

    return "\n".join(sorted(pairs)[:12])


# ============================================================
# 10. Translation cache
# ============================================================

CACHE_SIZE = int(
    os.getenv("TRANSLATION_CACHE_SIZE", "2048")
)

CACHE_TTL = int(
    os.getenv("TRANSLATION_CACHE_TTL", "86400")
)

_translation_cache = OrderedDict()
_cache_lock = threading.Lock()


def cache_get(key):

    now = time.monotonic()

    with _cache_lock:

        entry = _translation_cache.get(key)

        if entry is None:
            return None

        value, expires = entry

        if now >= expires:
            del _translation_cache[key]
            return None

        _translation_cache.move_to_end(key)

        return value


def cache_set(key, value):

    if not value:
        return

    with _cache_lock:

        _translation_cache[key] = (
            value,
            time.monotonic() + CACHE_TTL
        )

        _translation_cache.move_to_end(key)

        while len(_translation_cache) > CACHE_SIZE:
            _translation_cache.popitem(last=False)


# ============================================================
# 11. OpenAI configuration
# ============================================================

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-6-luna"
)

OPENAI_KEY = os.getenv("OPENAI_API_KEY")

_openai_client = (
    OpenAI(
        api_key=OPENAI_KEY,
        timeout=15.0,
        max_retries=0
    )
    if OPENAI_KEY and OpenAI
    else None
)

OPENAI_MAX_COMPLETION_TOKENS = int(
    os.getenv(
        "OPENAI_MAX_COMPLETION_TOKENS",
        "500"
    )
)

OPENAI_QUOTA_RECHECK_SECONDS = int(
    os.getenv(
        "OPENAI_QUOTA_RECHECK_SECONDS",
        "3600"
    )
)

_openai_unavailable_until = 0.0
_openai_last_error = None
_openai_state_lock = threading.Lock()


def openai_available():

    if _openai_client is None:
        return False

    with _openai_state_lock:
        return (
            time.monotonic()
            >= _openai_unavailable_until
        )


def handle_openai_error(error):

    global _openai_unavailable_until
    global _openai_last_error

    status = getattr(error, "status_code", None)

    body = getattr(error, "body", None)

    code = getattr(error, "code", None)

    if isinstance(body, dict):

        error_data = body.get("error", body)

        if isinstance(error_data, dict):
            code = code or error_data.get("code")

    error_text = str(error).lower()

    if (
        code == "insufficient_quota"
        or "insufficient_quota" in error_text
        or "exceeded your current quota" in error_text
    ):

        category = "quota_exhausted"

        logger.error(
            "OPENAI_CREDIT_EXHAUSTED"
        )

        with _openai_state_lock:
            _openai_unavailable_until = (
                time.monotonic()
                + OPENAI_QUOTA_RECHECK_SECONDS
            )

    elif (
        status == 401
        or code == "invalid_api_key"
    ):

        category = "authentication_error"

        logger.error(
            "OPENAI_AUTHENTICATION_ERROR"
        )

    elif (
        code == "model_not_found"
        or "model_not_found" in error_text
        or "does not exist" in error_text
    ):

        category = "model_error"

        logger.error(
            "OPENAI_MODEL_NOT_AVAILABLE"
        )

    elif status == 400:

        category = "bad_request"

        logger.error(
            "OPENAI_BAD_REQUEST"
        )

    elif status == 429:

        category = "rate_limit"

        logger.warning(
            "OPENAI_RATE_LIMIT"
        )

    elif status in (500, 502, 503, 504):

        category = "server_error"

        logger.warning(
            "OPENAI_SERVER_ERROR"
        )

    else:

        category = "api_error"

        logger.error(
            "OPENAI_API_ERROR"
        )

    with _openai_state_lock:
        _openai_last_error = category

    # 記錄錯誤原因，但不記錄 API Key 或原始對話。
    logger.error(
        "OpenAI detail: status=%s code=%s "
        "type=%s message=%s",
        status,
        code,
        type(error).__name__,
        str(error)[:500]
    )

    return category


# ============================================================
# 12. OpenAI translation
# ============================================================

def openai_translate(src_lang, tgt_lang, text):

    if not _openai_client:
        raise RuntimeError(
            "OpenAI client not configured"
        )

    glossary = make_glossary(
        text,
        src_lang
    )

    system_prompt = (
        "You translate Indonesian and Traditional "
        "Chinese for everyday elderly-care conversations. "
        "Produce natural, grammatically correct, "
        "faithful translations. Understand Indonesian "
        "slang and abbreviations. Preserve names, "
        "numbers, and existing HH:MM times. "
        "Keep questions as questions. "
        "Do not add or remove meaning. "
        "Use Taiwan Traditional Chinese when translating "
        "to Chinese. Return only the translation."
    )

    if glossary:

        system_prompt += (
            "\nRelevant terminology:\n"
            + glossary
        )

    user_prompt = (
        f"Translate from {src_lang} "
        f"to {tgt_lang}:\n\n{text}"
    )

    try:

        response = (
            _openai_client
            .chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                max_completion_tokens=(
                    OPENAI_MAX_COMPLETION_TOKENS
                )
            )
        )

        translated = (
            response.choices[0].message.content
            or ""
        ).strip()

        if not translated:
            raise RuntimeError(
                "OpenAI returned empty translation"
            )

        return translated

    except Exception as error:

        handle_openai_error(error)

        raise


# ============================================================
# 13. Google Translate fallback
# ============================================================

translator_id_zh = GoogleTranslator(
    source="id",
    target="zh-TW"
)

translator_zh_id = GoogleTranslator(
    source="zh-TW",
    target="id"
)


def google_translate(source, target, text):

    # Google 只作備援，不快取錯誤訊息。

    if source == "id":

        result = translator_id_zh.translate(text)

    elif source.startswith("zh"):

        result = translator_zh_id.translate(text)

    else:

        result = GoogleTranslator(
            source=source,
            target=target
        ).translate(text)

    if not result or not result.strip():

        raise RuntimeError(
            "Google returned empty translation"
        )

    return result.strip()


# ============================================================
# 14. Google Sheets asynchronous logging
# ============================================================

# 使用單一背景工作執行緒。
# LINE 回覆不必等待 Google Sheets 寫入完成。
# 這是盡力寫入，不保證服務重啟前所有資料都完成。

_sheet_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix="sheet-writer"
)

_sheet_pending = threading.BoundedSemaphore(100)


def save_to_sheet_row(
    original,
    translated,
    metadata=None
):

    if sheet is None:
        return False

    timestamp = datetime.now(
        ZoneInfo("Asia/Taipei")
    ).strftime("%Y-%m-%d %H:%M:%S")

    row = [
        timestamp,
        original,
        translated,
        json.dumps(
            metadata or {},
            ensure_ascii=False
        )
    ]

    if not _sheet_pending.acquire(blocking=False):

        logger.warning(
            "GOOGLE_SHEETS_QUEUE_FULL"
        )

        return False

    def write_task():

        try:

            for attempt in range(2):

                try:

                    sheet.append_row(
                        row,
                        value_input_option="RAW"
                    )

                    return

                except Exception as error:

                    logger.warning(
                        "GOOGLE_SHEETS_WRITE_FAILED "
                        "attempt=%s type=%s",
                        attempt + 1,
                        type(error).__name__
                    )

                    if attempt == 0:
                        time.sleep(0.5)

        finally:
            _sheet_pending.release()

    try:

        _sheet_executor.submit(write_task)

        return True

    except RuntimeError:

        _sheet_pending.release()

        return False


# ============================================================
# 15. Rate limiting
# ============================================================

RATE_LIMIT = int(
    os.getenv(
        "RATE_LIMIT_PER_MIN",
        "30"
    )
)

_rate_store = {}
_rate_lock = threading.Lock()


def rate_limited(key):

    now = time.monotonic()

    with _rate_lock:

        count, start = _rate_store.get(
            key,
            (0, now)
        )

        if now - start >= 60:
            count = 0
            start = now

        if count >= RATE_LIMIT:
            return True

        _rate_store[key] = (
            count + 1,
            start
        )

        # 定期清除過期紀錄
        if len(_rate_store) > 5000:

            expired = [
                k for k, (_, s) in _rate_store.items()
                if now - s >= 120
            ]

            for k in expired:
                _rate_store.pop(k, None)

        return False


# ============================================================
# 16. Main translation pipeline
# ============================================================

def process_message(
    text,
    client_key="anonymous"
):

    if not isinstance(text, str):
        return {"error": "請輸入有效文字"}

    text = text.strip()

    if not text:
        return {"error": "請輸入有效文字"}

    if len(text) > MAX_TEXT_LENGTH:
        return {
            "error": (
                f"文字過長，最多 {MAX_TEXT_LENGTH} 字"
            )
        }

    if rate_limited(client_key):
        return {
            "error": (
                f"速率限制：每 60 秒最多 "
                f"{RATE_LIMIT} 次"
            )
        }

    lang, cleaned = detect_language(text)

    if not lang:
        return {"error": "無法偵測語言"}

    lang = str(lang).lower()

    # Indonesian -> Traditional Chinese
    if (
        lang == "indonesian"
        or lang.startswith("id")
    ):

        expanded = expand_abbreviations(cleaned)

        pre = preprocess_text(
            expanded,
            "indonesian"
        )

        src_lang = "Indonesian"
        tgt_lang = "Traditional Chinese"

        google_source = "id"
        google_target = "zh-TW"

        direction = "id->zh"

    # Traditional Chinese -> Indonesian
    elif (
        lang == "chinese"
        or lang.startswith("zh")
    ):

        pre = cleaned

        src_lang = "Traditional Chinese"
        tgt_lang = "Indonesian"

        google_source = "zh-TW"
        google_target = "id"

        direction = "zh->id"

    else:

        return {
            "error": "僅支援中文與印尼文"
        }

    # 依模型、翻譯方向、文字區分快取
    cache_key = (
        OPENAI_MODEL,
        direction,
        pre
    )

    cached = cache_get(cache_key)

    if cached is not None:

        result = cached

        meta = {
            "source": "cache",
            "model": OPENAI_MODEL
        }

        logger.info(
            "TRANSLATION_CACHE_HIT"
        )

    else:

        result = None
        meta = {}

        # First: OpenAI
        if openai_available():

            try:

                result = openai_translate(
                    src_lang,
                    tgt_lang,
                    pre
                )

                meta = {
                    "source": "openai",
                    "model": OPENAI_MODEL
                }

                cache_set(
                    cache_key,
                    result
                )

                logger.info(
                    "OPENAI_TRANSLATION_SUCCESS"
                )

            except Exception as error:

                logger.warning(
                    "OpenAI failed; trying Google: %s",
                    type(error).__name__
                )

        # Second: Google fallback
        if not result:

            try:

                result = google_translate(
                    google_source,
                    google_target,
                    pre
                )

                meta = {
                    "source": "google-fallback"
                }

                # Google 備援結果不放入 OpenAI 快取，
                # 避免恢復額度後一直沿用備援翻譯。
                logger.info(
                    "GOOGLE_FALLBACK_SUCCESS"
                )

            except Exception as error:

                logger.error(
                    "GOOGLE_FALLBACK_FAILED: %s",
                    type(error).__name__
                )

                return {
                    "error": (
                        "翻譯服務暫時無法使用，"
                        "請稍後再試。"
                    ),
                    "meta": {
                        "source": "unavailable"
                    }
                }

    # 不再強制改寫中文或補句號。
    # 直接保留翻譯引擎的自然句子。

    save_to_sheet_row(
        text,
        result,
        metadata={
            "direction": direction,
            "client": client_key,
            "meta": meta
        }
    )

    response = {
        "result": result,
        "lang": (
            "id"
            if direction == "id->zh"
            else "zh"
        ),
        "meta": meta
    }

    if direction == "id->zh":

        response["original_expanded"] = (
            expanded
        )

        response["preprocessed"] = pre

    else:

        response["polished_input"] = pre

    return response


# ============================================================
# 17. Flask endpoints
# ============================================================

@app.route("/", methods=["GET", "HEAD"])
def home():

    return "LINE Translator is running", 200


@app.route("/ping", methods=["GET", "HEAD"])
def ping():

    return "pong", 200


@app.route("/health", methods=["GET"])
def health():

    with _openai_state_lock:

        available_after = (
            _openai_unavailable_until
        )

        last_error = _openai_last_error

    return jsonify({
        "ok": True,
        "sheets": sheet is not None,
        "openai": _openai_client is not None,
        "model": OPENAI_MODEL,
        "openai_available": (
            _openai_client is not None
            and time.monotonic() >= available_after
        ),
        "openai_last_error": last_error
    }), 200


# ============================================================
# 18. API authentication
# ============================================================

TRANSLATE_API_KEY = os.getenv(
    "TRANSLATE_API_KEY"
)


def api_authorized():

    if not TRANSLATE_API_KEY:
        return False

    supplied = request.headers.get(
        "X-API-Key",
        ""
    )

    return hmac.compare_digest(
        supplied,
        TRANSLATE_API_KEY
    )


@app.route("/translate", methods=["POST"])
def translate_api():

    if not api_authorized():

        return jsonify({
            "error": "Unauthorized"
        }), 401

    data = request.get_json(
        silent=True
    )

    if not isinstance(data, dict):

        return jsonify({
            "error": "Invalid JSON"
        }), 400

    text = data.get("text", "")

    if not isinstance(text, str):

        return jsonify({
            "error": "Invalid text"
        }), 400

    client = (
        request.remote_addr
        or "anonymous"
    )

    result = process_message(
        text,
        client_key=client
    )

    return jsonify(result), (
        200 if "result" in result else 400
    )


@app.route("/history", methods=["GET"])
def history():

    if not api_authorized():

        return jsonify({
            "error": "Unauthorized"
        }), 401

    if sheet is None:

        return jsonify({
            "error": "Google Sheets 未配置"
        }), 400

    try:

        n = int(
            request.args.get("n", 20)
        )

        n = max(1, min(n, 100))

        rows = sheet.get_all_values()

        return jsonify({
            "rows": rows[-n:]
        }), 200

    except Exception:

        logger.exception(
            "Google Sheets history failed"
        )

        return jsonify({
            "error": "無法讀取試算表"
        }), 500


# ============================================================
# 19. LINE webhook
# ============================================================

@app.route("/callback", methods=["POST"])
def callback():

    if not handler or not line_bot_api:

        return "LINE not configured", 503

    signature = request.headers.get(
        "X-Line-Signature",
        ""
    )

    body = request.get_data(
        as_text=True
    )

    try:

        handler.handle(
            body,
            signature
        )

    except InvalidSignatureError:

        logger.warning(
            "LINE_INVALID_SIGNATURE"
        )

        return "Invalid signature", 400

    except Exception:

        logger.exception(
            "LINE_WEBHOOK_ERROR"
        )

        return "Webhook error", 500

    return "OK", 200


# ============================================================
# 20. LINE message handler
# ============================================================

if handler:

    @handler.add(
        MessageEvent,
        message=TextMessage
    )
    def handle_message(event):

        try:

            user_msg = event.message.text

            user_id = (
                getattr(
                    event.source,
                    "user_id",
                    None
                )
                or getattr(
                    event.source,
                    "group_id",
                    None
                )
                or "unknown"
            )

            client_key = (
                f"line:{user_id}"
            )

            result = process_message(
                user_msg,
                client_key=client_key
            )

            if "result" in result:

                # 不再顯示「🗣️ 翻譯結果：」
                reply_text = result["result"]

            else:

                reply_text = (
                    "⚠️ "
                    + result.get(
                        "error",
                        "處理失敗"
                    )
                )

            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=reply_text[:5000]
                )
            )

        except Exception:

            logger.exception(
                "LINE_MESSAGE_ERROR"
            )

            # 避免重複使用已消耗的 reply token。
            raise


# ============================================================
# 21. Run Flask
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv("PORT", "5000")
    )

    host = os.getenv(
        "HOST",
        "0.0.0.0"
    )

    logger.info(
        "Starting LINE Translator"
    )

    logger.info(
        "OPENAI_MODEL=%s",
        OPENAI_MODEL
    )

    logger.info(
        "OPENAI_ENABLED=%s",
        bool(_openai_client)
    )

    app.run(
        host=host,
        port=port,
        debug=(
            os.getenv("FLASK_DEBUG", "0") == "1"
        )
    )
