import os
import re
import json
import string
import logging
import time
from functools import lru_cache, wraps
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

# --- Dictionaries (你可以再把原本更完整的 map 貼進來擴充) ---
indonesian_abbreviation_map = {
    # 👨‍👩‍👧‍👦 人稱與稱謂
    "ad": "弟弟",
    "adik": "弟弟",
    "kak": "哥哥",
    "ce": "姐姐",
    "cece": "姐姐",
    "ibu": "媽媽",
    "ayah": "爸爸",
    "nenek": "奶奶",
    "tmn": "朋友",
    "sy": "我",
    "aku": "我",
    "saya": "我",
    "kmu": "你",
    "km": "你",
    "anda": "您",
    "dia": "他/她",
    "dy": "他/她",

    # 🕐 時間與日期
    "pagi": "早上",
    "siang": "中午",
    "sore": "下午",
    "malam": "晚上",
    "bsk": "明天",
    "besok": "明天",
    "kmrn": "昨天",
    "kemarin": "昨天",
    "udh": "已經",
    "sudah": "已經",
    "blm": "還沒",
    "belum": "還沒",

    # 🍱 生活動作
    "makan": "吃",
    "mkn": "吃",
    "minum": "喝",
    "mandi": "洗澡",
    "tidur": "睡覺",
    "bangun": "起床",
    "bantu": "幫忙",
    "bersih": "打掃",
    "cuci": "洗",
    "masak": "煮",
    "lihat": "看見",

    # 💬 聊天縮寫
    "aj": "aja",
    "aja": "就好",
    "deh": "就這樣吧",
    "jg": "juga",
    "jd": "jadi",
    "kl": "kalau",
    "klo": "kalau",
    "krn": "karena",
    "iya": "ya",
    "yaudah": "好啦",
    "ngga": "不",
    "ga": "不",
    "gk": "不",
    "gt": "gitu",
    "gtu": "gitu",
    "gtw": "不知道",
    "sm": "sama",
    "trs": "terus",
    "skrg": "現在",
    "dr": "醫生",
    "dok": "醫生",
    "tp": "tapi",
    "tpi": "tapi",
    "ok": "好",
    "okee": "好喔",
    "okey": "好喔",
    "sip": "好",
    "mantap": "太棒了",
    "btw": "順便說一下",

    # 其他常見
    "bkn": "不是",
    "bsa": "bisa",
    "bisa": "可以",
    "gpp": "沒關係",
    "syg": "親愛的",
    "thx": "謝謝",
    "makasih": "謝謝",
    "terima kasih": "謝謝",
    "mantul": "很棒",
}

chinese_indonesian_vocab = {
    "奶奶": "nenek",
    "白天": "siang hari",
    "有": "ada",
    "排便": "buang air besar",
}

# 中文潤飾對照（可擴充）
chinese_polish_map = {
    "謝謝你": "謝謝。",
    "好的": "好。",
    "是啊姐姐": "好的姐姐。",
    "ok": "好。",
}

# --- Utility functions ---
def save_to_sheet_row(original, translated, metadata=None):
    """Append to Google Sheet with retry (synchronous)."""
    if not sheet:
        return False
    row = [time.strftime("%Y-%m-%d %H:%M:%S"), original, translated, json.dumps(metadata or {})]
    for attempt in range(2):
        try:
            sheet.append_row(row)
            return True
        except Exception as e:
            logger.exception("Write to sheet failed (attempt %d): %s", attempt + 1, e)
            time.sleep(0.5)
    return False


def expand_abbreviations(text):
    # replace whole-word tokens, longer keys first
    keys_sorted = sorted(indonesian_abbreviation_map.keys(), key=lambda k: -len(k))
    pattern = re.compile(r'\b(' + '|'.join(re.escape(k) for k in keys_sorted) + r')\b', flags=re.IGNORECASE)
    return pattern.sub(lambda m: indonesian_abbreviation_map.get(m.group(0).lower(), m.group(0)), text)


def polish_chinese(text):
    for k, v in chinese_polish_map.items():
        text = text.replace(k, v)
    if not re.search(r'[。！？]$', text.strip()):
        text = text.strip() + "。"
    return text


