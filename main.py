import os
import re
import json
import string
import logging
import time
from functools import lru_cache
from io import StringIO
from dotenv import load_dotenv

from flask import Flask, request, jsonify, abort
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException

from linebot import LineBotApi, WebhookHandler, WebhookParser
from linebot.models import TextMessage, MessageEvent, TextSendMessage

from deep_translator import GoogleTranslator

# Optional Google Sheets
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GS_AVAILABLE = True
except Exception:
    GS_AVAILABLE = False

# Optional OpenAI
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# --- Load .env ---
load_dotenv()

# --- Logging ---
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("line-translator")

# --- Flask app ---
app = Flask(__name__)

# --- LINE setup ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    logger.warning("LINE token/secret not set. Set LINE_CHANNEL_ACCESS_TOKEN and LINE_CHANNEL_SECRET in env.")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else None
handler = WebhookHandler(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None
parser = WebhookParser(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else None

# --- langdetect deterministic seed ---
DetectorFactory.seed = 0

# --- Google Sheets (optional) ---
sheet = None
GS_KEY = os.getenv("GOOGLE_SHEET_KEY")
GS_JSON = os.getenv("GOOGLE_SHEET_JSON")
if GS_AVAILABLE and GS_KEY and GS_JSON:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    try:
        try:
            creds_dict = json.loads(GS_JSON)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            logger.info("Loaded Google credentials from JSON content.")
        except Exception:
            creds = ServiceAccountCredentials.from_json_keyfile_name(GS_JSON, scope)
            logger.info("Loaded Google credentials from file.")
        gc = gspread.authorize(creds)
        sheet = gc.open_by_key(GS_KEY).sheet1
        logger.info("Google Sheets connected.")
    except Exception as e:
        logger.exception("Google Sheets init failed: %s", e)
else:
    if not GS_AVAILABLE:
        logger.info("gspread/oauth2client not available; skipping Google Sheets init.")

# --- Dictionaries (kept from your original) ---
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
    "雨停": "hujan berh停",
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

# 中文潤飾對照（可擴充）
chinese_polish_map = {
    "謝謝你": "謝謝。",
    "好的": "好。",
    "是啊姐姐": "好的姐姐。",
    "ok": "好。"
}

# --- Utility functions ---
def save_to_sheet_row(original, translated, metadata=None):
    """Append to Google Sheet with retry (synchronous)."""
    if not sheet:
        return False
    row = [time.strftime("%Y-%m-%d %H:%M:%S"), original, translated, json.dumps(metadata or {}, ensure_ascii=False)]
    for attempt in range(2):
        try:
            sheet.append_row(row)
            return True
        except Exception as e:
            logger.exception("Write to sheet failed (attempt %d): %s", attempt+1, e)
            time.sleep(0.5)
    return False

def expand_abbreviations(text: str) -> str:
    # replace whole-word tokens, longer keys first
    keys_sorted = sorted(indonesian_abbreviation_map.keys(), key=lambda k: -len(k))
    pattern = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keys_sorted) + r')\b', flags=re.IGNORECASE)
    return pattern.sub(lambda m: indonesian_abbreviation_map.get(m.group(0).lower(), m.group(0)), text)

def polish_chinese(text: str) -> str:
    for k, v in chinese_polish_map.items():
        text = text.replace(k, v)
    if not re.search(r'[。！？]$', text.strip()):
        text = text.strip() + "。"
    return text

