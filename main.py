import os
import re
import json
import logging
import time
from functools import lru_cache
from dotenv import load_dotenv

from flask import Flask, request, jsonify
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

from linebot import LineBotApi, WebhookHandler
from linebot.models import TextMessage, MessageEvent, TextSendMessage

from deep_translator import GoogleTranslator

# Optional Google Sheets
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GS_AVAILABLE = True
except ImportError:
    GS_AVAILABLE = False

# Optional OpenAI
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


# ============================================================
# 1. Load environment
# ============================================================

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO")
)

logger = logging.getLogger("line-translator")

app = Flask(__name__)


# ============================================================
# 2. LINE setup
# ============================================================

LINE_CHANNEL_ACCESS_TOKEN = os.getenv(
    "LINE_CHANNEL_ACCESS_TOKEN"
)

LINE_CHANNEL_SECRET = os.getenv(
    "LINE_CHANNEL_SECRET"
)

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    logger.warning("LINE token or secret not configured")

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

DetectorFactory.seed = 0


# ============================================================
# 3. Google Sheets
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
            creds_dict = json.loads(GS_JSON)

            creds = (
                ServiceAccountCredentials
                .from_json_keyfile_dict(
                    creds_dict,
                    scope
                )
            )

        except (json.JSONDecodeError, TypeError):
            creds = (
                ServiceAccountCredentials
                .from_json_keyfile_name(
                    GS_JSON,
                    scope
                )
            )

        gc = gspread.authorize(creds)

        sheet = gc.open_by_key(GS_KEY).sheet1

        logger.info("Google Sheets connected")

    except Exception as e:
        logger.exception(
            "Google Sheets initialization failed: %s",
            e
        )


# ============================================================
# 4. Indonesian abbreviation dictionary
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

    # 照護與生活
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

    # 聊天縮寫
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

    # 工作與學校
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

    # 其他
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
# 5. Chinese-Indonesian vocabulary
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
    "日期順序": "urutan tanggal"
}


# ============================================================
# 6. Chinese polishing
# ============================================================

chinese_polish_map = {
    "謝謝你": "謝謝。",
    "好的": "好。",
    "是啊姐姐": "好的姐姐。",
    "ok": "好。"
}


def polish_chinese(text):

    text = text.strip()

    for key, value in chinese_polish_map.items():
        text = text.replace(key, value)

    if text and not re.search(r'[。！？]$', text):
        text += "。"

    return text


# ============================================================
# 7. Save Google Sheets
# ============================================================

def save_to_sheet_row(original, translated, metadata=None):

    if sheet is None:
        return False

    row = [
        time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() + 8 * 3600)
        ),
        original,
        translated,
        json.dumps(
            metadata or {},
            ensure_ascii=False
        )
    ]

    for attempt in range(2):

        try:
            sheet.append_row(row)
            return True

        except Exception as e:
            logger.warning(
                "Google Sheets write failed: %s",
                type(e).__name__
            )

            if attempt == 0:
                time.sleep(0.5)

    return False


# ============================================================
# 8. Indonesian abbreviation processing
# ============================================================

# 只展開明確的縮寫，避免把正常印尼文全部替換成中文。
# 原本完整詞彙表仍保留，用於 AI 翻譯提示。

indonesian_normalization_map = {

    "sy": "saya",
    "kmu": "kamu",
    "km": "kamu",
    "dy": "dia",
    "dya": "dia",

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
    "dpn": "depan"
}


