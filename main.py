import os
import re
import string
from langdetect import detect, DetectorFactory
from langdetect.lang_detect_exception import LangDetectException
from dotenv import load_dotenv
from flask import Flask, request
from linebot import LineBotApi, WebhookHandler
from linebot.models import TextMessage, MessageEvent
from deep_translator import GoogleTranslator
import gspread
from oauth2client.service_account import ServiceAccountCredentials


# --- Load .env ---
load_dotenv()


# --- Flask Setup ---
app = Flask(__name__)
line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# --- Language Detector Seed ---
DetectorFactory.seed = 0

# --- Google Sheets Setup ---
sheet = None
if os.getenv("GOOGLE_SHEET_KEY") and os.getenv("GOOGLE_SHEET_JSON"):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(os.getenv("GOOGLE_SHEET_JSON"), scope)
    sheet = gspread.authorize(creds).open_by_key(os.getenv("GOOGLE_SHEET_KEY")).sheet1

# --- Maps ---
indonesian_abbreviation_map = {
    "ad": "弟弟",
    "aj": "aja",
    "ajh": "aja",
    "aja": "就好",
    "a.m.": "pagi",
    "bca": "銀行",
    "blg": "說",
    "blm": "belum",
    "bkn": "不是",
    "bpk": "先生",
    "bsa": "bisa",
    "bsk": "besok",
    "buka": "打開",
    "bwt": "buat",
    "ce": "姐姐",
    "Cece": "姐姐",
    "cucu": "孫子",
    "cuaca": "天氣",
    "deh": "就這樣吧",
    "dki": "特別首都區",
    "dlu": "dulu",
    "dpt": "dapat",
    "dr": "醫生",
    "dy": "他/她",
    "dya": "他/她",
    "faq": "常見問題",
    "gk": "不",
    "gt": "gitu",
    "gtu": "gitu",
    "gtw": "不知道",
    "habis": "吃完",
    "hr": "假期",
    "ibu": "媽媽",
    "jam": "pukul",
    "jg": "juga",
    "jgk": "juga",
    "jdi": "jadi",
    "kak": "哥哥",
    "karena": "因為",
    "kartu": "卡片",
    "kl": "如果",
    "klw": "kalau",
    "km": "公里",
    "kmu": "你",
    "kmrn": "昨天",
    "kkn": "社會服務",
    "kpk": "反貪腐委員會",
    "krg": "少",
    "krn": "karena",
    "lihat": "看見",
    "lg": "lagi",
    "iya": "ya",              # 是的（常見變體）
    "lya": "ya",
    "mandi": "洗澡",
    "mandikan": "洗澡",
    "masaknya": "makannya",
    "masukan": "放進",
    "makan": "吃",
    "mobil": "車",
    "nanti": "等一下",
    "nd": "下屬",
    "nenek": "奶奶",
    "ngash": "ngasih",
    "ngerti": "明白",
    "ngga": "不",
    "ngmng": "講話",
    "nenwk": "nenek",
    "orang": "人",
    "pintu": "門口",
    "pm": "私人消息",
    "polri": "印度尼西亞警察",
    "potong": "切",
    "pp": "夫妻",
    "pt": "有限公司",
    "p.m.": "sore",
    "pulang": "回家",
    "rehabilitas": "復健",
    "rt": "居民社區",
    "rumah": "家",
    "rw": "社區範圍",
    "saja": "就好",
    "sayur": "蔬菜",
    "sd": "小學",
    "sdr": "弟兄/姐妹",
    "selesai": "喝完了",
    "sja": "saja",
    "sllu": "selalu",
    "sm": "sama",
    "sm2": "sama-sama",
    "smpe": "sampai",
    "smp": "初中",
    "smk": "中等職業學校",
    "sore": "siang",
    "sudah": "已經",
    "sy": "我",
    "syg": "親愛的",
    "susa": "susah",
    "t": "tidur",
    "tapi": "但是",
    "td": "tadi",
    "tdk": "不",
    "temani": "陪",
    "tk": "學前班",
    "tm": "他們",
    "tmn": "朋友",
    "tni": "印度尼西亞國軍",
    "trus": "terus",
    "trs": "terus",
    "tbtb": "突然",
    "tutup": "關上",
    "uang": "錢",
    "udh": "sudah",
    "udh2": "已經已經", 
    "wfh": "在家工作",
    "wfo": "辦公室工作",
    "wmm": "微型企業"
}