# 🔧 改良版語言偵測：加入「在縮寫字典裡就當印尼文」
def detect_language(text: str):
    """偵測語言：先看中文，其次看縮寫字典 / 關鍵詞，最後才用 langdetect。"""
    t = text.strip()
    if not t:
        return None, text

    # 1) 中文：只要有一個中文字就當中文
    if re.search(r'[\u4e00-\u9fff]', t):
        return 'chinese', text

    # 2) 先抓裡面的英文單字，看有沒有在縮寫字典裡（包含 lya, ce 等）
    tokens = re.findall(r'[A-Za-z]+', t.lower())
    if any(tok in indonesian_abbreviation_map for tok in tokens):
        return 'indonesian', text

    # 3) 原本就有的印尼關鍵詞啟發式
    if re.search(r'\b(saya|aku|makan|tidur|pagi|selamat|terima kasih|kamu|kmu|mkn|udh)\b', t.lower()):
        return 'indonesian', text

    # 4) 最後才交給 langdetect，並做簡單 mapping
    try:
        detected = detect(t)  # 例如 'id', 'in', 'ms', 'zh-cn', 'en'...
        d_lower = detected.lower()
        if d_lower in ('id', 'in', 'ms'):
            return 'indonesian', text
        if d_lower.startswith('zh'):
            return 'chinese', text
        return detected, text
    except LangDetectException:
        return None, text

def convert_jam_to_hhmm(text: str) -> str:
    """
    Converts 'jam 3 sore', 'jam9', 'jam 9.5', 'jam 9:30' -> HH:MM.
    Keeps simple heuristics for 'pagi/siang/sore/malam'.
    """
    def to_24(h, m, period):
        h = int(h) % 24
        m = int(m)
        if period:
            p = period.lower()
            if p in ('sore', 'malam', 'pm', 'p.m.'):
                if h < 12:
                    h += 12
            if p in ('pagi','am','a.m.') and h == 12:
                h = 0
        return f"{h:02d}:{m:02d}"

    # jam 3 sore
    pattern_period = re.compile(
        r'\bjam\s*(\d{1,2})(?:[:.,](\d{1,2}|\d*\.\d+))?\s*(pagi|siang|sore|malam|am|pm|a\.m\.|p\.m\.)\b',
        flags=re.IGNORECASE
    )
    def repl_period(m):
        h = int(m.group(1))
        minpart = m.group(2)
        period = m.group(3)
        minute = 0
        if minpart:
            if '.' in minpart:
                minute = int(round(float(minpart) * 60))
            else:
                minute = int(minpart)
        return to_24(h, minute, period)
    text = pattern_period.sub(repl_period, text)

    # jam 9.5 or jam 9.25
    pattern_decimal = re.compile(r'\bjam\s*(\d{1,2})\s*[.,]?\s*(\d*\.\d+)\b', flags=re.IGNORECASE)
    def repl_decimal(m):
        h = int(m.group(1))
        dec = float(m.group(2))
        minute = int(round(dec * 60))
        return to_24(h, minute, None)
    text = pattern_decimal.sub(repl_decimal, text)

    # jam 9:30 or jam9 or jam 9
    pattern_basic = re.compile(r'\bjam\s*(\d{1,2})(?:[:.,](\d{1,2}))?\b', flags=re.IGNORECASE)
    def repl_basic(m):
        h = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) and m.group(2).isdigit() else 0
        return to_24(h, minute, None)
    text = pattern_basic.sub(repl_basic, text)
    return text

def preprocess_text(text: str, lang: str) -> str:
    if lang == 'indonesian':
        text = re.sub(r'(\d{1,2})點(\d{1,2})', r'\1:\2', text)
        text = re.sub(r'(\d{1,2})點\b', r'\1:00', text)
        text = convert_jam_to_hhmm(text)
        text = expand_abbreviations(text)
    return text

# --- Translator singletons & cache (Google, 作為 fallback) ---
translator_id_zh = GoogleTranslator(source="id", target="zh-TW")
translator_zh_id = GoogleTranslator(source="zh-TW", target="id")

@lru_cache(maxsize=2048)
def translate_cached(source, target, text):
    """Google 翻譯（cache）"""
    try:
        if source.startswith('id'):
            return translator_id_zh.translate(text)
        if source.startswith('zh'):
            return translator_zh_id.translate(text)
        return GoogleTranslator(source=source, target=target).translate(text)
    except Exception as e:
        logger.exception("Translation engine error (Google): %s", e)
        return "⚠️ 翻譯失敗"

