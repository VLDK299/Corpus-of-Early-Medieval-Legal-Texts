import re
import csv
import sys
from pathlib import Path

RAW = Path("raw/anglo_saxon_laws_DOE_2000.txt")
INVENTORY = Path("inventory.tsv")
OUT_TXT = Path("texts/anglo_saxon")
OUT_TSV = Path("texts/anglo_saxon")
PATTERN = re.compile(r"^\[(\d+)\s+\(([^)]+)\)\]\s*(.*)$")

def clean_doc(doc_id, start, end):
    lines = RAW.read_text(encoding="utf-8").splitlines()
    fragment = lines[start-1:end]
    # удалить шапку до первого маркера
    try:
        first = next(i for i, l in enumerate(fragment) if l.startswith("["))
        fragment = fragment[first:]
    except StopIteration:
        print(f"WARN: в {doc_id} не найдено маркеров [000...], пропуск.")
        return

    records = []
    for line in fragment:
        line = line.rstrip("\n")
        if not line.strip():
            continue
        m = PATTERN.match(line)
        if m:
            ref = f"[{m.group(1)} ({m.group(2)})]"
            text = m.group(3).strip()
            records.append([ref, text])
        else:
            if records:
                records[-1][1] += " " + line.strip()
    
    # сохранить txt
    txt_path = OUT_TXT / f"{doc_id}.txt"
    txt_path.write_text("\n".join(r[1] for r in records), encoding="utf-8")
    
    # сохранить refs.tsv
    tsv_path = OUT_TSV / f"{doc_id}.refs.tsv"
    with tsv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["source_ref", "text"])
        w.writerows(records)

def main():
    if not RAW.exists():
        print(f"ОШИБКА: Не найден исходный файл {RAW}")
        print("Убедитесь, что вы получили его у DOE и положили в папку raw/.")
        sys.exit(1)
    
    if not INVENTORY.exists():
        print(f"ОШИБКА: Не найден {INVENTORY}")
        sys.exit(1)

    OUT_TXT.mkdir(parents=True, exist_ok=True)
    OUT_TSV.mkdir(parents=True, exist_ok=True)

    with INVENTORY.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("corpus") != "anglo_saxon":
                continue
            
            doc_id = row["doc_id"]
            start_str = row.get("start_line", "")
            end_str = row.get("end_line", "")
            
            if not start_str.isdigit() or not end_str.isdigit():
                print(f"WARN: {doc_id} — некорректные start_line/end_line ({start_str}, {end_str}). Пропуск.")
                continue
                
            start = int(start_str)
            end = int(end_str)
            
            print(f"Обработка {doc_id} (строки {start}-{end})...")
            clean_doc(doc_id, start, end)
            
    print("Готово!")

if __name__ == "__main__":
    main()