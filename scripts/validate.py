#!/usr/bin/env python3
"""
Валидация корпуса: согласованность inventory.tsv, metadata.tsv,
tokens_report.tsv, word_forms_report.tsv, variants.tsv и фактических файлов.

Использование:
    python scripts/validate.py                    # обычная проверка
    python scripts/validate.py --strict           # предупреждения = ошибки
    python scripts/validate.py --quiet            # только итог
    python scripts/validate.py --root PATH        # корень проекта

Код выхода:
    0 — всё в порядке (или только предупреждения без --strict)
    1 — есть ошибки (или предупреждения при --strict)

Соглашение 2026-11-18 (decisions.md §3.8, §6.2):
    Поля num_structural_units и unit_type — справочные.
    Анализ плотности структурных единиц не проводится, т.к. единицы
    разных памятников несопоставимы (титул-контейнер vs атомарная
    статья vs глава). Валидатор проверяет unit_type на допустимость
    значения (защита от опечаток), но не требует заполнения
    num_structural_units.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict
from pathlib import Path


# --------------------------------------------------------------- константы

HORIZONS = {
    "horizon_I":   (475, 599),
    "horizon_II":  (600, 700),
    "horizon_III": (700, 900),
    "horizon_IV":  (900, 1087),
}

GENRE_MACRO = {"legislative", "ecclesiastical", "administrative"}
GENRE_SUB = {
    "code", "edict", "capitulary", "decree",
    "treatise", "formula", "treaty", "fragment", "unclear",
}
EDITION_TYPE = {"critical", "translation", "early_print", "compilation", "unclear"}

# unit_type по decisions.md §6.2. Поле справочное (см. шапку файла),
# но значение должно быть из словаря — защита от опечаток.
UNIT_TYPE = {
    "article", "title", "chapter", "paragraph", "fragment", "unclear",
}
# Допустимые unit_type для островных документов (B1 2026-11-09).
# Значения genre_sub (code/treaty/decree/treatise/formula) — не unit_type.
INSULAR_UNIT_TYPE = {"article", "unclear", "fragment"}

TEXT_DIR = {
    "insular": "anglo_saxon",
    "continental": "continental",
}
WORD_FORMS_DIR = {
    "insular": "insular",
    "continental": "continental",
}
REFS_DIR = {
    "insular": "anglo_saxon/refs",
}

EXPECTED_TOKENS = {
    "insular": 43523,
    "continental": 167393,
}
EXPECTED_TOTAL = 210916

FORBIDDEN_NOTES = {"заметка", ""}

SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


# --------------------------------------------------------------- утилиты

def load_tsv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def non_ascii(s: str) -> bool:
    return any(ord(c) > 127 for c in s)


def is_int(s: str) -> bool:
    try:
        int(s)
        return True
    except (TypeError, ValueError):
        return False


class Result:
    def __init__(self):
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)

    def section(self, name: str):
        print(f"\n=== {name} ===")


# --------------------------------------------------------------- проверки

def check_identifiers(inv: list[dict], meta: list[dict], r: Result):
    r.section("IDENTIFIERS")

    inv_ids = {row["doc_id"] for row in inv if row.get("doc_id")}
    meta_ids = {row["doc_id"] for row in meta if row.get("doc_id")}

    only_inv = inv_ids - meta_ids
    only_meta = meta_ids - inv_ids
    if only_inv:
        r.error(f"doc_id только в inventory.tsv ({len(only_inv)}): {sorted(only_inv)[:10]}")
    if only_meta:
        r.error(f"doc_id только в metadata.tsv ({len(only_meta)}): {sorted(only_meta)[:10]}")

    inv_ascii = {row["doc_id"]: row.get("doc_id_ascii") or row["doc_id"] for row in inv}
    meta_ascii = {row["doc_id"]: row.get("doc_id_ascii") or row["doc_id"] for row in meta}
    for doc_id in inv_ids & meta_ids:
        if inv_ascii[doc_id] != meta_ascii[doc_id]:
            r.error(f"{doc_id}: doc_id_ascii различается "
                    f"(inventory={inv_ascii[doc_id]!r}, metadata={meta_ascii[doc_id]!r})")

    seen = defaultdict(list)
    for doc_id, ascii_id in meta_ascii.items():
        seen[ascii_id].append(doc_id)
    for ascii_id, docs in seen.items():
        if len(docs) > 1:
            r.error(f"doc_id_ascii={ascii_id!r} встречается у {len(docs)} документов: {docs}")

    for doc_id, ascii_id in meta_ascii.items():
        if non_ascii(doc_id) and doc_id == ascii_id:
            r.error(f"{doc_id}: не-ASCII doc_id без ascii-алиаса")

    for doc_id, ascii_id in meta_ascii.items():
        if SAFE_ID_RE.fullmatch(doc_id) and doc_id != ascii_id:
            r.warn(f"{doc_id}: скрипто-безопасный doc_id, но doc_id_ascii={ascii_id!r} отличается")

    if not r.errors:
        print(f"  OK: {len(meta_ids)} документов, идентификаторы согласованы")


def check_files(meta: list[dict], root: Path, r: Result):
    r.section("FILES")

    for row in meta:
        doc_id = row.get("doc_id", "")
        ascii_id = row.get("doc_id_ascii") or doc_id
        sub = row.get("subcorpus", "")
        sub_dir = TEXT_DIR.get(sub)
        if not sub_dir:
            r.error(f"{doc_id}: неизвестный subcorpus={sub!r}")
            continue
        p = root / "texts" / sub_dir / f"{ascii_id}.txt"
        if not p.exists():
            r.error(f"{doc_id}: нет файла {p.relative_to(root)}")

    for sub_dir in TEXT_DIR.values():
        d = root / "texts" / sub_dir
        if not d.exists():
            r.warn(f"Папка не найдена: texts/{sub_dir}/")
            continue
        bad = [f.name for f in d.glob("*.txt") if non_ascii(f.stem)]
        for name in bad:
            r.error(f"texts/{sub_dir}/{name}: не-ASCII имя файла")

    for sub, sub_dir in TEXT_DIR.items():
        d = root / "texts" / sub_dir
        if not d.exists():
            continue
        n_txt = len(list(d.glob("*.txt")))
        n_doc = sum(1 for row in meta if row.get("subcorpus") == sub)
        if n_txt != n_doc:
            r.error(f"texts/{sub_dir}/: {n_txt} .txt, а документов {n_doc}")

    for sub, refs_dir_rel in REFS_DIR.items():
        refs_root = root / "texts" / refs_dir_rel
        for row in meta:
            if row.get("subcorpus") != sub:
                continue
            doc_id = row.get("doc_id", "")
            ascii_id = row.get("doc_id_ascii") or doc_id
            p = refs_root / f"{ascii_id}.refs.tsv"
            if not p.exists():
                r.warn(f"{doc_id}: нет {p.relative_to(root)}")

    for row in meta:
        doc_id = row.get("doc_id", "")
        ascii_id = row.get("doc_id_ascii") or doc_id
        sub = row.get("subcorpus", "")
        sub_dir = WORD_FORMS_DIR.get(sub)
        if not sub_dir:
            continue
        p = root / "word_forms" / sub_dir / f"{ascii_id}.tsv"
        if not p.exists():
            r.error(f"{doc_id}: нет файла {p.relative_to(root)}")

    for sub_dir in WORD_FORMS_DIR.values():
        d = root / "word_forms" / sub_dir
        if not d.exists():
            continue
        bad = [f.name for f in d.glob("*.tsv") if non_ascii(f.stem)]
        for name in bad:
            r.error(f"word_forms/{sub_dir}/{name}: не-ASCII имя файла")

    if not r.errors:
        print(f"  OK: файлы на месте, не-ASCII имён нет")


def check_tokens(meta: list[dict], tokens_report: list[dict],
                 word_forms_report: list[dict], r: Result):
    r.section("TOKENS")

    meta_by_ascii = {row.get("doc_id_ascii") or row["doc_id"]: row for row in meta}
    tok_by_ascii = {row["doc_id"]: row for row in tokens_report}
    wf_by_ascii = {row["doc_id"]: row for row in word_forms_report}

    for doc_id, row in meta_by_ascii.items():
        tc = (row.get("token_count") or "").strip()
        if not tc:
            r.warn(f"{doc_id}: token_count пуст в metadata.tsv")
            continue
        if doc_id not in tok_by_ascii:
            r.error(f"{doc_id}: нет в tokens_report.tsv")
            continue
        tt = tok_by_ascii[doc_id].get("tokens_total", "").strip()
        if tc != tt:
            r.error(f"{doc_id}: token_count={tc} ≠ tokens_total={tt}")

    for doc_id, tok_row in tok_by_ascii.items():
        if doc_id not in wf_by_ascii:
            r.error(f"{doc_id}: нет в word_forms_report.tsv")
            continue
        tt = tok_row.get("tokens_total", "").strip()
        wt = wf_by_ascii[doc_id].get("tokens", "").strip()
        if tt != wt:
            r.error(f"{doc_id}: tokens_total={tt} ≠ tokens={wt}")

    for sub, expected in EXPECTED_TOKENS.items():
        actual = sum(int(row["tokens_total"]) for row in tokens_report
                     if row.get("subcorpus") == sub and is_int(row.get("tokens_total", "")))
        if actual != expected:
            r.error(f"{sub}: сумма tokens_total={actual}, ожидается {expected}")

    total = sum(int(row["tokens_total"]) for row in tokens_report
                if is_int(row.get("tokens_total", "")))
    if total != EXPECTED_TOTAL:
        r.error(f"Всего tokens_total={total}, ожидается {EXPECTED_TOTAL}")

    if not r.errors:
        print(f"  OK: {len(tok_by_ascii)} документов, суммы совпадают")


def check_metadata(meta: list[dict], r: Result):
    r.section("METADATA")

    for row in meta:
        doc_id = row.get("doc_id", "")
        sub = row.get("subcorpus", "")

        ds = (row.get("date_start") or "").strip()
        de = (row.get("date_end") or "").strip()
        if not (ds.isdigit() and de.isdigit()):
            r.error(f"{doc_id}: date_start/date_end не числа ({ds!r}/{de!r})")
            continue
        ds_i, de_i = int(ds), int(de)
        if ds_i > de_i:
            r.error(f"{doc_id}: date_start={ds_i} > date_end={de_i}")

        horizon = (row.get("horizon") or "").strip()
        if horizon not in HORIZONS:
            r.error(f"{doc_id}: horizon={horizon!r} не из {sorted(HORIZONS)}")
            continue
        h_start, h_end = HORIZONS[horizon]
        if not (ds_i >= h_start and de_i <= h_end):
            matches = [h for h, (s, e) in HORIZONS.items() if ds_i >= s and de_i <= e]
            if matches:
                r.error(f"{doc_id}: даты {ds_i}-{de_i} не в {horizon}, "
                        f"а в {matches}")
            else:
                r.error(f"{doc_id}: даты {ds_i}-{de_i} не попадают ни в один горизонт")

        pd = (row.get("period_dates") or "").strip()
        expected_pd = f"{h_start}-{h_end}"
        if pd and pd != expected_pd:
            r.error(f"{doc_id}: period_dates={pd!r}, ожидается {expected_pd!r}")

        gm = (row.get("genre_macro") or "").strip()
        if gm not in GENRE_MACRO:
            r.error(f"{doc_id}: genre_macro={gm!r} не из {sorted(GENRE_MACRO)}")

        gs = (row.get("genre_sub") or "").strip()
        if gs not in GENRE_SUB:
            r.error(f"{doc_id}: genre_sub={gs!r} не из {sorted(GENRE_SUB)}")

        # unit_type — справочное поле (decisions.md §3.8, §6.2), но значение
        # должно быть из словаря: защита от опечаток.
        ut = (row.get("unit_type") or "").strip()
        if ut not in UNIT_TYPE:
            r.error(f"{doc_id}: unit_type={ut!r} не из {sorted(UNIT_TYPE)}")
        elif sub == "insular" and ut not in INSULAR_UNIT_TYPE:
            r.error(
                f"{doc_id}: unit_type={ut!r} недопустим для островного "
                f"(ожидается одно из {sorted(INSULAR_UNIT_TYPE)})"
            )

        et = (row.get("edition_type") or "").strip()
        if et not in EDITION_TYPE:
            r.error(f"{doc_id}: edition_type={et!r} не из {sorted(EDITION_TYPE)}")

        hp = (row.get("has_prologue") or "").strip()
        he = (row.get("has_epilogue") or "").strip()
        if hp not in {"yes", "no"}:
            r.error(f"{doc_id}: has_prologue={hp!r} (ожидается yes/no)")
        if he not in {"yes", "no"}:
            r.error(f"{doc_id}: has_epilogue={he!r} (ожидается yes/no)")

        if doc_id == "LawAf_1" and hp != "no":
            r.error(f"LawAf_1: has_prologue={hp!r}, ожидается 'no' "
                    "(пролог вынесен в LawAfEl)")

        # num_structural_units — справочное поле (decisions.md §3.8, §6.2).
        # Заполненность не проверяется: 73 островных + LexRomBur могут быть
        # пустыми. Проверка "nsu < 0" удалена как бессмысленная.

    if not r.errors:
        print(f"  OK: {len(meta)} записей, метаданные валидны")


def check_lexical(meta: list[dict], tokens_report: list[dict],
                 word_forms_report: list[dict], r: Result):
    r.section("LEXICAL DIVERSITY")

    tok_by_ascii = {row["doc_id"]: row for row in tokens_report}
    wf_by_ascii = {row["doc_id"]: row for row in word_forms_report}

    for doc_id, wf in wf_by_ascii.items():
        tt = tok_by_ascii.get(doc_id, {}).get("types", "")
        uf = wf.get("unique_forms", "")
        hapax = wf.get("hapax", "")

        if not (is_int(tt) and is_int(uf) and is_int(hapax)):
            continue

        tt_i, uf_i, hapax_i = int(tt), int(uf), int(hapax)

        if tt_i > uf_i:
            r.error(f"{doc_id}: types={tt_i} > unique_forms={uf_i}")
        if hapax_i > uf_i:
            r.error(f"{doc_id}: hapax={hapax_i} > unique_forms={uf_i}")

    if not r.errors:
        print(f"  OK: типы и hapax согласованы")


def check_warnings(meta: list[dict], r: Result):
    r.section("WARNINGS")

    for row in meta:
        doc_id = row.get("doc_id", "")

        et = (row.get("edition_type") or "").strip()
        if et == "unclear":
            r.warn(f"{doc_id}: edition_type=unclear — издание не определено")

        notes = (row.get("notes") or "").strip()
        if notes in FORBIDDEN_NOTES:
            r.warn(f"{doc_id}: notes-заглушка ({notes!r})")

        # num_structural_units пуст — не предупреждение (decisions.md §3.8, §6.2):
        # поле справочное, в анализе плотности не используется.

    if not r.warnings:
        print(f"  предупреждений нет")


# Проверка variants.tsv (критичен после D1: launch.json использует -V)
def check_variants(root: Path, r: Result):
    r.section("VARIANTS")

    path = root / "variants.tsv"
    if not path.exists():
        r.warn(f"Нет {path.name} в корне (используется -V/--variants)")
        return

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if not reader.fieldnames:
            r.error(f"{path.name}: пустой файл")
            return
        required = {"base_term", "variants"}
        missing = required - set(reader.fieldnames)
        if missing:
            r.error(f"{path.name}: нет колонок {sorted(missing)}")
            return
        has_exact = "exact" in reader.fieldnames
        seen = set()
        n = 0
        for i, row in enumerate(reader, start=2):
            base = (row.get("base_term") or "").strip()
            if not base:
                r.error(f"{path.name}:{i}: пустой base_term")
                continue
            if base in seen:
                r.error(f"{path.name}:{i}: дубль base_term={base!r}")
            seen.add(base)

            raw = (row.get("variants") or "").strip()
            if not raw:
                r.error(f"{path.name}:{i}: {base!r}: пустой variants")
                continue
            parts = [v.strip() for v in raw.split(",") if v.strip()]
            if not parts:
                r.error(f"{path.name}:{i}: {base!r}: variants не разобраны")

            if has_exact:
                ex = (row.get("exact") or "no").strip().lower()
                if ex not in {"yes", "no", "true", "false", "1", "0"}:
                    r.error(
                        f"{path.name}:{i}: {base!r}: exact={ex!r} "
                        "(ожидается yes/no)"
                    )
            n += 1

    if not r.errors:
        print(f"  OK: {n} base_term(s), exact и variants валидны")


# --------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="Валидация корпуса.")
    ap.add_argument("--root", type=Path, default=None,
                    help="Корень проекта (по умолчанию — текущий каталог)")
    ap.add_argument("--strict", action="store_true",
                    help="Предупреждения = ошибки")
    ap.add_argument("--quiet", action="store_true",
                    help="Только итог, без секций")
    args = ap.parse_args()

    root = (args.root or Path.cwd()).resolve()
    if not (root / "inventory.tsv").exists():
        print(f"Ошибка: {root} не корень проекта (нет inventory.tsv).", file=sys.stderr)
        return 2

    inv = load_tsv(root / "inventory.tsv")
    meta = load_tsv(root / "metadata.tsv")
    tokens_report = load_tsv(root / "logs" / "tokens_report.tsv")
    word_forms_report = load_tsv(root / "logs" / "word_forms_report.tsv")

    if not inv:
        print("Ошибка: inventory.tsv пуст или не читается.", file=sys.stderr)
        return 2
    if not meta:
        print("Ошибка: metadata.tsv пуст или не читается.", file=sys.stderr)
        return 2
    if not tokens_report:
        print("Предупреждение: logs/tokens_report.tsv пуст или отсутствует. "
              "Запустите scripts/count_tokens.py.", file=sys.stderr)
    if not word_forms_report:
        print("Предупреждение: logs/word_forms_report.tsv пуст или отсутствует. "
              "Запустите scripts/word_forms.py.", file=sys.stderr)

    r = Result()

    if not args.quiet:
        print(f"Корень: {root}")
        print(f"inventory.tsv: {len(inv)} записей")
        print(f"metadata.tsv:  {len(meta)} записей")
        print(f"tokens_report.tsv:       {len(tokens_report)} записей")
        print(f"word_forms_report.tsv:   {len(word_forms_report)} записей")

    check_identifiers(inv, meta, r)
    check_files(meta, root, r)
    check_metadata(meta, r)
    if tokens_report or word_forms_report:
        check_tokens(meta, tokens_report, word_forms_report, r)
        check_lexical(meta, tokens_report, word_forms_report, r)
    check_warnings(meta, r)
    check_variants(root, r)

    if not args.quiet:
        print()
        print("=== ИТОГ ===")

    n_err = len(r.errors)
    n_warn = len(r.warnings)

    if r.errors:
        print(f"\nОШИБКИ ({n_err}):")
        for e in r.errors:
            print(f"  ✗ {e}")

    if r.warnings:
        print(f"\nПРЕДУПРЕЖДЕНИЯ ({n_warn}):")
        for w in r.warnings:
            print(f"  ! {w}")

    print(f"\nИтого: {n_err} ошибок, {n_warn} предупреждений")

    if n_err == 0:
        if args.strict and n_warn > 0:
            print("Результат: --strict, предупреждения считаются ошибками")
            return 1
        print("Результат: OK")
        return 0
    print("Результат: есть ошибки")
    return 1


if __name__ == "__main__":
    sys.exit(main())