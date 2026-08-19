#!/usr/bin/env python3
"""What rule is a materials mod actually expressing?

Reframe: forget balance. A materials mod says "things like X should also
need copper". If that intent is a derivable RULE rather than ad-hoc
per-item edits, it can be applied to every content mod's defs directly --
no analogue matching required.

This applies one mod's patches to the combined def document and reports
every costList it changed, grouped by the signature of what was added,
with the ratio of each added material to the def's pre-existing cost.
Constant ratios within a group = a rule. Scattered ratios = hand-tuning.

  python3 mod_rule.py mopolita.bame.morematerials
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from lxml import etree

sys.path.insert(0, str(Path(__file__).parent))
from who_patched import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_RW,
    DEFAULT_WORKSHOP,
    active_mod_ids,
    apply_op,
    read,
    resolve_mods,
    select,
    xml_files,
)


def cost_of(node):
    e = node.find("costList")
    if e is None:
        return None
    out = {}
    for c in e:
        try:
            out[c.tag] = float((c.text or "").strip())
        except ValueError:
            pass
    return out


def build_doc(rw, workshop, config):
    active = active_mod_ids(config)
    mods = resolve_mods(rw, workshop, active)
    doc = etree.Element("Defs")
    src = {}
    for path in sorted((rw / "Data" / "Core" / "Defs").rglob("*.xml")):
        root = read(path)
        if root is None:
            continue
        for n in root:
            if isinstance(n.tag, str):
                doc.append(n)
                dn = n.findtext("defName")
                if dn:
                    src[dn] = "core"
    for pid, folder in mods:
        for path in xml_files(folder, "Defs"):
            root = read(path)
            if root is None:
                continue
            for n in root:
                if isinstance(n.tag, str):
                    doc.append(n)
                    dn = n.findtext("defName")
                    if dn:
                        src.setdefault(dn, pid)
    return etree.ElementTree(doc), mods, set(active), src


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packageId")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()

    tree, mods, active_ids, src = build_doc(args.rimworld, args.workshop, args.mods_config)
    target = next((f for pid, f in mods if pid == args.packageId), None)
    if target is None:
        sys.exit(f"{args.packageId} not active or not found")

    # Snapshot every costList in the document.
    nodes = select(tree, "/Defs/*[defName]")
    before = {}
    for n in nodes:
        dn = n.findtext("defName")
        c = cost_of(n)
        if dn and c is not None:
            before[dn] = c

    unhandled = []
    for path in xml_files(target, "Patches"):
        root = read(path)
        if root is None:
            continue
        for op in root:
            if isinstance(op.tag, str):
                apply_op(tree, op, active_ids, unhandled)

    changed = []
    for n in select(tree, "/Defs/*[defName]"):
        dn = n.findtext("defName")
        if not dn:
            continue
        after = cost_of(n)
        if after is None:
            continue
        b = before.get(dn)
        if b is None or b == after:
            continue
        added = {k: v for k, v in after.items() if k not in b}
        raised = {k: (b[k], v) for k, v in after.items() if k in b and b[k] != v}
        removed = {k: v for k, v in b.items() if k not in after}
        changed.append(
            {
                "defName": dn,
                "defType": n.tag,
                "source": src.get(dn, "?"),
                "desig": n.findtext("designationCategory") or "",
                "before": b,
                "added": added,
                "raised": raised,
                "removed": removed,
            }
        )

    print("=" * 76)
    print(f"RULE ANALYSIS — {args.packageId}")
    print("=" * 76)
    print(f"\ncostLists changed: {len(changed)}")
    print(f"targets by source mod: {dict(Counter(c['source'] for c in changed))}")
    print(f"targets by def type:   {dict(Counter(c['defType'] for c in changed))}")
    print(f"pure additions: {sum(1 for c in changed if c['added'] and not c['raised'] and not c['removed'])}")
    print(f"amount changes: {sum(1 for c in changed if c['raised'])}")
    print(f"removals:       {sum(1 for c in changed if c['removed'])}")

    groups = defaultdict(list)
    for c in changed:
        groups[tuple(sorted(c["added"]))].append(c)

    print(f"\ndistinct added-material signatures: {len(groups)}")
    print("\n" + "=" * 76)
    print("PER-SIGNATURE: is the amount a constant, or proportional to existing cost?")
    print("=" * 76)

    for sig, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if not sig:
            continue
        print(f"\n--- added {' + '.join(sig)}   ({len(members)} defs) ---")
        print(f"    categories: {dict(Counter(m['desig'] or '<none>' for m in members))}")
        for mat in sig:
            amounts = [m["added"][mat] for m in members]
            steel = [m["before"].get("Steel", 0.0) for m in members]
            total = [sum(m["before"].values()) for m in members]
            per_steel = [a / s for a, s in zip(amounts, steel) if s]
            per_total = [a / t for a, t in zip(amounts, total) if t]

            def spread(xs):
                if not xs:
                    return "n/a"
                if len(xs) == 1:
                    return f"{xs[0]:.4f} (n=1)"
                return (f"med {statistics.median(xs):.4f}  "
                        f"min {min(xs):.4f}  max {max(xs):.4f}  "
                        f"cv {statistics.pstdev(xs)/statistics.mean(xs):.2f}")

            print(f"    {mat}:")
            print(f"       absolute      {spread(amounts)}")
            print(f"       per Steel     {spread(per_steel)}")
            print(f"       per totalcost {spread(per_total)}")

        for m in members[:8]:
            print(f"       {m['defName'][:34]:<34} before={m['before']} added={m['added']}")
        if len(members) > 8:
            print(f"       ... and {len(members)-8} more")

    if unhandled:
        print(f"\nunhandled operation classes: {sorted({c for c, _ in unhandled})}")


if __name__ == "__main__":
    main()
