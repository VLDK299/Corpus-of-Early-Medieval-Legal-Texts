import re
import csv
import sys
from pathlib import Path

RAW_DIR = Path("texts/continental/continental_raw")
OUT_DIR = Path("texts/continental")
LOG_PATH = Path("logs/clean_latin_log.tsv")

# --- Паттерны удаления ---
RE_FOOTNOTE = re.compile(r"\*\).*$", re.MULTILINE)
RE_VARIANT = re.compile(r"///.*$", re.MULTILINE)
RE_ADD_MARK = re.compile(r"Add\.\s*\d+\.\s*")
RE_SINGLE_STAR = re.compile(r"(?<!\*)\*(?!\))")
RE_CYRILLIC = re.compile(r"[\u0400-\u04FF]+")
RE_LATIN_MARK = re.compile(r"^LATIN\s*$", re.MULTILINE)

RE_BRACKET_REF = re.compile(
    r"\((?:L\. Bai\.|v\. Eur\.|cfr\.|sic\b|vgl\.|tit\.|lib\.|cap\.)[^)]*\)",
    re.IGNORECASE,
)

# Строки-ссылки на римские источники (в квадратных скобках)
RE_SOURCE_LINE = re.compile(
    r"^\s*\[\s*(?:Paul|CTh|Dig|CJ|Ulp|Gai|Nov|Cod|Inst|Vat|Marc|Hermog|Callistrat|African|Papinian|Popon|Iulian|Marcian|Pomp|Sabin|Edict|Procons|respons|sent)",
    re.IGNORECASE,
)

# Редакторские заголовки capitularia
RE_EDITORIAL_HEADER = re.compile(
    r"^\s*\[\s*(?:Pactus|Decretio|Capitulare|Edictus|Die Kapitel)",
    re.IGNORECASE,
)

RE_TEXTUS_ABEST = re.compile(r"\[TEXTUS ABEST\]")

# --- Логирование ---
def log(logfile, doc_id, line_no, category, line):
    logfile.writerow([doc_id, line_no, category, line.strip()[:200]])

# --- Обработка ---
def clean_text(doc_id, text, logfile):
    lines = text.split("\n")
    cleaned = []

    for i, line in enumerate(lines, start=1):
        original = line

        # 1. Маркер языка
        if RE_LATIN_MARK.match(line):
            log(logfile, doc_id, i, "removed_latin_mark", original)
            continue

        # 2. Строки-ссылки на римские источники
        if RE_SOURCE_LINE.match(line):
            log(logfile, doc_id, i, "removed_source_ref", original)
            continue

        # 3. Редакторские заголовки capitularia
        if RE_EDITORIAL_HEADER.match(line):
            log(logfile, doc_id, i, "removed_editorial_header", original)
            continue

        # 4. Сноски, варианты
        line = RE_FOOTNOTE.sub("", line)
        line = RE_VARIANT.sub("", line)

        # 5. Маркер Add. N. (только маркер)
        line = RE_ADD_MARK.sub(" ", line)

        # 6. Одиночные *
        line = RE_SINGLE_STAR.sub("", line)

        # 7. Ссылки на издания в скобках
        line = RE_BRACKET_REF.sub("", line)

        # 8. Кириллица
        if RE_CYRILLIC.search(line):
            log(logfile, doc_id, i, "removed_cyrillic", original)
            line = RE_CYRILLIC.sub("", line)

        # 9. TEXTUS ABEST
        line = RE_TEXTUS_ABEST.sub("[lacuna]", line)

        # 10. Проверка на спорные квадратные скобки
        for m in re.finditer(r"\[([^\]]+)\]", line):
            content = m.group(1)
            if len(content.split()) >= 4:
                log(logfile, doc_id, i, "check_bracket_long", m.group(0))

        # 11. Проверка на лакуны
        if "…" in line or "..." in line:
            log(logfile, doc_id, i, "lacuna", line)

        # 12. Нормализация пробелов
        line = re.sub(r"[ \t]+", " ", line).strip()

        if line:
            cleaned.append(line)

    # --- Склейка разорванных строк ---
    merged = []
    for j, line in enumerate(cleaned, start=1):
        if not merged:
            merged.append(line)
            continue
        prev = merged[-1]
        # Склеиваем, если новая строка начинается со строчной буквы
        if line[:1].islower():
            # логируем подозрительные склейки после точки
            if prev.rstrip().endswith((".", ":", ";")):
                log(logfile, "?", j, "suspicious_merge", f"{prev[-40:]} || {line[:40]}")
            merged[-1] = prev + " " + line
        else:
            merged.append(line)

    return "\n".join(merged)

# --- Прогон ---
if __name__ == "__main__":
    if not RAW_DIR.exists():
        print(f"ОШИБКА: Папка с исходниками не найдена: {RAW_DIR}")
        print("Создайте её и поместите туда исходные латинские тексты для обработки.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    with LOG_PATH.open("w", encoding="utf-8", newline="") as lf:
        writer = csv.writer(lf, delimiter="\t")
        writer.writerow(["doc_id", "line", "category", "content"])

        files_processed = 0
        for raw in sorted(RAW_DIR.glob("*.txt")):
            doc_id = raw.stem
            text = raw.read_text(encoding="utf-8")
            cleaned = clean_text(doc_id, text, writer)
            (OUT_DIR / f"{doc_id}.txt").write_text(cleaned, encoding="utf-8")
            print(f"Готово: {doc_id}")
            files_processed += 1

        if files_processed == 0:
            print(f"ВНИМАНИЕ: В папке {RAW_DIR} не найдено ни одного .txt файла.")