# --- OpenAI 翻譯設定 ---
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
_openai_client = OpenAI(api_key=OPENAI_KEY) if (OPENAI_KEY and OpenAI) else None

def _make_glossary_pairs():
    """把縮寫/詞彙對照整理進 prompt，避免太長。"""
    N = 80
    id_abbr_items = list(indonesian_abbreviation_map.items())[:N]
    zh_id_items = list(chinese_indonesian_vocab.items())[:N]

    lines = []
    if id_abbr_items:
        lines.append("• Indonesian chat abbreviations:")
        for k, v in id_abbr_items:
            lines.append(f"  - {k} -> {v}")
    if zh_id_items:
        lines.append("• Chinese→Indonesian domain terms:")
        for k, v in zh_id_items:
            lines.append(f"  - {k} -> {v}")
    return "\n".join(lines)

def _extract_text_from_response(resp) -> str:
    """從 Responses API 回傳物件中抓出第一段文字。"""
    try:
        output_list = getattr(resp, "output", None)
        if not output_list:
            return ""
        first = output_list[0]
        content = getattr(first, "content", None)
        if not content:
            return ""
        c0 = content[0]
        text_obj = getattr(c0, "text", None)
        if text_obj and hasattr(text_obj, "value"):
            return (text_obj.value or "").strip()
        return ""
    except Exception:
        return ""

def openai_translate(src_lang, tgt_lang, text: str):
    """
    直接透過 OpenAI 做翻譯（不用 Google 當 baseline）。
    出錯時丟例外，外層會負責 fallback。
    """
    if not _openai_client:
        raise RuntimeError("OpenAI client not configured")

    glossary_hint = _make_glossary_pairs()
    prompt = (
        "You are a professional translator between Indonesian and Traditional Chinese "
        "for elderly caregiving daily conversation.\n\n"
        f"Source language: {src_lang}\n"
        f"Target language: {tgt_lang}\n\n"
        "Important domain terms and chat abbreviations:\n"
        f"{glossary_hint}\n\n"
        "Instructions:\n"
        "1) 保留人名、專有名詞與數字。\n"
        "2) 若文字中已有 HH:MM（24 小時制）時間格式，請完整保留，不要改動。\n"
        "3) 口吻自然、簡單、禮貌，符合日常對話（照護情境）。\n"
        "4) 不要加解釋或註解，只輸出目標語言翻譯句子。\n"
        "5) 如果原文很口語或有縮寫（例如印尼聊天用語），請先理解後，用清楚自然的目標語言重寫。\n\n"
        "Translate the following text:\n"
        f"<<<{text}>>>"
    )

    resp = _openai_client.responses.create(
        model=OPENAI_MODEL,
        input=prompt,
    )
    translated = _extract_text_from_response(resp)
    if not translated:
        raise RuntimeError("Empty translation from OpenAI")
    return translated.strip()

# --- Simple rate limiter (in-memory) ---
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))  # messages per minute per token/ip
_rate_store = {}  # key -> [count, window_start_ts]

def rate_limited(key):
    now = int(time.time())
    window = 60
    record = _rate_store.get(key, [0, now])
    count, start = record
    if now - start >= window:
        record = [0, now]
        count, start = record
    if count >= RATE_LIMIT:
        return True
    record[0] += 1
    _rate_store[key] = record
    return False

