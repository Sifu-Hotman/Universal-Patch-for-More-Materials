#!/usr/bin/env python3
"""How much of the new material, given the recipe? Fit and compare models.

Selection ("which defs get copper") and amount ("how much") are separate
problems. derive_rules.py handles selection. This fits the amount.

Competing explanations for the observed spread:
  - two regimes: wire-like things are 1:1, everything else proportional
  - a floor: any proportional rule rounds up to 1 on a 1-steel recipe,
    which merely LOOKS like 1:1

  python3 amount_model.py mopolita.bame.morematerials
"""

from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mod_rule import build_doc, cost_of  # noqa: E402
from who_patched import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_RW,
    DEFAULT_WORKSHOP,
    apply_op,
    read,
    select,
    xml_files,
)


def score(pairs, predict):
    """pairs = [(steel, actual)]. Returns (median abs rel error, % within 35%)."""
    errs = []
    for steel, actual in pairs:
        p = predict(steel)
        errs.append(abs(p - actual) / max(actual, 1))
    hit = sum(1 for e in errs if e <= 0.35)
    return statistics.median(errs), 100.0 * hit / len(errs)


def fit_power(pairs):
    """Least-squares fit of amount = k * steel^p in log space."""
    import math
    xs = [math.log(s) for s, _ in pairs]
    ys = [math.log(a) for _, a in pairs if a > 0]
    if len(xs) != len(ys) or len(xs) < 3:
        return 1.0, 1.0
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    p = num / den if den else 1.0
    k = math.exp(my - p * mx)
    return k, p


def fit_k(pairs, floor=True):
    """Grid-search the multiplier minimising median relative error."""
    best = (9e9, 0.0)
    for i in range(1, 401):
        k = i / 1000.0
        f = (lambda s, k=k: max(1, round(k * s))) if floor else (lambda s, k=k: round(k * s))
        e, _ = score(pairs, f)
        if e < best[0]:
            best = (e, k)
    return best[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packageId")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()

    tree, mods, active_ids, _ = build_doc(args.rimworld, args.workshop, args.mods_config)
    folder = next((f for pid, f in mods if pid == args.packageId), None)
    if folder is None:
        sys.exit(f"{args.packageId} not active")

    nodes, before = {}, {}
    for n in select(tree, "/Defs/ThingDef[defName]"):
        dn, c = n.findtext("defName"), cost_of(n)
        if dn and c:
            nodes[dn] = n
            before[dn] = c

    unhandled = []
    for path in xml_files(folder, "Patches"):
        root = read(path)
        if root is None:
            continue
        for op in root:
            if isinstance(op.tag, str):
                apply_op(tree, op, active_ids, unhandled)

    data = {}
    for dn, node in nodes.items():
        after = cost_of(node)
        if after is None:
            continue
        for mat, amt in after.items():
            if mat in before[dn]:
                continue
            steel = before[dn].get("Steel")
            if steel:
                data.setdefault(mat, []).append((dn, steel, amt))

    for mat, rows in sorted(data.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 5:
            continue
        rows.sort(key=lambda r: r[1])
        pairs = [(s, a) for _, s, a in rows]
        ratios = [a / s for s, a in pairs]

        print("=" * 76)
        print(f"{mat}   n={len(rows)}")
        print("=" * 76)
        print(f"  ratio spread: min {min(ratios):.3f}  median {statistics.median(ratios):.3f}"
              f"  max {max(ratios):.3f}")
        n_one = sum(1 for r in ratios if r >= 0.999)
        print(f"  at-or-above 1:1 : {n_one}/{len(ratios)}")
        small = [r for s, r in zip([p[0] for p in pairs], ratios) if s <= 3]
        print(f"  recipes with <=3 Steel: {len(small)}"
              f"   (their ratios: {[f'{r:.2f}' for r in small][:8]})")

        med_all = statistics.median(ratios)
        sub = [r for r in ratios if r < 0.999]
        med_sub = statistics.median(sub) if sub else med_all
        k_floor = fit_k(pairs, floor=True)
        pk, pp = fit_power(pairs)
        const = statistics.median(a for _, a in pairs)

        models = [
            ("median ratio, no floor", lambda s: round(med_all * s)),
            ("median ratio + floor 1", lambda s: max(1, round(med_all * s))),
            ("median of r<1 + floor 1  [user proposal]", lambda s: max(1, round(med_sub * s))),
            (f"best-fit k={k_floor:.3f} + floor 1", lambda s: max(1, round(k_floor * s))),
            (f"constant {const:.0f} (ignores recipe size)", lambda s: const),
            (f"power law {pk:.2f} * Steel^{pp:.2f}", lambda s: max(1, round(pk * s ** pp))),
        ]
        print(f"\n  {'model':<44} {'med err':>8} {'within 35%':>11}")
        for name, fn in models:
            e, hit = score(pairs, fn)
            print(f"  {name:<44} {e:>7.2f} {hit:>10.0f}%")

        print(f"\n  medians: all r = {med_all:.3f}   r<1 only = {med_sub:.3f}")
        print("\n  smallest and largest recipes:")
        for dn, s, a in rows[:4] + rows[-4:]:
            print(f"     {dn[:30]:<30} {s:>6.0f} Steel -> {a:>5.0f} {mat}   r={a/s:.3f}")
        print()


if __name__ == "__main__":
    main()