def expand_abbreviations(text):

    keys = sorted(
        indonesian_normalization_map,
        key=len,
        reverse=True
    )

    pattern = re.compile(
        r'\b('
        + '|'.join(re.escape(k) for k in keys)
        + r')\b',
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
# 9. Language detection
# ============================================================

def detect_language(text):

    text = text.strip()

    if not text:
        return None, text

    if re.search(r'[\u4e00-\u9fff]', text):
        return "chinese", text

    tokens = re.findall(
        r'[A-Za-z0-9]+',
        text.lower()
    )

    if any(
        token in indonesian_abbreviation_map
        for token in tokens
    ):
        return "indonesian", text

    if re.search(
        r'\b(saya|aku|makan|tidur|pagi|selamat|'
        r'kamu|besok|sudah|belum|nenek)\b',
        text.lower()
    ):
        return "indonesian", text

    try:

        detected = detect(text).lower()

        if detected in ("id", "in", "ms"):
            return "indonesian", text

        if detected.startswith("zh"):
            return "chinese", text

        return detected, text

    except LangDetectException:
        return None, text


# ============================================================
# 10. Indonesian time conversion
# ============================================================

def convert_jam_to_hhmm(text):

    def convert_time(match):

        hour = int(match.group(1))

        minute_text = match.group(2)

        period = (
            match.group(3) or ""
        ).lower()

        minute = 0

        if minute_text:

            if ":" in minute_text:
                minute = int(
                    minute_text.replace(":", "")
                )

            elif minute_text.startswith("."):
                value = minute_text[1:]

                if len(value) == 1:
                    minute = int(
                        round(float(minute_text) * 60)
                    )
                else:
                    minute = int(value)

            else:
                minute = int(minute_text)

        if hour > 23 or minute > 59:
            return match.group(0)

        if period in ("sore", "malam", "pm"):

            if hour < 12:
                hour += 12

        elif period in ("pagi", "am"):

            if hour == 12:
                hour = 0

        elif period == "siang":

            if 1 <= hour <= 6:
                hour += 12

        return f"{hour:02d}:{minute:02d}"

    pattern = re.compile(
        r'\b(?:jam|pukul)\s*'
        r'(\d{1,2})'
        r'([:.]\d{1,2})?'
        r'\s*(pagi|siang|sore|malam|am|pm)?\b',
        flags=re.IGNORECASE
    )

    return pattern.sub(convert_time, text)


def preprocess_text(text, lang):

    if lang == "indonesian":

        text = convert_jam_to_hhmm(text)

        text = expand_abbreviations(text)

    return text


# ============================================================
# 11. Google Translate fallback
# ============================================================

translator_id_zh = GoogleTranslator(
    source="id",
    target="zh-TW"
)

translator_zh_id = GoogleTranslator(
    source="zh-TW",
    target="id"
)


@lru_cache(maxsize=2048)
def translate_cached(source, target, text):

    # 只有成功的翻譯會被快取

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
# 12. OpenAI GPT-6 configuration
# ============================================================

OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-6-luna"
)
OPENAI_KEY = os.getenv(
    "OPENAI_API_KEY"
)

_openai_client = (
    OpenAI(
        api_key=OPENAI_KEY,
        timeout=15.0,
        max_retries=0
    )
    if OPENAI_KEY and OpenAI
    else None
)

# API 額度不足狀態
OPENAI_QUOTA_EXHAUSTED = False

# 額度不足後暫停 1 小時
OPENAI_QUOTA_RECHECK_SECONDS = 3600

OPENAI_NEXT_CHECK = 0


def openai_available():

    global OPENAI_QUOTA_EXHAUSTED
    global OPENAI_NEXT_CHECK

    if not _openai_client:
        return False

    if OPENAI_QUOTA_EXHAUSTED:

        if time.time() < OPENAI_NEXT_CHECK:
            return False

        OPENAI_QUOTA_EXHAUSTED = False

        logger.info(
            "OPENAI_QUOTA_RECHECK"
        )

    return True


def handle_openai_error(error):

    global OPENAI_QUOTA_EXHAUSTED
    global OPENAI_NEXT_CHECK

    error_text = str(error).lower()

    error_code = getattr(
        error,
        "code",
        None
    )

    if (
        error_code == "insufficient_quota"
        or "insufficient_quota" in error_text
        or "exceeded your current quota" in error_text
    ):

        OPENAI_QUOTA_EXHAUSTED = True

        OPENAI_NEXT_CHECK = (
            time.time()
            + OPENAI_QUOTA_RECHECK_SECONDS
        )

        logger.error(
            "OPENAI_CREDIT_EXHAUSTED"
        )

        return "quota_exhausted"

    if (
        "invalid_api_key" in error_text
        or "authentication" in error_text
    ):

        logger.error(
            "OPENAI_AUTHENTICATION_ERROR"
        )

        return "authentication_error"

    if (
        "model_not_found" in error_text
        or "does not exist" in error_text
    ):

        logger.error(
            "OPENAI_MODEL_NOT_AVAILABLE"
        )

        return "model_error"

    if "rate_limit" in error_text:

        logger.warning(
            "OPENAI_RATE_LIMIT"
        )

        return "rate_limit"

    logger.error(
        "OPENAI_API_ERROR: %s",
        type(error).__name__
    )

    return "api_error"


