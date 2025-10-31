# app.py
import os
import re
import json
import string
import logging
from io import StringIO
from dotenv import load_dotenv

from flask import Flask, request
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

from linebot import LineBotApi, WebhookHandler
from linebot.models import TextMessage, MessageEvent

from deep_translator import GoogleTranslator

import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- Load .env ---
load_dotenv()

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Flask & LINE Setup ---
app = Flask(__name__)
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    logger.warning("LINE channel token/secret not set. Make sure LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET are set in .env")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

# --- Langdetect seed for determinism ---
DetectorFactory.seed = 0

# --- Google Sheets Setup (supports JSON content or file path) ---
sheet = None
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
GOOGLE_SHEET_JSON = os.getenv("GOOGLE_SHEET_JSON")

if GOOGLE_SHEET_KEY and GOOGLE_SHEET_JSON:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        try:
            # first try parse as JSON content
            creds_data = json.loads(GOOGLE_SHEET_JSON)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_data, scope)
            logger.info("Loaded Google credentials from JSON content in env.")
        except json.JSONDecodeError:
            # fallback to treat as file path
            creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_SHEET_JSON, scope)
            logger.info("Loaded Google credentials from file path.")
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GOOGLE_SHEET_KEY).sheet1
        logger.info("✅ Google Sheets connected.")
    except Exception as e:
        logger.exception("Failed to initialize Google Sheets: %s", e)

# --- DICTIONARIES (you provided these; included here) ---
indonesian_abbreviation_map = {
    # 👨‍👩‍👧‍👦 人稱與稱謂
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

    # 🕐 時間與日期
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

    # 🍱 照護與生活動作
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

    # 💬 聊天口語縮寫
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
    "lya": "ya",
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

    # 🏠 物件與地點
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

    # 🧾 工作、單位與學校
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

    # 🧠 其他補充
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
    "外箱": "kotak luar",
    "粉紅色": "merah muda",
    "下面": "di bawah",
    "還沒": "belum",
    "遵循": "mengikuti",
    "日期順序": "urutan tanggal",
}

# 中文潤飾對照（可擴充）
chinese_polish_map = {
    "謝謝你": "謝謝。",
    "好的": "好。",
    "ok": "好。"
}

# --- Utility functions ---

def save_to_sheet(original, translated):
    if sheet:
        try:
            sheet.append_row([original, translated])
        except Exception as e:
            logger.exception("Error writing to Google Sheets: %s", e)

def expand_abbreviations(text: str) -> str:
    # 先做 word-boundary 取代（忽略大小寫）
    # 為避免將 longer tokens 被 shorter tokens 擋掉，排序長度遞減替換
    keys_sorted = sorted(indonesian_abbreviation_map.keys(), key=lambda k: -len(k))
    for abbr in keys_sorted:
        full = indonesian_abbreviation_map[abbr]
        text = re.sub(r'\b' + re.escape(abbr) + r'\b', full, text, flags=re.IGNORECASE)
    return text

def polish_chinese(text: str) -> str:
    for k, v in chinese_polish_map.items():
        text = text.replace(k, v)
    if not re.search(r'[。！？]$', text):
        text = text.strip() + "。"
    return text

def detect_language(text: str):
    # 用中文字元與拉丁字元比例來優先判斷
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    latin_chars = sum(1 for c in text if c.isalpha() and c.lower() in string.ascii_lowercase)
    logger.debug("chinese_chars=%d latin_chars=%d", chinese_chars, latin_chars)

    if chinese_chars > latin_chars:
        return 'chinese', text
    elif latin_chars > chinese_chars:
        return 'indonesian', text
    else:
        # fallback to langdetect
        try:
            detected = detect(text)
            return detected, text
        except LangDetectException:
            return None, text

