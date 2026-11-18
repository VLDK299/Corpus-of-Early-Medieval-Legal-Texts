import csv
import re
import sys
from pathlib import Path
from collections import defaultdict

META_PATH = Path("metadata.tsv")
REPORT_PATH = Path("logs/tokens_report.tsv")
SUBCORPUS_DIRS = {
    "insular": Path("texts/anglo_saxon"),
    "continental": Path("texts/continental"),
}

# Токен: последовательность букв/цифр, включая диакритику
TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
# Только буквенные токены (без цифр)
ALPHA_RE = re.compile(r"[^\W\d_]+", flags=re.UNICODE)


def count_tokens(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    tokens_all = TOKEN_RE.findall(text)
    tokens_alpha = ALPHA_RE.findall(text)
    types = {t.lower() for t in tokens_alpha}
    return {
        "tokens_total": len(tokens_all),
        "tokens_alpha": len(tokens_alpha),
        "types": len(types),
        "chars": len(text),
    }


def load_metadata(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    if "token_count" not in fieldnames:
        fieldnames.append("token_count")
        for r in rows:
            r.setdefault("token_count", "")
    return rows, fieldnames


def save_metadata(path: Path, rows, fieldnames):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f, delimiter="\t", fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    if not META_PATH.exists():
        print(f"Нет файла {META_PATH}. Создайте metadata.tsv сначала.")
        sys.exit(1)

    rows, fieldnames = load_metadata(META_PATH)

    report = []
    updated_by_sub = defaultdict(int)
    missing = []
    unknown_sub = []
    fell_back = []

    for row in rows:
        doc_id = (row.get("doc_id") or "").strip()
        if not doc_id:
            continue

        doc_ascii = (row.get("doc_id_ascii") or doc_id).strip() or doc_id
        subcorpus = (row.get("subcorpus") or "").strip()

        if subcorpus not in SUBCORPUS_DIRS:
            unknown_sub.append(f"{doc_id} ({subcorpus or 'пусто'})")
            continue

        # Сначала ищем по ascii, затем fallback на оригинал (если файл ещё не переименован)
        txt_path = SUBCORPUS_DIRS[subcorpus] / f"{doc_ascii}.txt"
        if not txt_path.exists():
            fallback = SUBCORPUS_DIRS[subcorpus] / f"{doc_id}.txt"
            if fallback.exists():
                txt_path = fallback
                fell_back.append(f"{doc_ascii} -> {txt_path}")
            else:
                missing.append(f"{doc_ascii} (doc_id={doc_id}) -> {txt_path}")
                print(f"НЕТ ФАЙЛА: {txt_path}")
                continue

        stats = count_tokens(txt_path)
        row["token_count"] = str(stats["tokens_total"])
        updated_by_sub[subcorpus] += 1
        report.append([
            subcorpus, doc_ascii,
            stats["tokens_total"], stats["tokens_alpha"],
            stats["types"], stats["chars"],
        ])

    save_metadata(META_PATH, rows, fieldnames)

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow([
            "subcorpus", "doc_id", "tokens_total",
            "tokens_alpha", "types", "chars",
        ])
        writer.writerows(report)

    print("\n=== ИТОГИ ===")
    totals = defaultdict(int)
    for r in report:
        totals[r[0]] += r[2]
    for sub, n in updated_by_sub.items():
        print(f"{sub}: обновлено {n} памятников, токенов всего {totals[sub]}")
    print(f"Всего токенов: {sum(totals.values())}")

    if unknown_sub:
        print("\nНеизвестный subcorpus (не insular и не continental):")
        for u in unknown_sub:
            print(f"  {u}")

    if fell_back:
        print("\nНайдено по старому имени (doc_id), не по doc_id_ascii:")
        for fb in fell_back:
            print(f"  {fb}")
        print("  Проверьте: файлы в texts/<subcorpus>/ ещё не переименованы.")

    if missing:
        print("\nПропущено (файл не найден ни по doc_id_ascii, ни по doc_id):")
        for m in missing:
            print(f"  {m}")
        print("\nПроверьте: имя файла в texts/<subcorpus>/ должно совпадать "
              "с doc_id_ascii (или doc_id) в metadata.tsv без расширения.")


if __name__ == "__main__":
    main()