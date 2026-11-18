import csv
import re
import sys
from pathlib import Path
from collections import Counter, defaultdict

META_PATH = Path("metadata.tsv")
OUT_DIR = Path("word_forms")
REPORT_PATH = Path("logs/word_forms_report.tsv")
SUBCORPUS_DIRS = {
    "insular": Path("texts/anglo_saxon"),
    "continental": Path("texts/continental"),
}

TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text)


def write_freq_list(path: Path, counter: Counter, total: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["rank", "form", "count", "per_10k"])
        for rank, (form, count) in enumerate(counter.most_common(), 1):
            per_10k = (count / total * 10000) if total else 0
            writer.writerow([rank, form, count, f"{per_10k:.2f}"])


def main():
    if not META_PATH.exists():
        print(f"Нет {META_PATH}.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    sub_counters = {sub: Counter() for sub in SUBCORPUS_DIRS}
    sub_totals = defaultdict(int)
    corpus_counter = Counter()
    corpus_total = 0

    report = []
    missing_files = []

    for sub, dirpath in SUBCORPUS_DIRS.items():
        if not dirpath.exists():
            print(f"Папка не найдена: {dirpath}")
            continue
        for txt in sorted(dirpath.glob("*.txt")):
            doc_id = txt.stem
            tokens = tokenize(txt.read_text(encoding="utf-8"))
            if not tokens:
                print(f"ПУСТО: {txt}")
                continue

            c = Counter(tokens)
            write_freq_list(OUT_DIR / sub / f"{doc_id}.tsv", c, len(tokens))

            sub_counters[sub].update(c)
            sub_totals[sub] += len(tokens)
            corpus_counter.update(c)
            corpus_total += len(tokens)

            hapax = sum(1 for v in c.values() if v == 1)
            report.append([sub, doc_id, len(tokens), len(c), hapax])

    # Сводные списки по подкорпусам
    for sub, c in sub_counters.items():
        if c:
            write_freq_list(OUT_DIR / f"{sub}_all.tsv", c, sub_totals[sub])

    # Общий по корпусу
    if corpus_counter:
        write_freq_list(OUT_DIR / "corpus_all.tsv", corpus_counter, corpus_total)

    # Отчёт
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, delimiter="\t")
        writer.writerow(["subcorpus", "doc_id", "tokens", "unique_forms", "hapax"])
        writer.writerows(report)

    print("\n=== ИТОГИ ===")
    for sub in SUBCORPUS_DIRS:
        n = sum(1 for r in report if r[0] == sub)
        if n:
            print(f"{sub}: {n} памятников, токенов {sub_totals[sub]}, "
                  f"уникальных форм {len(sub_counters[sub])}")
    print(f"Всего: токенов {corpus_total}, уникальных форм {len(corpus_counter)}")
    print(f"\nФайлы: {OUT_DIR}/<subcorpus>/<doc_id>.tsv")
    print(f"Сводные: {OUT_DIR}/insular_all.tsv, {OUT_DIR}/continental_all.tsv, "
          f"{OUT_DIR}/corpus_all.tsv")
    print(f"Отчёт: {REPORT_PATH}")


if __name__ == "__main__":
    main()