def convert_jam_to_hhmm(text: str) -> str:
    """
    Convert patterns like:
      - jam 9, jam9, jam 9.5, jam 9:30, jam 12.35
      - jam 3 sore / jam 6 pagi / jam 7 malam
    into consistent HH:MM 24-hour format or preserve readable '下午9:00' depending on strategy.
    We'll output HH:MM (24h) for clarity (e.g., jam 3 sore -> 15:00).
    """
    def hour_min_to_24(hour_int: int, minute_int: int, period: str = None):
        # period could be 'pagi', 'siang', 'sore', 'malam', 'a.m.', 'p.m.' etc.
        if period:
            p = period.lower()
            if p in ('sore', 'malam', 'p.m.', 'pm'):
                if hour_int < 12:
                    hour_int = hour_int + 12
            if p in ('pagi', 'a.m.', 'am'):
                if hour_int == 12:
                    hour_int = 0
            # 'siang'一般視為12:00-15:00，保持原本數字（若需要進一步處理可擴充）
        # bound hour
        hour_int = hour_int % 24
        return f"{hour_int:02d}:{minute_int:02d}"

    # 先處理帶 period 的形式： jam 3 sore / jam 3 pagi
    pattern_period = re.compile(r'\bjam\s*(\d{1,2})(?:[:.,]\s*(\d{1,2}|\d{1,2}\.\d+))?\s*(pagi|siang|sore|malam|a\.m\.|p\.m\.|am|pm)\b', flags=re.IGNORECASE)
    def repl_period(m):
        h = int(m.group(1))
        min_part = m.group(2)
        period = m.group(3)
        minute = 0
        if min_part:
            if '.' in min_part:
                try:
                    minute = round(float("0." + min_part.split('.')[-1]) * 60)
                except:
                    minute = int(float(min_part))
            else:
                minute = int(min_part)
        return hour_min_to_24(h, minute, period)
    text = pattern_period.sub(repl_period, text)

    # 處理含小數的 like jam 9.5 or jam 9.25 (9.5 -> 9:30)
    pattern_decimal = re.compile(r'\bjam\s*(\d{1,2})\s*[:.,]?\s*(\d*\.\d+)\b', flags=re.IGNORECASE)
    def repl_decimal(m):
        h = int(m.group(1))
        dec = float(m.group(2))
        minute = int(round(dec * 60))
        return hour_min_to_24(h, minute)
    text = pattern_decimal.sub(repl_decimal, text)

    # 處理標準 jam H[:MM]
    pattern_basic = re.compile(r'\bjam\s*(\d{1,2})(?:[:.,]\s*(\d{1,2}))?\b', flags=re.IGNORECASE)
    def repl_basic(m):
        h = int(m.group(1))
        min_part = m.group(2)
        minute = int(min_part) if min_part and min_part.isdigit() else 0
        return hour_min_to_24(h, minute)
    text = pattern_basic.sub(repl_basic, text)

    return text

def preprocess_text(text: str, lang: str) -> str:
    if lang == 'indonesian':
        # expand some chinese-style time like "12點30" -> "12:30" if present in imported text
        text = re.sub(r'(\d{1,2})點(\d{1,2})', r'\1:\2', text)
        text = re.sub(r'(\d{1,2})點', r'\1:00', text)
        # normalize "jam ..." to HH:MM 24h
        text = convert_jam_to_hhmm(text)
    return text

def translate_text(text: str, source: str, target: str) -> str:
    try:
        return GoogleTranslator(source=source, target=target).translate(text)
    except Exception as e:
        logger.exception("Translation error: %s", e)
        return "⚠️ 翻譯失敗"

# --- Main processing pipeline ---

def process_message(text: str) -> str:
    text = text.strip()
    if not text or all(ch in string.punctuation for ch in text):
        return "⚠️ 請輸入有效文字"

    lang, cleaned = detect_language(text)
    logger.info("Detected language: %s | Text: %s", lang, cleaned)

    if not lang:
        return "⚠️ 無法偵測語言"

    # handle Indonesian input
    if lang == 'indonesian' or lang.startswith('id'):
        # expand abbreviations then preprocess (time convert etc)
        expanded = expand_abbreviations(cleaned.lower())
        preprocessed = preprocess_text(expanded, 'indonesian')
        translated = translate_text(preprocessed, source='id', target='zh-TW')
        polished = polish_chinese(translated)
        save_to_sheet(text, polished)
        return f"🗣️ 翻譯結果：{polished}"

    # handle Chinese input
    elif lang == 'chinese' or lang.startswith('zh'):
        # polish Chinese then translate to Indonesian
        polished_input = polish_chinese(cleaned)
        # optionally translate dictionary replacements first for short phrases (we keep general translate)
        translated = translate_text(polished_input, source='zh-TW', target='id')
        save_to_sheet(text, translated)
        return f"🗣️ 翻譯結果：{translated}"

    # fallback: if langdetect gives 'en' or others, try translate to both?
    else:
        # we'll only handle chinese and indonesian explicitly
        return "⚠️ 僅支援中文與印尼文"

# --- LINE Webhook handlers ---
@app.route("/callback", methods=["POST"])
def callback():
    # signature may not exist in testing env
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    if handler:
        try:
            handler.handle(body, signature)
        except Exception as e:
            logger.exception("Error handling LINE webhook: %s", e)
            # Don't disclose internals to LINE
    else:
        logger.warning("LINE handler not configured.")
    return "OK", 200

@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

if handler:
    @handler.add(MessageEvent)
    def handle_message(event):
        try:
            # only care text messages
            from linebot.models import TextMessage as LineTextMessage
            if isinstance(event.message, LineTextMessage):
                user_message = event.message.text
                reply = process_message(user_message)
                if line_bot_api:
                    line_bot_api.reply_message(event.reply_token, TextMessage(text=reply))
                else:
                    logger.warning("LINE API not configured; cannot reply.")
        except Exception as e:
            logger.exception("Error in handle_message: %s", e)

# --- Run app ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info("Starting app on %s:%d", host, port)
    app.run(host=host, port=port)