# ============================================================
# 13. Optimized glossary
# ============================================================

def _make_glossary_pairs(text, src_lang):

    lines = []

    if src_lang == "Indonesian":

        for key, value in indonesian_abbreviation_map.items():

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

                lines.append(
                    f"{key} -> {value}"
                )

    else:

        for key, value in chinese_indonesian_vocab.items():

            if key in text:

                lines.append(
                    f"{key} -> {value}"
                )

    return "\n".join(lines[:30])


# ============================================================
# 14. OpenAI translation
# ============================================================

@lru_cache(maxsize=2048)
def openai_translate_cached(
    src_lang,
    tgt_lang,
    text
):

    return openai_translate(
        src_lang,
        tgt_lang,
        text
    )


def openai_translate(
    src_lang,
    tgt_lang,
    text
):

    if not _openai_client:

        raise RuntimeError(
            "OpenAI client not configured"
        )

    glossary_hint = _make_glossary_pairs(
        text,
        src_lang
    )

    system_prompt = (
        "You are a professional translator between "
        "Indonesian and Traditional Chinese for "
        "elderly caregiving conversations.\n"
        "Translate accurately, naturally and politely.\n"
        "Understand Indonesian slang and abbreviations.\n"
        "Preserve names, numbers and HH:MM times.\n"
        "Do not add explanations.\n"
        "Return only the translated text."
    )

    if glossary_hint:

        system_prompt += (
            "\nRelevant vocabulary:\n"
            + glossary_hint
        )

    user_prompt = (
        f"Translate from {src_lang} "
        f"to {tgt_lang}:\n"
        f"{text}"
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

                max_completion_tokens=300
            )
        )

        translated = (
            response.choices[0].message.content or ""
        ).strip()

        if not translated:

            raise RuntimeError(
                "Empty translation from OpenAI"
            )

        return translated

    except Exception as e:

        handle_openai_error(e)

        raise


# ============================================================
# 15. Rate limiter
# ============================================================

RATE_LIMIT = int(
    os.getenv(
        "RATE_LIMIT_PER_MIN",
        "30"
    )
)

_rate_store = {}


def rate_limited(key):

    now = int(time.time())

    record = _rate_store.get(
        key,
        [0, now]
    )

    count, start = record

    if now - start >= 60:

        record = [0, now]

        count = 0

    if count >= RATE_LIMIT:
        return True

    record[0] += 1

    _rate_store[key] = record

    return False


# ============================================================
# 16. Main translation pipeline
# ============================================================