chinese_polish_map = {
    "你好吗": "你好嗎？",
    "你忙吗": "你忙嗎？",
    "可以吗": "可以嗎？",
    "怎么了": "怎麼了？",
    "你在干什么": "你在幹嘛？",
    "去哪": "去哪裡？",
    "怎么说": "怎麼說呢？",
    "怎么办": "該怎麼辦？",
    "有什么": "有什麼事？",
    "加油": "努力吧",
    "我饿了": "我餓了",
    "我很忙": "我現在很忙",
    "我不知道": "我不清楚",
    "一定要": "必須",
    "还行": "還不錯",
    "不行": "不太行",
    "自己来": "自己來處理",
    "现在": "此刻",
    "很好": "非常好",
    "谢谢": "謝謝",
    "对不起": "對不起",
    "没关系": "沒關係",
    "没问题": "沒問題",
    "没事": "沒事",
    "好久不见": "好久不見",
    "太棒了": "太棒了",
    "太遗憾了": "太遺憾了",
    "明天见": "明天見",
    "拜拜": "再見",
    "大豆牛奶": "豆漿",
    "大豆": "豆漿",
    "噁心": "想吐",
    "祖母": "奶奶",
    "交談": "說話",
    "太重": "太大",
    "下雨": "雨下",
    "一點": "一點點",
    "首先": "先",
    "這裡是": "這裡正在",
    "就好就好": "就好",
    "吃": "吃飯",
    "康復": "復健",
    "燈光": "燈",
    "沒有用完了": "喝完了",
    "沒有藥可以吃": "沒有藥可以吃了",
    "取消了她的": "會關",
    "我洗澡洗澡洗澡": "幫奶奶洗澡",
    "點3": "3點",
    "我已經幫助我的奶奶在3點上洗澡": "我在三點已經幫奶奶洗澡了",
    "奶奶不太冷": "以免對奶奶來說太冷",
    "奶奶午餐姐姐": "奶奶的午餐，姐姐",
    "留一點點姐姐": "只剩一點點，姐姐",
    "這個飯是半碗嗎": "這碗飯是半碗的嗎？",
    "奶奶的晚餐用完了姐姐": "奶奶的晚餐吃完了，姐姐",
    "奶奶也要拜拜": "奶奶也要去拜拜",
    "明天弟弟要拜拜妳在幫忙他把東西擺好": "明天弟弟要拜拜，妳要幫他把東西擺好",
    "哦，是的姐姐": "喔，好，姐姐",
    "了解姐姐": "我懂了，姐姐",
    "這裡有什麼樂趣": "這附近有什麼好玩的？",
    "查看點多少錢": "幾點退房？",
    "國家姓氏": "國姓鄉",
    "姓氏國家": "國姓鄉",
    "奶奶的午餐，姐姐。": "奶奶的午餐，姐姐",
    "Sup sangat sedikit mabuk.": "湯只喝了一點點",
    "Apakah nenek punya makan malam?": "奶奶吃晚餐了嗎？",
    "已經姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐姐": "奶奶的晚餐已經吃完了，姐姐",
    "奶奶吃飯晚餐點6姐姐": "奶奶六點吃晚餐，姐姐",
    "什麼是姐姐": "什麼事，姐姐？",
    "已經我把它放在房子裡姐姐": "我已經把桶子拿進房子裡了，姐姐",
    "是的姐姐": "好喔，姐姐",
    "我打掃就好，明天我是孫子": "我打掃就好，明天我再洗，姐姐",
    "姐姐奶奶說了我不明白的": "奶奶說的話我不太懂，姐姐",
    "這裡雨下了姐姐": "這裡從早上下雨，姐姐",
    "想在門口坐坐": "想在門口坐一下",
    "Senang melihat mobilnya": "看看車子也好",
    "妳推她在門口坐": "你推她到門口坐一下",
    "在門口就好": "坐門口就好",
    "打開門前面那裡": "把門前那邊打開",
    "等一下妳要煮飯": "等等你要煮飯",
    "從復健返回點9，30姐姐": "從復健回來是 9:30，姐姐",
    "有限公司有限公司": "有限公司",
    "Makelar": "仲介",
    "晚餐你還有飯吃嗎": "你晚餐還有飯吃嗎",
    "這樣吃的飽嗎": "吃這樣夠飽嗎",
    "Sangat sedikit susu": "奶奶只吃了一點點",
    "喔，好，姐姐": "好喔，姐姐",
    "已經已經姐姐": "已經，姐姐",
    "吃飯夜": "晚餐",
    "吃飯夜奶奶奶奶奶奶": "奶奶晚餐吃了嗎",
    "很多": "吃得很多。",
    "姐妹奶奶奶忘了帶它": "姊姊忘了把奶奶的牛奶帶來",
    "我姐姐說他星期五把他帶走": "姊姊說她星期五會帶來",
    "說這是錯誤的": "說錯了",
    "它是在星期四帶來的": "是星期四帶來的",
    "蘇珊一點點姐姐吃飯夜": "吃得有一點點，姐姐",
    "Saya mengatakan foto yang saya ambil": "我是說你拍的照片",
    "Anda mengambil fotonya": "你拍了照片",
    "花了":"吃完了",
    "我落後於奶奶姐姐切":"姐姐，我在奶奶後面切菜",
}

# --- Functions ---
import re