# --- Main processing pipeline ---
def process_message(text: str, client_key: str = "anonymous") -> dict:
    text = text.strip()
    if not text:
        return {"error": "請輸入有效文字"}

    if rate_limited(client_key):
        return {"error": f"速率限制：每 60 秒最多 {RATE_LIMIT} 次"}

    lang, cleaned = detect_language(text)
    logger.info("process_message: detected=%s text=%s", lang, cleaned)

    if not lang:
        return {"error": "無法偵測語言"}

    lang = str(lang).lower()

    # 印尼文 -> 中文
    if lang == 'indonesian' or lang.startswith('id'):
        expanded = expand_abbreviations(cleaned)
        pre = preprocess_text(expanded, 'indonesian')

        meta = {}
        result = None

        # 優先使用 OpenAI
        try:
            if _openai_client:
                result = openai_translate("Indonesian", "Traditional Chinese", pre)
                result = polish_chinese(result)
                meta = {"source": "openai", "model": OPENAI_MODEL}
        except Exception as e:
            logger.exception("OpenAI translate error (id->zh), falling back: %s", e)

        # 若 OpenAI 失敗則 fallback Google
        if not result:
            base = translate_cached('id', 'zh-TW', pre)
            result = polish_chinese(base)
            meta = {"source": "google-fallback"}

        save_to_sheet_row(text, result, metadata={"direction": "id->zh", "client": client_key, "meta": meta})
        return {
            "result": result,
            "original_expanded": expanded,
            "preprocessed": pre,
            "lang": "id",
            "meta": meta,
        }

    # 中文 -> 印尼文
    elif lang == 'chinese' or lang.startswith('zh'):
        polished_in = polish_chinese(cleaned)

        meta = {}
        result = None

        try:
            if _openai_client:
                result = openai_translate("Traditional Chinese", "Indonesian", polished_in)
                meta = {"source": "openai", "model": OPENAI_MODEL}
        except Exception as e:
            logger.exception("OpenAI translate error (zh->id), falling back: %s", e)

        if not result:
            base = translate_cached('zh-TW', 'id', polished_in)
            result = base
            meta = {"source": "google-fallback"}

        save_to_sheet_row(text, result, metadata={"direction": "zh->id", "client": client_key, "meta": meta})
        return {
            "result": result,
            "polished_input": polished_in,
            "lang": "zh",
            "meta": meta,
        }

    else:
        return {"error": "僅支援中文與印尼文"}

# --- Flask endpoints ---
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200

@app.route("/health", methods=["GET"])
def health():
    ok = {"ok": True, "sheets": bool(sheet), "openai": bool(_openai_client)}
    return jsonify(ok), 200

@app.route("/translate", methods=["POST"])
def translate_api():
    data = request.get_json(force=True)
    text = data.get("text", "")
    client = data.get("client", request.remote_addr or "anonymous")
    res = process_message(text, client_key=client)
    return jsonify(res), 200 if "result" in res else 400

@app.route("/history", methods=["GET"])
def history():
    # basic: if Google Sheet configured, return last N rows (limited)
    if not sheet:
        return jsonify({"error": "Google Sheets 未配置"}), 400
    n = int(request.args.get("n", 20))
    try:
        rows = sheet.get_all_values()[-n:]
        return jsonify({"rows": rows}), 200
    except Exception as e:
        logger.exception("Failed to fetch sheet rows: %s", e)
        return jsonify({"error": "無法讀取試算表"}), 500

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    if not handler or not line_bot_api:
        logger.warning("LINE not configured; ignoring callback.")
        return "LINE not configured", 503
    try:
        handler.handle(body, signature)
    except Exception as e:
        logger.exception("LINE webhook handle error: %s", e)
        return "OK", 200
    return "OK", 200

if handler:
    @handler.add(MessageEvent, message=TextMessage)
    def handle_message(event):
        try:
            user_msg = event.message.text
            user_id = getattr(event.source, "user_id", None) or getattr(event.source, "group_id", None) or "unknown"
            client_key = f"line:{user_id}"
            res = process_message(user_msg, client_key=client_key)
            if "result" in res:
                reply_text = f"🗣️ 翻譯結果：{res['result']}"
            else:
                reply_text = f"⚠️ {res.get('error', '處理失敗')}"
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        except Exception as e:
            logger.exception("Error in handle_message: %s", e)
            try:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 內部錯誤"))
            except Exception:
                pass

# --- Run ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info(
        "Starting Flask app on %s:%d (OPENAI_MODEL=%s, openai_enabled=%s)",
        host, port, OPENAI_MODEL, bool(_openai_client)
    )
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