def process_message(
    text,
    client_key="anonymous"
):

    text = text.strip()

    if not text:

        return {
            "error": "請輸入有效文字"
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

        return {
            "error": "無法偵測語言"
        }

    lang = str(lang).lower()

    # 印尼文 -> 中文
    if (
        lang == "indonesian"
        or lang.startswith("id")
    ):

        expanded = expand_abbreviations(
            cleaned
        )

        pre = preprocess_text(
            expanded,
            "indonesian"
        )

        source = "Indonesian"

        target = "Traditional Chinese"

        google_source = "id"

        google_target = "zh-TW"

        direction = "id->zh"

    # 中文 -> 印尼文
    elif (
        lang == "chinese"
        or lang.startswith("zh")
    ):

        pre = polish_chinese(cleaned)

        source = "Traditional Chinese"

        target = "Indonesian"

        google_source = "zh-TW"

        google_target = "id"

        direction = "zh->id"

    else:

        return {
            "error": "僅支援中文與印尼文"
        }

    result = None

    meta = {}

    # 優先使用 OpenAI
    if openai_available():

        try:

            result = openai_translate_cached(
                source,
                target,
                pre
            )

            meta = {
                "source": "openai",
                "model": OPENAI_MODEL
            }

            logger.info(
                "OPENAI_TRANSLATION_SUCCESS"
            )

        except Exception as e:

            logger.warning(
                "OpenAI translation failed, "
                "switching to Google: %s",
                type(e).__name__
            )

    # OpenAI 失敗 -> Google
    if not result:

        try:

            result = translate_cached(
                google_source,
                google_target,
                pre
            )

            meta = {
                "source": "google-fallback"
            }

            logger.info(
                "GOOGLE_FALLBACK_SUCCESS"
            )

        except Exception as e:

            logger.error(
                "GOOGLE_FALLBACK_FAILED: %s",
                type(e).__name__
            )

            return {
                "error": (
                    "翻譯服務暫時無法使用，"
                    "請稍後再試。"
                ),
                "meta": {
                    "source": "unavailable",
                    "openai_quota_exhausted":
                        OPENAI_QUOTA_EXHAUSTED
                }
            }

    if direction == "id->zh":

        result = polish_chinese(result)

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
            expand_abbreviations(cleaned)
        )

        response["preprocessed"] = pre

    else:

        response["polished_input"] = pre

    return response


# ============================================================
# 17. Flask endpoints
# ============================================================

@app.route("/ping", methods=["GET", "HEAD"])
def ping():

    return "pong", 200


@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "sheets": sheet is not None,
        "openai": _openai_client is not None,
        "model": OPENAI_MODEL,
        "openai_quota_exhausted":
            OPENAI_QUOTA_EXHAUSTED
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

    import hmac

    return hmac.compare_digest(
        supplied,
        TRANSLATE_API_KEY
    )


@app.route(
    "/translate",
    methods=["POST"]
)
def translate_api():

    if not api_authorized():

        return jsonify({
            "error": "Unauthorized"
        }), 401

    data = request.get_json(
        silent=True
    ) or {}

    text = data.get(
        "text",
        ""
    )

    if not isinstance(text, str):

        return jsonify({
            "error": "Invalid text"
        }), 400

    client = request.remote_addr or "anonymous"

    result = process_message(
        text,
        client_key=client
    )

    return jsonify(result), (
        200
        if "result" in result
        else 400
    )


@app.route(
    "/history",
    methods=["GET"]
)
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
            request.args.get(
                "n",
                20
            )
        )

        n = max(
            1,
            min(n, 100)
        )

        rows = sheet.get_all_values()[-n:]

        return jsonify({
            "rows": rows
        }), 200

    except Exception as e:

        logger.exception(
            "History error: %s",
            e
        )

        return jsonify({
            "error": "無法讀取試算表"
        }), 500


# ============================================================
# 19. LINE Webhook
# ============================================================

@app.route(
    "/callback",
    methods=["POST"]
)
def callback():

    signature = request.headers.get(
        "X-Line-Signature",
        ""
    )

    body = request.get_data(
        as_text=True
    )

    if not handler or not line_bot_api:

        return "LINE not configured", 503

    try:

        handler.handle(
            body,
            signature
        )

    except Exception as e:

        logger.exception(
            "LINE webhook error: %s",
            e
        )

        return "Webhook error", 400

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

            client_key = f"line:{user_id}"

            result = process_message(
                user_msg,
                client_key=client_key
            )

            if "result" in result:

                reply_text = (
                    "🗣️ 翻譯結果："
                    + result["result"]
                )

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
                    text=reply_text
                )
            )

        except Exception as e:

            logger.exception(
                "LINE message error: %s",
                e
            )

            try:

                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text="⚠️ 內部錯誤，請稍後再試。"
                    )
                )

            except Exception:
                pass


# ============================================================
# 21. Run Flask
# ============================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            5000
        )
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
            os.getenv(
                "FLASK_DEBUG",
                "0"
            ) == "1"
        )
    )