def convert_jam_to_chinese(text):
    """
    將印尼文時間格式如 jam 9, jam 12, jam 12:30, jam 12 ,30 等轉換為 24小時制時間，並保持一致性（如12:30）。
    特別處理 9.5、12.35 這類格式，並對上午下午進行轉換。
    """
    def repl(match):
        hour = match.group(1)  # 小時部分
        minute = match.group(2)  # 分鐘部分

        # 處理分鐘部分，清除逗號與點號，並保持一致
        if minute:
            minute = minute.strip().replace(',', '.').replace(' ', '')  # 清除逗號並將其轉為點號
            if '.' in minute:  # 處理像 9.5 或 12.35 這類時間
                hour, minute = minute.split('.')
                return f"{int(hour)}:{int(minute):02d}"  # 保證格式一致，例如 9.5 轉為 9:30
            else:
                return f"{int(hour)}:{minute}"  # 其他分鐘數顯示為 12:XX
        else:
            return f"{int(hour)}:00"  # 沒有分鐘數時顯示為 12:00

    # 只匹配 jam 和後面緊接的數字，不加空格或其他符號才轉換
    text = re.sub(r'\bjam\s*(\d{1,2})\s*[:.,]?\s*(\d{0,2})?', repl, text)

    # 處理 "jam 3 sore", "jam 6 pagi" 等
    text = re.sub(r'jam\s*(\d{1,2})\s*(sore)', r'點下午\1點', text)
    text = re.sub(r'jam\s*(\d{1,2})\s*(pagi)', r'點上午\1點', text)
    text = re.sub(r'jam\s*(\d{1,2})\s*(p.m\.)', r'點下午\1點', text)
    text = re.sub(r'jam\s*(\d{1,2})\s*(a\.m\.)', r'點上午\1點', text)

    # 處理 p.m. 和 a.m.，將其轉換為「晚上」或「上午」格式
    text = re.sub(r'jam\s*(\d{1,2})\s*(:?\d{1,2})?\s*(p\.m\.)', r'晚上\1:\2', text)
    text = re.sub(r'jam\s*(\d{1,2})\s*(:?\d{1,2})?\s*(a\.m\.)', r'上午\1:\2', text)

    return text

def expand_abbreviations(text):
    for abbr, full in indonesian_abbreviation_map.items():
        text = re.sub(r'\b' + re.escape(abbr) + r'\b', full, text, flags=re.IGNORECASE)
    return text

def polish_chinese(text):
    for k, v in chinese_polish_map.items():
        text = text.replace(k, v)
    if not re.search(r'[。！？]$', text):
        text += "。"
    return text

def translate(text, source, target):
    try:
        return GoogleTranslator(source=source, target=target).translate(text)
    except Exception as e:
        print(f"翻譯錯誤: {e}")
        return "⚠️ 翻譯失敗"

def save_to_sheet(original, translated):
    if sheet:
        try:
            sheet.append_row([original, translated])
        except Exception as e:
            print(f"寫入 Google Sheets 錯誤：{e}")

def detect_language(text):
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        return 'chinese', text
    if any(char in 'abcdefghijklmnopqrstuvwxyz' for char in text.lower()):
        return 'indonesian', text
    try:
        return detect(text), text
    except LangDetectException:
        return None, text


def preprocess_text(text, lang):
    if lang == 'indonesian':
        text = re.sub(r'(\d{1,2})點(\d{1,2})', r'\1:\2', text)  # 例如「12點30」轉為「12:30」
        text = re.sub(r'(\d{1,2})點', r'\1:00', text)  # 例如「12點」轉為「12:00」
        text = re.sub(r'(\d{1,2})分', '', text)  # 移除「分」字，保持數字一致
        text = re.sub(r'今天中午(\d{1,2})點(\d{1,2})', r'Saat itu \1:\2 siang hari ini', text)  # 正確處理今天中午12點30分
        # 處理包含上午下午與時間
        text = re.sub(r'jam\s*(\d{1,2})\s*(sore|pagi|p.m\.|a\.m\.)', r'jam \1', text)  # 修正上午與下午
    return text

def process_message(text):
    text = text.strip()
    if not text or text in string.punctuation:
        return "⚠️ 請輸入有效文字"

    lang, clean_text = detect_language(text)
    print(f"Detected language: {lang}, Cleaned text: {clean_text}")

    if not lang:
        return "⚠️ 無法偵測語言"

    if lang == 'indonesian':
        clean_text = expand_abbreviations(clean_text.lower())
        clean_text = convert_jam_to_chinese(clean_text)  # ✅ 加入時間處理
        clean_text = preprocess_text(clean_text, lang)  # 修正這行
        translated = translate(clean_text, 'id', 'zh-TW')
        translated = polish_chinese(translated)
    elif lang == 'chinese':
        clean_text = polish_chinese(preprocess_text(clean_text, lang))  # 修正這行
        translated = translate(clean_text, 'zh-TW', 'id')
    else:
        return "⚠️ 僅支援中文與印尼文"


    save_to_sheet(text, translated)
    return translated

# --- LINE Webhook ---
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    handler.handle(body, signature)
    return 'OK'

@handler.add(MessageEvent)
def handle_message(event):
    if isinstance(event.message, TextMessage):
        user_message = event.message.text
        translated_message = process_message(user_message)
        line_bot_api.reply_message(event.reply_token, TextMessage(text=translated_message))

# --- Start App ---
if __name__ == "__main__":
    app.run()
