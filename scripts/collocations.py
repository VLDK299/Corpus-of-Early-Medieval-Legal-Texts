#!/usr/bin/env python3
"""
Коллокации для корпуса раннесредневековых правовых текстов.

Примеры:
    python scripts/collocations.py "wergeld*" -w 5
    python scripts/collocations.py "si" -s continental --min-freq 5 --top 50
    python scripts/collocations.py "cyning" -w 3 -m mi --tsv
    python scripts/collocations.py -V wergeld -i -w 5
    python scripts/collocations.py "gif" -o coll_gif.tsv

Метрики:
    ll (по умолчанию) — log-likelihood (Dunning 1993);
    mi              — mutual information, log2(O/E);
    tscore          — (O - E) / sqrt(O);
    dice            — 2*O / (f_node + f_coll).

Формула таблицы 2x2:
    O11 = совместные вхождения в окне
    O12 = f_coll - O11
    O21 = total_slots - O11       (все слоты окон минус O11)
    O22 = N - total_slots - f_coll + O11
    E11 = f_coll * total_slots / N
    ...
    LL  = 2*Sum Oi*ln(Oi/Ei)

Если O22 < 0 (узел очень частотный), для этой коллокаты LL = n/a,
остальные метрики выводятся; в stderr — агрегированное предупреждение.

С --tsv:
    На stdout — только TSV-таблица (без служебных строк),
    служебная строка '# node=...' уходит в stderr.
    Удобно для pandas.read_csv(sep="\\t") и Excel.
"""
import argparse
import math
import sys
from collections import Counter
from pathlib import Path

from corpus_utils import (
    load_metadata,
    load_doc_tokens_with_pos,
    parse_query,
    find_matches,
    load_variants,
    build_variant_pattern,
)


def log_likelihood(o11, o12, o21, o22):
    n = o11 + o12 + o21 + o22
    if n == 0:
        return 0.0
    e11 = (o11 + o12) * (o11 + o21) / n
    e12 = (o11 + o12) * (o12 + o22) / n
    e21 = (o21 + o22) * (o11 + o21) / n
    e22 = (o21 + o22) * (o12 + o22) / n
    s = 0.0
    for o, e in ((o11, e11), (o12, e12), (o21, e21), (o22, e22)):
        if o > 0 and e > 0:
            s += o * math.log(o / e)
    return 2.0 * s


