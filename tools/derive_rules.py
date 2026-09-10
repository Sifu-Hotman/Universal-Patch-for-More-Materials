#!/usr/bin/env python3
"""Can a handful of categorical rules reproduce a materials mod's per-def edits?

If yes, strategy 1 (per-def, vanilla only) converts to strategy 3
(categorical xpath), and every content mod is covered automatically --
present and future -- with no compat patches and no C#.

Key decomposition: do NOT model the 35 added-material *signatures*. Model
each MATERIAL separately. "Which defs get copper?" is one binary rule over
60 labelled examples; the signatures are just intersections of those rules.

Self-validating: rules are derived from the mod's own edits and scored
against those same edits. No hand labels.

  python3 derive_rules.py mopolita.bame.morematerials
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
from collections import Counter, defaultdict
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


def features(node) -> set[str]:
    """Everything an xpath predicate could plausibly select on."""
    f = set()
    for tag in ("designationCategory", "thingClass"):
        v = node.findtext(tag)
        if v:
            f.add(f"{tag}={v.strip()}")
    comps = node.find("comps")
    if comps is not None:
        for li in comps.findall("li"):
            c = li.get("Class")
            if c:
                f.add(f"comp={c.split('.')[-1]}")
    cl = node.find("costList")
    if cl is not None:
        for c in cl:
            f.add(f"cost={c.tag}")
    sb = node.find("statBases")
    if sb is not None:
        for c in sb:
            f.add(f"stat={c.tag}")
    tc = node.find("thingCategories")
    if tc is not None:
        for c in tc:
            if c.text:
                f.add(f"cat={c.text.strip()}")
    b = node.find("building")
    if b is not None:
        for c in b:
            if (c.text or "").strip().lower() == "true":
                f.add(f"building.{c.tag}")
    return f


def f1(tp, fp, fn):
    if not tp:
        return 0.0
    p, r = tp / (tp + fp), tp / (tp + fn)
    return 2 * p * r / (p + r)


def search(pos_ids, universe, feats, max_terms=2, min_support=2):
    """Best conjunction of features separating pos_ids within universe."""
    counts = Counter()
    for i in pos_ids:
        counts.update(feats[i])
    cands = [f for f, n in counts.items() if n >= min_support]

    best = (0.0, None, 0, 0, 0)
    for k in range(1, max_terms + 1):
        for combo in itertools.combinations(cands, k):
            cs = set(combo)
            sel = {i for i in universe if cs <= feats[i]}
            if not sel:
                continue
            tp = len(sel & pos_ids)
            score = f1(tp, len(sel) - tp, len(pos_ids) - tp)
            if score > best[0]:
                best = (score, combo, tp, len(sel) - tp, len(pos_ids) - tp)
        if best[0] >= 0.98:
            break
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packageId")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--max-terms", type=int, default=2)
    args = ap.parse_args()

    tree, mods, active_ids, src = build_doc(args.rimworld, args.workshop, args.mods_config)
    folder = next((f for pid, f in mods if pid == args.packageId), None)
    if folder is None:
        sys.exit(f"{args.packageId} not active")

    nodes, before, feats = {}, {}, {}
    for n in select(tree, "/Defs/ThingDef[defName]"):
        dn, c = n.findtext("defName"), cost_of(n)
        if dn and c:
            nodes[dn] = n
            before[dn] = c
            feats[dn] = features(n)   # PRE-patch: no leakage

    unhandled = []
    for path in xml_files(folder, "Patches"):
        root = read(path)
        if root is None:
            continue
        for op in root:
            if isinstance(op.tag, str):
                apply_op(tree, op, active_ids, unhandled)

    added = {}
    for dn, node in nodes.items():
        after = cost_of(node)
        if after is None:
            continue
        new = {k: v for k, v in after.items() if k not in before[dn]}
        if new:
            added[dn] = new

    core = {dn for dn in nodes if src.get(dn) == "core"}
    modded = {dn for dn in nodes if src.get(dn) not in ("core", None)}

    print("=" * 78)
    print(f"RULE DERIVATION - {args.packageId}")
    print("=" * 78)
    print(f"\nuniverse: Core ThingDefs with a costList = {len(core)}")
    print(f"          modded ThingDefs with a costList = {len(modded)}")
    print(f"defs given new materials: {len(added)}")

    mats = Counter()
    for a in added.values():
        mats.update(a.keys())
    print(f"distinct materials introduced: {len(mats)}  {dict(mats)}\n")

    print("=" * 78)
    print("PER-MATERIAL RULES  (derived from Core, scored on Core)")
    print("=" * 78)

    total_tp = total_fp = total_fn = 0
    rules = []
    for mat, _ in mats.most_common():
        pos = {dn for dn, a in added.items() if mat in a} & core
        if len(pos) < 2:
            continue
        score, combo, tp, fp, fn = search(pos, core, feats, args.max_terms)
        if combo is None:
            continue
        sel_core = {i for i in core if set(combo) <= feats[i]}
        sel_mod = {i for i in modded if set(combo) <= feats[i]}

        ratios = []
        for dn in pos:
            steel = before[dn].get("Steel")
            if steel:
                ratios.append(added[dn][mat] / steel)
        med = statistics.median(ratios) if ratios else None
        within = sum(1 for r in ratios if med and abs(r - med) <= 0.35 * med)

        total_tp += tp
        total_fp += fp
        total_fn += fn
        rules.append((mat, combo, sel_mod))

        print(f"\n{mat}   ({len(pos)} Core defs received it)")
        print(f"   rule: {' AND '.join(combo)}")
        print(f"   F1 {score:.2f}   hit {tp}  false-positive {fp}  missed {fn}")
        if med:
            print(f"   amount: median {med:.3f} x Steel   "
                  f"({within}/{len(ratios)} within +-35% of median)")
        print(f"   would also select {len(sel_mod)} MODDED defs")
        missed = sorted(pos - sel_core)[:5]
        if missed:
            print(f"   misses: {missed}")

    print("\n" + "=" * 78)
    print("REPRODUCTION OF THE MOD'S OWN EDITS")
    print("=" * 78)
    print(f"  material-assignments hit:             {total_tp}")
    print(f"  false positives (would over-apply):   {total_fp}")
    print(f"  missed (rule set under-applies):      {total_fn}")
    if total_tp + total_fn:
        print(f"  recall {100*total_tp/(total_tp+total_fn):.0f}%   "
              f"precision {100*total_tp/(total_tp+total_fp) if total_tp+total_fp else 0:.0f}%")

    covered = set()
    for _, _, sel_mod in rules:
        covered |= sel_mod
    print(f"\n  distinct MODDED defs the rule set would newly cover: {len(covered)}")
    by_mod = Counter(src.get(d, "?") for d in covered)
    print(f"  spanning {len(by_mod)} content mods; top:")
    for pid, n in by_mod.most_common(12):
        print(f"     {n:4d}  {pid}")


if __name__ == "__main__":
    main()
