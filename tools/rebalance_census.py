#!/usr/bin/env python3
"""How many mods in this list actually rebalance other mods' defs?

Decides whether this project is one compatibility patch or a lattice.
Applies every mod's patches cumulatively in load order and attributes
each LEVER change to the mod that made it.

Levers, not just costList: a mod that doubles every workToBuild or
re-gates research is a rebalance mod, and counting only costList
undercounts the population badly.

  python3 rebalance_census.py                 # active mods
  python3 rebalance_census.py --all-installed # every mod on disk
"""

from __future__ import annotations

import argparse
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


LEVER_STATS = {"WorkToBuild", "WorkToMake", "MarketValue"}


def levers_of(node):
    """Every price/gating-side field on a def, as a flat comparable dict."""
    out = {}
    e = node.find("costList")
    if e is not None:
        for c in e:
            out[f"cost:{c.tag}"] = (c.text or "").strip()
    for tag in ("costStuffCount",):
        e = node.find(tag)
        if e is not None:
            out[tag] = (e.text or "").strip()
    e = node.find("statBases")
    if e is not None:
        for c in e:
            if c.tag in LEVER_STATS:
                out[f"stat:{c.tag}"] = (c.text or "").strip()
    e = node.find("researchPrerequisites")
    if e is not None:
        out["research"] = ",".join(sorted((c.text or "").strip() for c in e))
    return out or None


def synth_all_installed(rw: Path, workshop: Path) -> list[str]:
    """Every mod on disk, as if the player enabled all of them."""
    from who_patched import package_id_of
    ids = []
    for base in (workshop, rw / "Mods"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir():
                pid = package_id_of(child)
                if pid and pid not in ids:
                    ids.append(pid)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--all-installed", action="store_true")
    args = ap.parse_args()

    if args.all_installed:
        import who_patched
        ids = synth_all_installed(args.rimworld, args.workshop)
        who_patched.active_mod_ids = lambda _p: ids
        import mod_rule
        mod_rule.active_mod_ids = who_patched.active_mod_ids
        print(f"ALL-INSTALLED mode: {len(ids)} mods on disk\n", file=sys.stderr)

    tree, mods, active_ids, src = build_doc(args.rimworld, args.workshop, args.mods_config)

    nodes = {}
    state = {}
    for n in select(tree, "/Defs/*[defName]"):
        dn, c = n.findtext("defName"), levers_of(n)
        if dn and c is not None:
            nodes[dn] = n
            state[dn] = c

    print(f"tracking {len(state)} costLists across {len(mods)} active mods\n", file=sys.stderr)

    report = []
    for pid, folder in mods:
        files = xml_files(folder, "Patches")
        if not files:
            continue
        unhandled = []
        for path in files:
            root = read(path)
            if root is None:
                continue
            for op in root:
                if isinstance(op.tag, str):
                    apply_op(tree, op, active_ids, unhandled)

        changed, added_mats, victims, kinds = [], Counter(), Counter(), Counter()
        for dn, node in nodes.items():
            after = levers_of(node)
            if after is None or after == state[dn]:
                continue
            new = {k[5:] for k in after if k not in state[dn] and k.startswith("cost:")}
            changed.append(dn)
            added_mats.update(new)
            victims[src.get(dn, "?")] += 1
            for k in set(after) | set(state[dn]):
                if after.get(k) != state[dn].get(k):
                    kinds[k.split(":")[0]] += 1
            state[dn] = after

        if changed:
            foreign = sum(v for k, v in victims.items() if k != pid)
            report.append(
                {"pid": pid, "n": len(changed), "foreign": foreign,
                 "victims": victims, "added": added_mats, "kinds": kinds}
            )

    report.sort(key=lambda r: -r["foreign"])

    print("=" * 78)
    print("REBALANCE CENSUS — mods that change LEVERS on defs they do not own")
    print("=" * 78)
    print(f"\n{'mod':<40} {'changed':>7} {'foreign':>7}  {'lever kinds':<22} top targets")
    print("-" * 110)
    for r in report:
        if not r["foreign"]:
            continue
        kinds = ",".join(f"{k}" for k, _ in r["kinds"].most_common(3))
        top = ", ".join(f"{k}:{v}" for k, v in r["victims"].most_common(2))
        print(f"{r['pid']:<40} {r['n']:>7} {r['foreign']:>7}  {kinds:<22} {top[:30]}")

    material_adders = [r for r in report if r["added"]]
    print(f"\n\nmods changing any foreign costList: {sum(1 for r in report if r['foreign'])}")
    print(f"mods introducing NEW materials into existing recipes: {len(material_adders)}")
    print("\n" + "=" * 78)
    print("NEW-MATERIAL INTRODUCERS (the More Materials pattern)")
    print("=" * 78)
    for r in sorted(material_adders, key=lambda r: -r["n"]):
        mats = ", ".join(f"{k}({v})" for k, v in r["added"].most_common(6))
        core = r["victims"].get("core", 0)
        print(f"\n{r['pid']}")
        print(f"   {r['n']} costLists changed, {core} of them vanilla Core")
        print(f"   materials introduced: {mats}")


if __name__ == "__main__":
    main()