def main():
    ap = argparse.ArgumentParser(description="Коллокации.")
    ap.add_argument("node", nargs="?", default=None,
                    help="узел (слово/фраза; '*' как glob; -r для регэкспа; -V для вариантов)")
    ap.add_argument("-r", "--regex", action="store_true")
    ap.add_argument("-i", "--ignore-case", action="store_true")
    ap.add_argument("-w", "--window", type=int, default=5)
    ap.add_argument("-s", "--subcorpus", choices=["both", "continental", "insular"], default="both")
    ap.add_argument("-n", "--min-freq", type=int, default=3,
                    help="мин. частота совместных вхождений")
    ap.add_argument("-m", "--measure", choices=["ll", "mi", "tscore", "dice"], default="ll")
    ap.add_argument("-t", "--top", type=int, default=100)
    ap.add_argument("--min-ll", type=float, default=None,
                    help="отсечка по LL (например, 3.84 = p<0.05)")
    ap.add_argument("-o", "--output")
    ap.add_argument("--tsv", action="store_true",
                    help="чистый TSV на stdout; служебная строка '# node=...' → stderr")

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
    if args.variants_base and args.node:
        sys.stderr.write("ERR: укажите либо node, либо -V (не оба).\n")
        sys.exit(2)
    if not args.variants_base and not args.node:
        sys.stderr.write("ERR: нужен node или -V.\n")
        sys.exit(2)
    if args.variants_base and args.regex:
        sys.stderr.write("ERR: -V и -r взаимоисключающие.\n")
        sys.exit(2)

    # Шаблоны
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
        node_label = f"{args.variants_base} (variants: {regex_str})"
        sys.stderr.write(f"# variants: {node_label}\n")
    else:
        patterns = parse_query(args.node, args.regex, args.ignore_case)
        if not patterns:
            sys.stderr.write("ERR: пустой запрос.\n")
            sys.exit(2)
        node_label = args.node

    metadata = load_metadata(Path(args.corpus_dir) / args.metadata)

    # Первый проход: частоты
    f_coll = Counter()
    f_node = 0
    N = 0
    docs = []
    for meta in metadata:
        if args.subcorpus != "both" and meta["subcorpus"] != args.subcorpus:
            continue
        tokens = [tok for _, tok, _ in load_doc_tokens_with_pos(meta, args.corpus_dir)]
        if not tokens:
            continue
        docs.append(tokens)
        N += len(tokens)
        f_coll.update(tokens)
        for _ in find_matches(tokens, patterns):
            f_node += 1

    if f_node == 0:
        sys.stderr.write(f'Узел "{node_label}" не найден.\n')
        return

    # Второй проход: окна
    co = Counter()
    total_slots = 0
    for tokens in docs:
        for start, end in find_matches(tokens, patterns):
            lo = max(0, start - args.window)
            hi = min(len(tokens), end + 1 + args.window)
            for i in range(lo, hi):
                if start <= i <= end:
                    continue
                co[tokens[i]] += 1
                total_slots += 1

    # Статистика
    rows = []
    n_invalid_ll = 0
    for coll, o11 in co.items():
        if o11 < args.min_freq:
            continue
        fc = f_coll[coll]
        o12 = fc - o11
        o21 = total_slots - o11
        o22 = N - total_slots - fc + o11
        if o22 < 0:
            n_invalid_ll += 1
            ll = float("nan")
        else:
            ll = log_likelihood(o11, o12, o21, o22)
        e11 = (o11 + o12) * (o11 + o21) / N if N else 0.0
        mi_v = math.log2(o11 / e11) if o11 > 0 and e11 > 0 else 0.0
        t_v = (o11 - e11) / math.sqrt(o11) if o11 > 0 else 0.0
        dice_v = 2 * o11 / (f_node + fc) if (f_node + fc) else 0.0
        rows.append({
            "coll": coll,
            "f_obs": o11,
            "f_exp": e11,
            "ll": ll,
            "mi": mi_v,
            "t": t_v,
            "dice": dice_v,
        })

    if n_invalid_ll:
        sys.stderr.write(
            f"WARN: {n_invalid_ll} коллокат(ов) с O22<0 (узел слишком частотный); "
            f"LL для них = n/a, остальные метрики валидны.\n"
        )

    if args.min_ll is not None:
        rows = [r for r in rows if not math.isnan(r["ll"]) and r["ll"] >= args.min_ll]

    def sort_key(r):
        v = r[args.measure]
        if isinstance(v, float) and math.isnan(v):
            return (1, 0.0)
        return (0, -v)

    rows.sort(key=sort_key)
    rows = rows[: args.top]

    out = (
        open(args.output, "w", encoding="utf-8", newline="")
        if args.output
        else sys.stdout
    )
    try:
        header_info = (
            f"# node={node_label!r} f_node={f_node} N={N} "
            f"window={args.window} measure={args.measure}\n"
        )
        if args.tsv:
            sys.stderr.write(header_info)
        else:
            out.write(header_info)
        out.write("collocate\tf_obs\tf_exp\tll\tmi\ttscore\tdice\n")
        for r in rows:
            ll_str = (
                "n/a" if (isinstance(r["ll"], float) and math.isnan(r["ll"]))
                else f"{r['ll']:.2f}"
            )
            out.write(
                f"{r['coll']}\t{r['f_obs']}\t{r['f_exp']:.2f}\t"
                f"{ll_str}\t{r['mi']:.2f}\t{r['t']:.2f}\t{r['dice']:.4f}\n"
            )
    finally:
        if args.output:
            out.close()

    sys.stderr.write(f"{len(rows)} коллокат(ов).\n")


if __name__ == "__main__":
    main()