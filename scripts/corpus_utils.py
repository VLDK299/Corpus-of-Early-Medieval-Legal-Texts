"""
Общие утилиты для corpus-скриптов.

Токенизация: \\w+ (совпадает с count_tokens.py).
Орфография не нормализуется.

Структура путей:
    texts/anglo_saxon/<doc_id>.txt
    texts/anglo_saxon/refs/<doc_id>.refs.tsv
    texts/continental/<doc_id>.txt
"""
import csv
import re
import sys
from pathlib import Path

TOKEN_RE = re.compile(r"\w+", re.UNICODE)


# ---------------------------------------------------------------------------
# Metadata / texts
# ---------------------------------------------------------------------------

def load_metadata(meta_path):
    """Загружает metadata.tsv как список словарей (строки)."""
    rows = []
    with open(meta_path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            rows.append(row)
    return rows


def tokenize(text):
    """Возвращает список (token, start, end)."""
    return [(m.group(), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


def _load_refs_tsv(refs_path):
    """Загружает refs.tsv (source_ref, text). Возвращает список пар или None."""
    if not refs_path.exists():
        return None
    with open(refs_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            return None
        try:
            ref_idx = header.index("source_ref")
            text_idx = header.index("text")
        except ValueError:
            sys.stderr.write(
                f"WARN: {refs_path} без колонок source_ref/text — падаю на номера строк\n"
            )
            return None
        rows = []
        for row in reader:
            if len(row) <= max(ref_idx, text_idx):
                continue
            ref = row[ref_idx].strip()
            text = row[text_idx]
            if not ref or ref.lower() == "none" or not text.strip():
                continue
            rows.append((ref, text))
        return rows


def load_doc_tokens_with_pos(doc_meta, corpus_dir, refs_subdir="refs"):
    """
    Генератор (ref, token, pos) для одного документа.

    Порядок предпочтения:
      1. texts/anglo_saxon/refs/<doc_id>.refs.tsv  → source_ref из файла
      2. texts/anglo_saxon/<doc_id>.txt            → номер строки (1-based)
      3. texts/continental/<doc_id>.txt            → номер строки (1-based)
    """
    subcorpus = doc_meta["subcorpus"]
    doc_id = doc_meta["doc_id"]

    if subcorpus == "insular":
        base = Path(corpus_dir) / "texts" / "anglo_saxon"
        refs_path = base / refs_subdir / f"{doc_id}.refs.tsv"
        txt_path = base / f"{doc_id}.txt"
    elif subcorpus == "continental":
        base = Path(corpus_dir) / "texts" / "continental"
        refs_path = None
        txt_path = base / f"{doc_id}.txt"
    else:
        sys.stderr.write(f"WARN: неизвестный subcorpus={subcorpus} у {doc_id}\n")
        return

    pos = 0

    if refs_path is not None:
        rows = _load_refs_tsv(refs_path)
        if rows is not None:
            for ref, text in rows:
                for tok, _, _ in tokenize(text):
                    yield ref, tok, pos
                    pos += 1
            return

    if txt_path.exists():
        with open(txt_path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for tok, _, _ in tokenize(line):
                    yield f"line {lineno}", tok, pos
                    pos += 1
        return

    sys.stderr.write(
        f"WARN: нет файла для {doc_id} "
        f"(искал {refs_path or '-'} и {txt_path})\n"
    )


def iter_docs(metadata, corpus_dir, subcorpus="both"):
    """Генератор (doc_meta, tokens) где tokens — список строк."""
    for meta in metadata:
        if subcorpus != "both" and meta["subcorpus"] != subcorpus:
            continue
        tokens = [tok for _, tok, _ in load_doc_tokens_with_pos(meta, corpus_dir)]
        yield meta, tokens


# ---------------------------------------------------------------------------
# Query parsing and matching
# ---------------------------------------------------------------------------

def parse_query(query, use_regex=False, ignore_case=False):
    """
    Разбирает поисковый запрос.

    Без -r:
      - пробел разделяет фразу на токены;
      - '*' внутри токена -> '.*' (glob-стиль);
      - каждый токен матчится как полное слово (^...$).

    С -r:
      - пробел разделяет фразу на позиции (по одному регэкспу на токен);
      - каждый фрагмент применяется как регэксп через re.match;
      - чтобы regex-фрагмент матчился целиком, добавьте '$' вручную;
      - литеральный пробел внутри одного регэкспа невозможен
        (токены не содержат пробелов), поэтому '\\s+' между токенами
        не работает — пишите фразу через пробел.

    Возвращает список скомпилированных шаблонов; фраза матчится как
    последовательность (см. find_matches).
    """
    flags = re.IGNORECASE if ignore_case else 0
    parts = query.split()
    if not parts:
        return []
    patterns = []
    for part in parts:
        if use_regex:
            patterns.append(re.compile(part, flags))
        elif "*" in part:
            regex = "^" + ".*".join(re.escape(x) for x in part.split("*")) + "$"
            patterns.append(re.compile(regex, flags))
        else:
            patterns.append(re.compile("^" + re.escape(part) + "$", flags))
    return patterns


def find_matches(tokens, patterns):
    """
    Возвращает (start, end_inclusive) для каждого совпадения.

    Фраза из L шаблонов ищется как L подряд идущих токенов,
    каждый из которых матчится соответствующим шаблоном через .match().
    """
    n = len(tokens)
    L = len(patterns)
    if L == 0:
        return
    for i in range(n - L + 1):
        if all(patterns[j].match(tokens[i + j]) for j in range(L)):
            yield i, i + L - 1


# ---------------------------------------------------------------------------
# Variants (variants.tsv)
# ---------------------------------------------------------------------------

def load_variants(path):
    """
    Загружает variants.tsv.

    Колонки: base_term, variants (через запятую), exact (yes/no; опционально).

    Возвращает dict base_term -> {"variants": [...], "exact": bool}.
    Если файла нет — {}. Если колонки exact нет — exact=False.
    """
    p = Path(path)
    if not p.exists():
        return {}
    variants = {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None or "base_term" not in reader.fieldnames:
            sys.stderr.write(
                f"WARN: {p} без колонки base_term — variants не загружены\n"
            )
            return {}
        for row in reader:
            base = (row.get("base_term") or "").strip()
            raw = (row.get("variants") or "").strip()
            exact_str = (row.get("exact") or "no").strip().lower()
            exact = exact_str in ("yes", "true", "1")
            if not base or not raw:
                continue
            vs = [v.strip() for v in raw.split(",") if v.strip()]
            if vs:
                variants[base] = {"variants": vs, "exact": exact}
    return variants


def build_variant_pattern(base, variants, ignore_case=False, exact=False):
    """
    Строит regex из списка вариантов.

    exact=False: ^(?:v1|v2|...)\\w*$  — с суффиксом (wergeld -> wergeldum).
    exact=True:  ^(?:v1|v2|...)$      — точное совпадение одного из вариантов.

    Возвращает (compiled_pattern, regex_string) для логирования.
    """
    if not variants:
        raise ValueError(f"Пустой список вариантов для {base!r}")
    alt = "|".join(re.escape(v) for v in variants)
    if exact:
        regex = rf"^(?:{alt})$"
    else:
        regex = rf"^(?:{alt})\w*$"
    flags = re.IGNORECASE if ignore_case else 0
    return re.compile(regex, flags), regex