def convert_jam_to_hhmm(text):
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
            if p in ('pagi', 'am', 'a.m.') and h == 12:
                h = 0
        return "%02d:%02d" % (h, m)

    # jam 3 sore
    pattern_period = re.compile(
        r'\bjam\s*(\d{1,2})(?:[:.,](\d{1,2}|\d*\.\d+))?\s*(pagi|siang|sore|malam|am|pm|a\.m\.|p\.m\.)\b',
        flags=re.IGNORECASE,
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


def preprocess_text(text, lang):
    if lang == 'indonesian':
        text = re.sub(r'(\d{1,2})點(\d{1,2})', r'\1:\2', text)
        text = re.sub(r'(\d{1,2})點\b', r'\1:00', text)
        text = convert_jam_to_hhmm(text)
        text = expand_abbreviations(text)
    return text

# --- Improved language detection ---
_CJK_RE = re.compile(r'[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF\u2F800-\u2FA1F]')
_ID_HINTS = re.compile(
    r'\b(saya|aku|anda|kamu|kmu|makan|minum|tidur|pagi|siang|sore|malam|terima kasih|makasih|skrg|udh|blm|gk|ngga|krn|kl|jam)\b'
)

def normalize_lang_code(code):
    """Normalize language codes into 'zh', 'id', or others."""
    if not code:
        return None
    code = code.lower()
    if code.startswith('zh') or code in {'cmn', 'zho'}:
        return 'zh'
    if code in {'id', 'in', 'ms'}:
        return 'id'
    return code


def detect_language(text):
    """Heuristic language detection: Chinese vs Indonesian vs others."""
    t = text.strip()
    if not t:
        return None, text

    # 1) Chinese character ratio
    han = len(_CJK_RE.findall(t))
    if han >= 2 or (han >= 1 and len(t) <= 6):
        return 'zh', text

    # 2) Indonesian hints
    if _ID_HINTS.search(t.lower()):
        return 'id', text

    # 3) langdetect fallback
    try:
        raw = detect(t)
        norm = normalize_lang_code(raw)
        return norm, text
    except LangDetectException:
        return None, text

# --- Translator singletons & cache ---
translator_id_zh = GoogleTranslator(source="id", target="zh-TW")
translator_zh_id = GoogleTranslator(source="zh-TW", target="id")


@lru_cache(maxsize=2048)
def translate_cached(source, target, text):
    """Cache by exact parameters (source,target,text)."""
    try:
        if source.startswith('id'):
            return translator_id_zh.translate(text)
        if source.startswith('zh'):
            return translator_zh_id.translate(text)
        # fallback
        return GoogleTranslator(source=source, target=target).translate(text)
    except Exception as e:
        logger.exception("Translation engine error: %s", e)
        return "⚠️ 翻譯失敗"


# --- Simple rate limiter (in-memory) ---
RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MIN", "30"))  # messages per minute per token/ip
_rate_store = {}  # key -> [count, window_start_ts]


def rate_limited(key):
    now = int(time.time())
    window = 60
    record = _rate_store.get(key, [0, now])
    count, start = record
    if now - start >= window:
        # reset
        record = [0, now]
        count, start = record
    if count >= RATE_LIMIT:
        return True
    record[0] += 1
    _rate_store[key] = record
    return False


# --- Main processing pipeline ---
def process_message(text, client_key="anonymous"):
    text = text.strip()
    if not text:
        return {"error": "請輸入有效文字"}

    if rate_limited(client_key):
        return {"error": "速率限制：每 60 秒最多 %d 次" % RATE_LIMIT}

    lang, cleaned = detect_language(text)
    logger.info("process_message: detected=%s text=%s", lang, cleaned)

    if not lang:
        return {"error": "無法偵測語言"}

    lang = lang.lower()

    if lang.startswith('id'):
        expanded = expand_abbreviations(cleaned)
        pre = preprocess_text(expanded, 'indonesian')
        tr = translate_cached('id', 'zh-TW', pre)
        polished = polish_chinese(tr)
        save_to_sheet_row(text, polished, metadata={"direction": "id->zh", "client": client_key})
        return {"result": polished, "original_expanded": expanded, "preprocessed": pre, "lang": "id"}

    if lang.startswith('zh'):
        polished_in = polish_chinese(cleaned)
        tr = translate_cached('zh-TW', 'id', polished_in)
        save_to_sheet_row(text, tr, metadata={"direction": "zh->id", "client": client_key})
        return {"result": tr, "polished_input": polished_in, "lang": "zh"}

    # Fallback: if still not zh/id but text looks like zh or id
    han = len(_CJK_RE.findall(cleaned))
    if han >= 2:
        polished_in = polish_chinese(cleaned)
        tr = translate_cached('zh-TW', 'id', polished_in)
        save_to_sheet_row(text, tr, metadata={"direction": "zh->id(fallback)", "client": client_key})
        return {"result": tr, "polished_input": polished_in, "lang": "zh-fallback"}

    if _ID_HINTS.search(cleaned.lower()):
        expanded = expand_abbreviations(cleaned)
        pre = preprocess_text(expanded, 'indonesian')
        tr = translate_cached('id', 'zh-TW', pre)
        polished = polish_chinese(tr)
        save_to_sheet_row(text, polished, metadata={"direction": "id->zh(fallback)", "client": client_key})
        return {"result": polished, "original_expanded": expanded, "preprocessed": pre, "lang": "id-fallback"}

    return {"error": "僅支援中文與印尼文"}


# --- Flask endpoints ---
@app.route("/ping", methods=["GET"])
def ping():
    return "pong", 200


@app.route("/health", methods=["GET"])
def health():
    ok = {"ok": True, "sheets": bool(sheet)}
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
    # LINE signature validated by parser/handler
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
            client_key = "line:%s" % user_id
            res = process_message(user_msg, client_key=client_key)
            if "result" in res:
                reply_text = u"🗣️ 翻譯結果：%s" % res["result"]
            else:
                reply_text = u"⚠️ %s" % res.get("error", "處理失敗")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        except Exception as e:
            logger.exception("Error in handle_message: %s", e)
            try:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 內部錯誤"))
            except Exception:
                pass


# --- Run ---
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "0.0.0.0")
    logger.info("Starting Flask app on %s:%d", host, port)
    app.run(host=host, port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")