import os
import re
import time
import sqlite3
import threading
import json
from datetime import datetime, timedelta
from flask import Flask
import telebot
from telebot import types
import requests
from bs4 import BeautifulSoup

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(BOT_TOKEN)

URL = "https://419.spb.ru/novosti/news_post/izmeneniya-raspisaniya"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DAYS_RU = ["ПОНЕДЕЛЬНИК", "ВТОРНИК", "СРЕДА", "ЧЕТВЕРГ", "ПЯТНИЦА", "СУББОТА", "ВОСКРЕСЕНЬЕ"]
MONTHS_RU = ["", "января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

ALL_CLASSES = [
    "5а","5б","5в","5г","6а","6б","6в","6г",
    "7а","7б","7в","8а","8б","8в","8г",
    "9а","9б","9в","9г","10а","10б","10в","11а","11б"
]

SHORT_NAMES = {
    "обществознание": "Общ-ние", "английский язык": "Ин. яз", "англ. язык": "Ин. яз",
    "анг/анг": "Ин. яз", "раз-ры о важном": "Разг. о важном", "разговоры о важном": "Разг. о важном",
    "вероятность и статистика": "Вер. и стат.", "вер. и статистика": "Вер. и стат.",
    "информатика": "Информ.", "инф/инф": "Информ.", "физкультура": "Физ-ра",
    "ф.культура": "Физ-ра", "ф.к/ф.к": "Физ-ра", "литература": "Лит-ра", "русский язык": "Рус. яз"
}

def clean_subj(name):
    if not name: return ""
    low = name.strip().lower()
    for k, v in SHORT_NAMES.items():
        if k in low: return v
    return name.strip()

# --- БАЗА ДАННЫХ ---
def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        class_name TEXT,
        topic_id INTEGER
    )""")
    conn.commit()
    conn.close()

def set_user_class(chat_id, class_name, topic_id=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (chat_id, class_name, topic_id) VALUES (?, ?, ?)", 
              (chat_id, class_name.lower(), topic_id))
    conn.commit()
    conn.close()

def get_user_class(chat_id):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT class_name, topic_id FROM users WHERE chat_id = ?", (chat_id,))
    row = c.fetchone()
    conn.close()
    return row if row else (None, None)

def get_all_subscribers():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("SELECT chat_id, class_name, topic_id FROM users")
    rows = c.fetchall()
    conn.close()
    return rows

# --- ЗАГРУЗКА БАЗОВОГО РАСПИСАНИЯ ИЗ JSON ---
BASE_SCHEDULE = {}

def load_schedule():
    global BASE_SCHEDULE
    if os.path.exists("schedule.json"):
        with open("schedule.json", "r", encoding="utf-8") as f:
            BASE_SCHEDULE = json.load(f)
        print(f"✅ Базовое расписание загружено для {len(BASE_SCHEDULE)} классов")
    else:
        print("⚠️ Файл schedule.json не найден!")

# --- УМНЫЙ ПАРСЕР ПО ДАТАМ ---
def parse_date_from_text(txt):
    """Пытается вытащить день и месяц из текста заголовка на сайте"""
    txt = txt.lower()
    day_num = None
    month_num = None
    wday = None

    # Ищем день недели
    for idx, name in enumerate(["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]):
        if name in txt:
            wday = idx
            break

    # Ищем число и месяц (например, "12 ноября")
    m = re.search(r'\b(\d{1,2})\s+(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)', txt)
    if m:
        day_num = int(m.group(1))
        m_str = m.group(2)
        months_map = {'янв':1, 'фев':2, 'мар':3, 'апр':4, 'май':5, 'июн':6, 'июл':7, 'авг':8, 'сен':9, 'окт':10, 'ноя':11, 'дек':12}
        for k, v in months_map.items():
            if k in m_str:
                month_num = v
                break
    return day_num, month_num, wday

def fetch_all_changes():
    """Собирает замены со всеми датами: { (day, month): { class_name: { lesson_num: (sub, room, canc) } } }"""
    all_dates_changes = {}
    try:
        res = requests.get(URL, headers=HEADERS, timeout=12)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, "html.parser")
        is_students = False

        current_date_key = None

        for el in soup.find_all(['h1', 'h2', 'h3', 'p', 'div', 'tr', 'strong', 'b']):
            txt = el.get_text(" ", strip=True)
            txt_upper = txt.upper()

            # Проверяем, не заголовок ли это с датой
            d_num, m_num, w_d = parse_date_from_text(txt)
            if d_num and m_num:
                current_date_key = (d_num, m_num)
                if current_date_key not in all_dates_changes:
                    all_dates_changes[current_date_key] = {c: {} for c in ALL_CLASSES}

            if "ОБУЧАЮЩИЕСЯ" in txt_upper or "УЧАЩИЕСЯ" in txt_upper:
                is_students = True
                continue
            elif "ПЕДАГОГИ" in txt_upper and len(txt) < 30 and is_students:
                is_students = False
                continue

            if not is_students or el.name != 'tr':
                continue

            if not current_date_key:
                continue # Если дату еще не встретили, пропускаем строки

            cells = [re.sub(r'\s+', ' ', td.get_text(strip=True)) for td in el.find_all(['td', 'th'])]
            if len(cells) < 2:
                continue

            first_cell = cells[0].strip().lower()
            if re.search(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.', cells[0]):
                continue

            matched_classes = [c for c in ALL_CLASSES if re.search(r'\b' + c, first_cell) or c in first_cell]
            if not matched_classes:
                continue

            row_full = " ".join(cells).upper()
            is_canc = "НЕТ" in row_full or "СНЯТ" in row_full or "ОТМЕН" in row_full

            lesson_num = int(cells[1]) if len(cells) >= 3 and cells[1].isdigit() else None
            sub = clean_subj(cells[2]) if len(cells) > 2 else ""
            room = cells[3] if len(cells) > 3 else ""

            for c in matched_classes:
                if lesson_num:
                    all_dates_changes[current_date_key][c][lesson_num] = (sub, room, is_canc)
                elif is_canc:
                    for digit in re.findall(r'\d+', row_full):
                        all_dates_changes[current_date_key][c][int(digit)] = ("УРОК СНЯТ", "", True)
    except Exception as e:
        print("Ошибка парсинга замен:", e)

    return all_dates_changes

def build_class_message(c_name, target_title, target_wday, day_changes):
    base = BASE_SCHEDULE.get(c_name, {}).get(str(target_wday), {})
    base = {int(k): v for k, v in base.items()}
    
    all_nums = sorted(set(list(base.keys()) + list(day_changes.keys())))

    if not all_nums:
        return f"📅 <b>{c_name.upper()} • {target_title}</b>\n\n🎉 Уроков нет или выходной!"

    if day_changes:
        header = f"🔔 <b>ИЗМЕНЕНИЯ В РАСПИСАНИИ ({c_name.upper()})</b>\n📅 <b>{target_title}</b>\n"
    else:
        header = f"🟢 <b>РАСПИСАНИЕ ({c_name.upper()})</b>\n📅 <b>{target_title}</b>\n\n✅ <i>Изменений нет, уроки по обычному графику:</i>\n"

    lines = [header]
    for num in all_nums:
        if num in day_changes:
            sub, room, canc = day_changes[num]
            r = f" (каб. {room})" if room else ""
            old_subj = base.get(num, ("", ""))[0]
            if canc:
                old = f" <s>{old_subj}</s>" if old_subj else ""
                lines.append(f"<blockquote>❌ <b>{num} урок: СНЯТ</b>{old}</blockquote>")
            else:
                old = f"\n   ↳ <i>Вместо: <s>{old_subj}</s></i>" if old_subj else ""
                lines.append(f"<blockquote>⚡ <b>{num} урок: {sub}{r}</b>{old}</blockquote>")
        elif num in base:
            sub, room = base[num]
            r = f" (каб. {room})" if room else ""
            lines.append(f"🔹 {num} ур: {sub}{r}")

    lines.append("\n🌐 <a href=\"https://419.spb.ru/novosti/news_post/izmeneniya-raspisaniya\">Сайт лицея 419</a>")
    return "\n".join(lines)

# --- КНОПКИ И МЕНЮ TELEGRAM ---
def get_main_keyboard():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📅 На сегодня", "📆 На завтра")
    kb.row("⚡ Только замены", "⚙️ Сменить класс")
    return kb

def get_class_inline_keyboard():
    kb = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(text=c.upper(), callback_data=f"set_{c}") for c in ALL_CLASSES]
    kb.add(*btns)
    return kb

@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    c_name, _ = get_user_class(message.chat.id)
    if c_name:
        bot.reply_to(message, f"👋 Привет! Ваш текущий класс: <b>{c_name.upper()}</b>.\nВыберите действие в меню:", 
                     parse_mode="HTML", reply_markup=get_main_keyboard())
    else:
        bot.reply_to(message, "👋 Привет! Я бот расписания ГБОУ Лицей № 419.\n\n👇 <b>Выберите ваш класс:</b>", 
                     parse_mode="HTML", reply_markup=get_class_inline_keyboard())

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def callback_set_class(call):
    c_name = call.data.split("_")[1]
    topic_id = getattr(call.message, 'message_thread_id', None)
    set_user_class(call.message.chat.id, c_name, topic_id)
    bot.edit_message_text(f"✅ Вы успешно выбрали класс <b>{c_name.upper()}</b>!\nТеперь бот присылает расписание и замены для вашего класса.",
                          chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="HTML")
    bot.send_message(call.message.chat.id, "Используйте кнопки меню внизу 👇", reply_markup=get_main_keyboard())

@bot.message_handler(func=lambda m: m.text == "⚙️ Сменить класс")
def cmd_change_class(message):
    bot.reply_to(message, "👇 <b>Выберите новый класс:</b>", parse_mode="HTML", reply_markup=get_class_inline_keyboard())

@bot.message_handler(func=lambda m: m.text in ["📅 На сегодня", "/today", "/сегодня"])
def cmd_today(message):
    c_name, _ = get_user_class(message.chat.id)
    if not c_name:
        cmd_start(message); return
    
    now_msk = datetime.utcnow() + timedelta(hours=3)
    target_date = (now_msk.day, now_msk.month)
    wday = now_msk.weekday()
    title = f"{DAYS_RU[wday]} ({now_msk.day} {MONTHS_RU[now_msk.month]})"
    
    all_changes = fetch_all_changes()
    day_changes = all_changes.get(target_date, {}).get(c_name, {})
    
    bot.reply_to(message, build_class_message(c_name, title, wday, day_changes), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in ["📆 На завтра", "/tomorrow", "/завтра"])
def cmd_tomorrow(message):
    c_name, _ = get_user_class(message.chat.id)
    if not c_name:
        cmd_start(message); return
    
    now_msk = datetime.utcnow() + timedelta(hours=3)
    nxt = now_msk + timedelta(days=2 if now_msk.weekday() == 5 else 1)
    target_date = (nxt.day, nxt.month)
    wday = nxt.weekday()
    title = f"{DAYS_RU[wday]} ({nxt.day} {MONTHS_RU[nxt.month]})"
    
    all_changes = fetch_all_changes()
    day_changes = all_changes.get(target_date, {}).get(c_name, {})
    
    bot.reply_to(message, build_class_message(c_name, title, wday, day_changes), parse_mode="HTML")

@bot.message_handler(func=lambda m: m.text in ["⚡ Только замены", "/changes", "/замены"])
def cmd_only_changes(message):
    c_name, _ = get_user_class(message.chat.id)
    if not c_name:
        cmd_start(message); return
        
    now_msk = datetime.utcnow() + timedelta(hours=3)
    target_date = (now_msk.day, now_msk.month)
    title = f"{now_msk.day} {MONTHS_RU[now_msk.month]}"
    
    all_changes = fetch_all_changes()
    c_changes = all_changes.get(target_date, {}).get(c_name, {})
    
    if not c_changes:
        bot.reply_to(message, f"✅ Для <b>{c_name.upper()}</b> на сегодня замен нет!", parse_mode="HTML")
        return
    lines = [f"⚡ <b>ЗАМЕНЫ ДЛЯ {c_name.upper()} ({title}):</b>\n"]
    for num, (sub, room, canc) in sorted(c_changes.items()):
        r = f" (каб. {room})" if room else ""
        lines.append(f"• <b>{num} урок:</b> {sub}{r}" if not canc else f"• <b>{num} урок:</b> <s>СНЯТ</s>")
    bot.reply_to(message, "\n".join(lines), parse_mode="HTML")

# --- ФОНОВЫЙ МОНИТОРИНГ И РАССЫЛКА ЗАМЕН ---
def auto_alerts_loop():
    last_signatures = {}
    while True:
        try:
            now_msk = datetime.utcnow() + timedelta(hours=3)
            # Автоматически проверяем либо сегодня, либо завтра (если вечер)
            if now_msk.hour >= 14 or now_msk.weekday() in (5, 6):
                nxt = now_msk + timedelta(days=2 if now_msk.weekday() == 5 else 1)
                target_date = (nxt.day, nxt.month)
                target_wday = nxt.weekday()
                target_title = f"{DAYS_RU[target_wday]} ({nxt.day} {MONTHS_RU[nxt.month]})"
            else:
                target_date = (now_msk.day, now_msk.month)
                target_wday = now_msk.weekday()
                target_title = f"{DAYS_RU[target_wday]} ({now_msk.day} {MONTHS_RU[now_msk.month]})"

            all_changes = fetch_all_changes()
            date_changes = all_changes.get(target_date, {})
            subscribers = get_all_subscribers()

            for chat_id, c_name, topic_id in subscribers:
                c_changes = date_changes.get(c_name, {})
                current_sig = f"{target_title}_{sorted(c_changes.items())}"

                if c_changes and current_sig != last_signatures.get(c_name):
                    msg = build_class_message(c_name, target_title, target_wday, c_changes)
                    try:
                        bot.send_message(chat_id, msg, message_thread_id=topic_id, parse_mode="HTML")
                    except Exception:
                        pass

            for c_name in ALL_CLASSES:
                if date_changes.get(c_name):
                    last_signatures[c_name] = f"{target_title}_{sorted(date_changes[c_name].items())}"

        except Exception as e:
            print("Ошибка в цикле мониторинга:", e)
        time.sleep(300)

# --- ВЕБ-СЕРВЕР ---
app = Flask(__name__)
@app.route('/')
def index():
    return "Bot 419 is alive 24/7!"

if __name__ == '__main__':
    init_db()
    load_schedule()
    threading.Thread(target=auto_alerts_loop, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))), daemon=True).start()
    print("Школьный бот лицея 419 запущен...")
    bot.infinity_polling()