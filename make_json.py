import json

def parse_schedule_csv(filename="schedule.csv"):
    schedule_data = {}
    
    current_day = None
    days_map = {
        "понедельник": "0",
        "вторник": "1",
        "среда": "2",
        "четверг": "3",
        "пятница": "4",
        "суббота": "5"
    }

    try:
        # Используем utf-8 с игнорированием ошибок кодировки
        with open(filename, mode='r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Ошибка открытия файла {filename}: {e}")
        return

    # Раскладываем строки по запятым
    reader = [line.strip().split(',') for line in lines]

    classes_row = None
    for row in reader[:5]:
        if any("5а" in c or "10а" in c for c in row):
            classes_row = row
            break
    
    if not classes_row:
        print("❌ Не удалось найти строку с классами в CSV!")
        return

    col_to_class = {}
    for col_idx, val in enumerate(classes_row):
        val_clean = val.strip().lower().replace('"', '')
        if val_clean and (val_clean[:-1].isdigit() and val_clean[-1] in 'абвг'):
            col_to_class[col_idx] = val_clean

    print(f"Найдены классы в колонках: {col_to_class}")

    current_lesson = None

    for row in reader:
        if not row or not row[0].strip():
            continue
        
        first_col = row[0].strip().lower().replace('"', '')

        for day_name, day_idx in days_map.items():
            if day_name in first_col:
                current_day = day_idx
                current_lesson = None
                break

        clean_first = row[0].strip().replace('"', '')
        if clean_first.isdigit():
            current_lesson = int(clean_first)

        if current_day is not None and current_lesson is not None:
            for col_idx, c_name in col_to_class.items():
                if col_idx < len(row):
                    subject = row[col_idx].strip().replace('"', '')
                    room = ""
                    if col_idx + 1 < len(row):
                        room = row[col_idx + 1].strip().replace('"', '')

                    if subject and subject.lower() != 'спортзал':
                        if c_name not in schedule_data:
                            schedule_data[c_name] = {}
                        if current_day not in schedule_data[c_name]:
                            schedule_data[c_name][current_day] = {}
                        
                        schedule_data[c_name][current_day][str(current_lesson)] = [subject, room]

    with open("schedule.json", "w", encoding="utf-8") as f:
        json.dump(schedule_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Успешно! Сгенерирован schedule.json для {len(schedule_data)} классов.")

if __name__ == "__main__":
    parse_schedule_csv()
