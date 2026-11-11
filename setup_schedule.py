import json
import re

# Сырой текст выгрузки из лицея 419
RAW_TEXT = """
СЮДА_ВСТАВЬТЕ_ТЕКСТ_ТАБЛИЦЫ
"""

DAYS_MAP = {
    "понедельник": 0, "вторник": 1, "среда": 2,
    "четверг": 3, "пятница": 4, "суббота": 5
}

SHORT_NAMES = {
    "обществознание": "Общ-ние", "английский язык": "Ин. яз", "англ. язык": "Ин. яз",
    "анг/анг": "Ин. яз", "раз-ры о важном": "Разг. о важном", "разговоры о важном": "Разг. о важном",
    "вероятность и статистика": "Вер. и стат.", "вер. и статистика": "Вер. и стат.",
    "информатика": "Информ.", "инф/инф": "Информ.", "физкультура": "Физ-ра",
    "ф.культура": "Физ-ра", "ф.к/ф.к": "Физ-ра", "литература": "Лит-ра", "русский язык": "Рус. яз"
}

def clean(text):
    if not text: return ""
    t = text.strip().strip('"').strip("'")
    low = t.lower()
    for k, v in SHORT_NAMES.items():
        if k in low: return v
    return t

def parse_schedule():
    schedule = {} # { class: { day_idx: { lesson_num: [subj, room] } } }
    lines = RAW_TEXT.strip().splitlines()

    class_columns = {} # col_index: class_name
    current_day = None

    for line in lines:
        if not line.strip() or "Школьный диспетчер" in line:
            continue

        # Делим строго по запятым
        parts = [p.strip() for p in line.split(",")]
        line_low = line.lower()

        # 1. Проверяем день недели
        found_day = False
        for d_name, d_idx in DAYS_MAP.items():
            if parts[0].lower().startswith(d_name):
                current_day = d_idx
                found_day = True
                break
        if found_day:
            continue

        # 2. Находим заголовки классов (5а, 5б, 6а... 10а... 11б)
        if "5а" in line_low and "10а" in line_low:
            for idx, cell in enumerate(parts):
                m = re.match(r'^([1-9]|1[0-1])[а-г]$', cell.lower())
                if m:
                    class_name = m.group(0)
                    class_columns[idx] = class_name
                    if class_name not in schedule:
                        schedule[class_name] = {}
            continue

        # 3. Читаем уроки (строка начинается с цифры урока)
        if current_day is not None and len(parts) > 1 and parts[0].isdigit():
            lesson_num = parts[0]
            for col_idx, class_name in class_columns.items():
                if col_idx < len(parts):
                    subj = clean(parts[col_idx])
                    room = parts[col_idx + 1].strip() if col_idx + 1 < len(parts) else ""
                    if subj and not subj.isdigit():
                        if str(current_day) not in schedule[class_name]:
                            schedule[class_name][str(current_day)] = {}
                        schedule[class_name][str(current_day)][lesson_num] = [subj, room]

    with open("schedule.json", "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    print("✅ Файл schedule.json успешно создан!")
    print(f"Распознано классов: {len(schedule)}")

if __name__ == "__main__":
    parse_schedule()
