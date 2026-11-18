#!/usr/bin/env python3
"""
KWIC-конкорданс для корпуса раннесредневековых правовых текстов.

Примеры:
    python scripts/concordance.py "wergeld*" -w 5
    python scripts/concordance.py "si quis" -i -s continental -n 50
    python scripts/concordance.py "^werg[ei]ld\\w*$" -r -i --tsv
    python scripts/concordance.py -V wergeld -i -w 7
    python scripts/concordance.py -V morth -i

Формат вывода по умолчанию:
    doc_id<TAB>ref<TAB>left [node] right

С --tsv:
    doc_id<TAB>ref<TAB>left<TAB>node<TAB>right

Семантика:
    - без -r: '*' = glob (.*), каждый токен матчится целиком (^...$);
    - с -r: фрагменты разделяются пробелом, каждый — регэксп,
      применяемый через re.match (привязка к началу);
    - с -V: base_term берётся из variants.tsv, все варианты объединяются
      в ^(?:v1|v2|...)\\w*$ (см. build_variant_pattern).
"""
import argparse
import sys
from pathlib import Path

from corpus_utils import (
    load_metadata,
    load_doc_tokens_with_pos,
    parse_query,
    find_matches,
    load_variants,
    build_variant_pattern,
)


def main():
    ap = argparse.ArgumentParser(description="KWIC-конкорданс.")
    ap.add_argument("query", nargs="?", default=None,
                    help="токен, фраза или регэксп (не нужен при -V)")
    ap.add_argument("-r", "--regex", action="store_true", help="query — регэксп")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("-w", "--window", type=int, default=5, help="контекст (по умолчанию 5)")
    ap.add_argument("-s", "--subcorpus", choices=["both", "continental", "insular"], default="both")
    ap.add_argument("-n", "--max-hits", type=int, default=100)
    ap.add_argument("-o", "--output", help="файл вывода (по умолчанию stdout)")
    ap.add_argument("--tsv", action="store_true", help="раздельные колонки left/node/right")

    # variants
    ap.add_argument("-V", "--variants", dest="variants_base", metavar="BASE",
                    help="base_term из variants.tsv (расширяет запрос по вариантам орфографии)")
    ap.add_argument("--variants-file", default="variants.tsv",
                    help="путь к variants.tsv относительно --corpus-dir (по умолчанию variants.tsv)")
    ap.add_argument("--variants-exact", action="store_true",
                    help="с -V: только точные варианты, без \\w* суффикса")

    ap.add_argument("--corpus-dir", default=".")
    ap.add_argument("--metadata", default="metadata.tsv")
    args = ap.parse_args()

    # Проверки взаимоисключения
    if args.variants_base and args.query:
        sys.stderr.write("ERR: укажите либо query, либо -V (не оба).\n")
        sys.exit(2)
    if not args.variants_base and not args.query:
        sys.stderr.write("ERR: нужен query или -V.\n")
        sys.exit(2)
    if args.variants_base and args.regex:
        sys.stderr.write("ERR: -V и -r взаимоисключающие.\n")
        sys.exit(2)

    # Построение шаблонов
    if args.variants_base:
        variants_path = Path(args.corpus_dir) / args.variants_file
        variants_map = load_variants(variants_path)
        if args.variants_base not in variants_map:
            sys.stderr.write(
                f"ERR: base_term '{args.variants_base}' не найден в {variants_path}.\n"
            )
            sys.exit(2)
        entry = variants_map[args.variants_base]
        exact = entry["exact"] or args.variants_exact
        pattern, regex_str = build_variant_pattern(
            args.variants_base, entry["variants"],
            ignore_case=args.ignore_case, exact=exact,
        )
        patterns = [pattern]
        sys.stderr.write(f"# variants: {args.variants_base} -> {regex_str}\n")
    else:
        patterns = parse_query(args.query, args.regex, args.ignore_case)
        if not patterns:
            sys.stderr.write("ERR: пустой запрос.\n")
            sys.exit(2)

    metadata = load_metadata(Path(args.corpus_dir) / args.metadata)

    out = (
        open(args.output, "w", encoding="utf-8", newline="")
        if args.output
        else sys.stdout
    )
    try:
        total = 0
        for meta in metadata:
            if args.subcorpus != "both" and meta["subcorpus"] != args.subcorpus:
                continue

            doc_tokens = []
            doc_refs = []
            for ref, tok, _ in load_doc_tokens_with_pos(meta, args.corpus_dir):
                doc_tokens.append(tok)
                doc_refs.append(ref)
            if not doc_tokens:
                continue

            for start, end in find_matches(doc_tokens, patterns):
                if total >= args.max_hits:
                    break
                lo = max(0, start - args.window)
                hi = min(len(doc_tokens), end + 1 + args.window)
                left = " ".join(doc_tokens[lo:start])
                node = " ".join(doc_tokens[start:end + 1])
                right = " ".join(doc_tokens[end + 1:hi])
                ref = doc_refs[start]

                if args.tsv:
                    out.write(f"{meta['doc_id']}\t{ref}\t{left}\t{node}\t{right}\n")
                else:
                    out.write(f"{meta['doc_id']}\t{ref}\t{left} [{node}] {right}\n")
                total += 1

            if total >= args.max_hits:
                break
    finally:
        if args.output:
            out.close()

    sys.stderr.write(f"{total} совпадений.\n" if total else "Совпадений нет.\n")


if __name__ == "__main__":
    main()