#!/usr/bin/env python3
"""End-to-end prototype of the mod's core logic, offline.

  1. replay a rebalance mod's patches  -> which vanilla defs moved, and how
  2. fingerprint modded defs against ONLY those moved anchors
  3. emit concrete costList proposals for the stranded analogues

Restricting the anchor set to defs the rebalance mod actually touched is
the whole trick: it shrinks the match problem from "all of vanilla" to a
few dozen defs, which is why precision here is far better than the
open-ended ablation in gate_ablation.py.

  python3 propose.py mopolita.bame.morematerials
  python3 propose.py mopolita.bame.morematerials --tier b
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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

OUT = Path(__file__).parent / "out"


def load_corpus():
    data = json.loads((OUT / "corpus.json").read_text())
    for group in ("vanilla", "modded"):
        for d in data[group]:
            d["statKeys"] = frozenset(d["statKeys"])
            d["comps"] = frozenset(d["comps"])
    return data["vanilla"], data["modded"]


def stat_distance(a, b) -> float:
    worst = 0.0
    for k, av in a["stats"].items():
        bv = b["stats"][k]
        if av != bv:
            worst = max(worst, abs(av - bv) / max(abs(bv), 0.01))
    return worst


def gates_ok(m, v) -> bool:
    return (
        v["comps"].issubset(m["comps"])
        and bool(m["designationCategory"])
        and m["designationCategory"] == v["designationCategory"]
    )


# Measured on More Materials: added amount tracks Steel^~0.5, not Steel.
# See amount_model.py -- copper fits 1.30*Steel^0.47, cast iron 2.13*Steel^0.51,
# and turrets at 200/300/350 Steel all receive exactly 10 copper. Linear
# scaling over-adds badly once the target is much larger than the anchor.
SIZE_EXPONENT = 0.5


def scale(anchor_before, anchor_added, target_before):
    """Transfer an additive composition change, sublinear in shared mass.

    Scale by (target mass / anchor mass) ** SIZE_EXPONENT over the materials
    the two recipes have in common. Falls back to total-cost mass when no
    material is shared.
    """
    shared = set(anchor_before) & set(target_before)
    a_mass = sum(anchor_before[k] for k in shared) or sum(anchor_before.values())
    t_mass = sum(target_before[k] for k in shared) or sum(target_before.values())
    if not a_mass:
        return {}
    factor = (t_mass / a_mass) ** SIZE_EXPONENT
    out = {}
    for mat, amount in anchor_added.items():
        scaled = amount * factor
        out[mat] = max(1, round(scaled)) if scaled > 0 else 0
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packageId")
    ap.add_argument("--tier", choices=["a", "b"], default="a")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()

    tree, mods, active_ids, _ = build_doc(args.rimworld, args.workshop, args.mods_config)
    folder = next((f for pid, f in mods if pid == args.packageId), None)
    if folder is None:
        sys.exit(f"{args.packageId} not active")

    before = {}
    for n in select(tree, "/Defs/*[defName]"):
        dn, c = n.findtext("defName"), cost_of(n)
        if dn and c is not None:
            before[dn] = c

    unhandled = []
    for path in xml_files(folder, "Patches"):
        root = read(path)
        if root is None:
            continue
        for op in root:
            if isinstance(op.tag, str):
                apply_op(tree, op, active_ids, unhandled)

    anchors = {}
    for n in select(tree, "/Defs/*[defName]"):
        dn = n.findtext("defName")
        after = cost_of(n)
        if not dn or after is None or dn not in before or before[dn] == after:
            continue
        added = {k: v for k, v in after.items() if k not in before[dn]}
        if added:
            anchors[dn] = {"before": before[dn], "added": added}

    vanilla, modded = load_corpus()
    v_by_name = {d["defName"]: d for d in vanilla}
    anchor_fps = [(dn, v_by_name[dn]) for dn in anchors if dn in v_by_name]

    cap = 0.001 if args.tier == "a" else 0.5
    proposals, ambiguous = [], 0
    for m in modded:
        cands = [
            (stat_distance(m, v), dn, v)
            for dn, v in anchor_fps
            if v["statKeys"] == m["statKeys"] and gates_ok(m, v)
        ]
        cands = [c for c in cands if c[0] <= cap]
        if not cands:
            continue
        cands.sort()
        if len(cands) > 1 and (args.tier == "a" or cands[1][0] - cands[0][0] < 0.05):
            ambiguous += 1
            continue
        d, anchor_name, _ = cands[0]
        tgt_before = before.get(m["defName"])
        if not tgt_before:
            continue
        add = scale(anchors[anchor_name]["before"], anchors[anchor_name]["added"], tgt_before)
        if add:
            proposals.append(
                {"target": m, "anchor": anchor_name, "d": d, "add": add,
                 "tgt_before": tgt_before, "anchor_add": anchors[anchor_name]["added"]}
            )

    print("=" * 78)
    print(f"PROPOSALS — {args.packageId}, tier {args.tier.upper()}")
    print("=" * 78)
    print(f"\nanchors (vanilla defs this mod gave new materials): {len(anchors)}")
    print(f"  of which fingerprintable: {len(anchor_fps)}")
    print(f"modded defs in corpus: {len(modded)}")
    print(f"\nproposals: {len(proposals)}   abstained as ambiguous: {ambiguous}")

    by_anchor = Counter(p["anchor"] for p in proposals)
    print(f"anchors that stranded something: {len(by_anchor)}\n")

    proposals.sort(key=lambda p: (p["anchor"], p["target"]["source"]))
    for p in proposals:
        t = p["target"]
        add = ", ".join(f"{v:g} {k}" for k, v in sorted(p["add"].items()))
        cur = ", ".join(f"{v:g} {k}" for k, v in sorted(p["tgt_before"].items()))
        print(f"  {(t['label'] or t['defName'])[:34]:<34} [{t['source'][:24]:<24}]")
        print(f"      anchor {p['anchor']}  (d={p['d']:.3f})")
        print(f"      now      {cur}")
        print(f"      proposed {cur}, {add}")

    if not proposals:
        print("  (none)")


if __name__ == "__main__":
    main()
