#!/usr/bin/env python3
"""Fingerprint-distance histogram — Universal Rebalancer open question 1.

Question: is the distance between modded defs and vanilla defs BIMODAL?
If copy-pasted derivatives pile up at ~0 and everything else sits far away,
the fingerprint tolerance lives in the gap and needs no tuning. If there is
no gap, the copy-paste premise is weak and the fingerprint tier is in doubt.

Pure offline XML parse. Does not run the game and does not apply
PatchOperations -- see LIMITATIONS at the bottom of the report.

  python3 fingerprint_histogram.py [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
DEFAULT_RW = HOME / ".local/share/Steam/steamapps/common/RimWorld"
DEFAULT_WORKSHOP = HOME / ".local/share/Steam/steamapps/workshop/content/294100"
DEFAULT_CONFIG = (
    HOME / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml"
)
GAME_VERSION = "1.6"
CORE_PACKAGE_ID = "ludeon.rimworld"

# Levers -- what the mod would actually patch. Not part of the fingerprint.
LEVER_TAGS = {"costList", "costStuffCount", "workToBuild", "researchPrerequisites"}

# Lever-valued entries that live INSIDE statBases. These must never enter the
# identity fingerprint: divergence here is the signal being detected, not
# evidence against a match. Including them makes the matcher worse at exactly
# the items it most needs to catch.
LEVER_STATS = {
    "WorkToBuild",
    "WorkToMake",
    "MarketValue",
    "SellPriceFactor",
    "RoyalFavorValue",
}


# --------------------------------------------------------------------------
# XML loading
# --------------------------------------------------------------------------


def read_xml(path: Path):
    """Parse one def file, tolerating the encoding and syntax crimes mods commit."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return ET.fromstring(raw.decode(enc))
        except (UnicodeDecodeError, ET.ParseError):
            continue
    return None


def def_files(mod_root: Path):
    """Def XML files RimWorld would load for this mod at GAME_VERSION.

    Ignores LoadFolders.xml -- root, versioned, and Common folders cover
    the overwhelming majority of mods.
    """
    out = []
    for sub in ("", GAME_VERSION, "Common"):
        defs_dir = (mod_root / sub / "Defs") if sub else (mod_root / "Defs")
        if defs_dir.is_dir():
            out.extend(sorted(defs_dir.rglob("*.xml")))
    return out


def package_id_of(mod_root: Path) -> str | None:
    about = mod_root / "About" / "About.xml"
    if not about.is_file():
        return None
    root = read_xml(about)
    if root is None:
        return None
    node = root.find("packageId")
    if node is None or not node.text:
        return None
    return node.text.strip().lower()


def active_mod_ids(config_path: Path) -> list[str]:
    root = read_xml(config_path)
    if root is None:
        sys.exit(f"cannot read ModsConfig at {config_path}")
    node = root.find("activeMods")
    if node is None:
        sys.exit("ModsConfig has no <activeMods>")
    return [li.text.strip().lower() for li in node.findall("li") if li.text]


def resolve_mod_folders(rw_dir: Path, workshop_dir: Path, active: list[str]):
    """packageId -> folder, for active mods only, honouring load order."""
    index: dict[str, Path] = {}
    for base in (workshop_dir, rw_dir / "Mods"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            pid = package_id_of(child)
            # Local Mods/ folders win over Workshop copies of the same mod.
            if pid and (pid not in index or base.name == "Mods"):
                index[pid] = child

    ordered, missing = [], []
    for pid in active:
        if pid == CORE_PACKAGE_ID:
            continue
        if pid in index:
            ordered.append((pid, index[pid]))
        else:
            missing.append(pid)
    return ordered, missing


# --------------------------------------------------------------------------
# Def inheritance (ParentName / Name / Abstract)
# --------------------------------------------------------------------------


def merge_inherited(child: ET.Element, parent: ET.Element) -> None:
    """RimWorld-ish inheritance: parent nodes fill gaps, child always wins.

    Approximation of XmlInheritance: recurse into scalar-ish nodes, let the
    child replace list nodes wholesale. Good enough to recover statBases and
    comps, which is all the fingerprint needs.
    """
    existing = {c.tag: c for c in child}
    for pnode in parent:
        if pnode.get("Inherit", "").lower() == "false":
            continue
        cnode = existing.get(pnode.tag)
        if cnode is None:
            child.append(copy_element(pnode))
            continue
        if any(g.tag == "li" for g in pnode) or any(g.tag == "li" for g in cnode):
            continue  # child's list replaces parent's
        merge_inherited(cnode, pnode)


def copy_element(node: ET.Element) -> ET.Element:
    clone = ET.Element(node.tag, dict(node.attrib))
    clone.text = node.text
    for kid in node:
        clone.append(copy_element(kid))
    return clone


def resolve_all(nodes: list[ET.Element], by_name: dict[str, ET.Element]) -> None:
    """Flatten ParentName chains in place, deepest ancestor first."""
    done: set[int] = set()

    def resolve(node: ET.Element, chain: set[str]) -> None:
        if id(node) in done:
            return
        done.add(id(node))
        pname = node.get("ParentName")
        if not pname or pname in chain:
            return
        parent = by_name.get(pname)
        if parent is None:
            return
        resolve(parent, chain | {pname})
        merge_inherited(node, parent)

    for node in nodes:
        resolve(node, set())


# --------------------------------------------------------------------------
# Fingerprint extraction
# --------------------------------------------------------------------------

NUM = re.compile(r"^-?\d+(\.\d+)?$")


def as_float(text: str | None):
    if text is None:
        return None
    text = text.strip()
    return float(text) if NUM.match(text) else None


def extract(node: ET.Element, source: str) -> dict | None:
    defname_node = node.find("defName")
    if defname_node is None or not defname_node.text:
        return None

    stat_node = node.find("statBases")
    stats, levers = {}, {}
    if stat_node is not None:
        for s in stat_node:
            val = as_float(s.text)
            if val is None:
                continue
            (levers if s.tag in LEVER_STATS else stats)[s.tag] = val
    if not stats:
        return None

    comps = []
    comps_node = node.find("comps")
    if comps_node is not None:
        for li in comps_node.findall("li"):
            cls = li.get("Class")
            if cls:
                comps.append(cls)

    cost = {}
    cost_node = node.find("costList")
    if cost_node is not None:
        for c in cost_node:
            val = as_float(c.text)
            if val is not None:
                cost[c.tag] = val

    def text_of(tag):
        n = node.find(tag)
        return n.text.strip() if n is not None and n.text else None

    return {
        "defName": defname_node.text.strip(),
        "defType": node.tag,
        "source": source,
        "label": text_of("label"),
        "thingClass": text_of("thingClass"),
        "designationCategory": text_of("designationCategory"),
        "stats": stats,
        "statKeys": frozenset(stats),
        "levers": levers,
        "comps": frozenset(comps),
        "costList": cost,
        "costStuffCount": as_float(text_of("costStuffCount")),
        "workToBuild": as_float(text_of("workToBuild")),
    }


def serialise(d: dict) -> dict:
    out = dict(d)
    out["statKeys"] = sorted(d["statKeys"])
    out["comps"] = sorted(d["comps"])
    return out


def collect(files, source, all_nodes, by_name, stats_counter):
    for path in files:
        root = read_xml(path)
        if root is None:
            stats_counter["unparseable_files"] += 1
            continue
        stats_counter["files"] += 1
        for node in root:
            if not isinstance(node.tag, str):
                continue
            stats_counter["def_nodes"] += 1
            name = node.get("Name")
            if name:
                by_name[name] = node
            all_nodes.append((node, source))


# --------------------------------------------------------------------------
# Distance
# --------------------------------------------------------------------------


def stat_distance(a: dict, b: dict) -> float:
    """Max relative deviation across the (identical) stat key sets."""
    worst = 0.0
    for key, av in a["stats"].items():
        bv = b["stats"][key]
        if av == bv:
            continue
        denom = max(abs(bv), 0.01)
        worst = max(worst, abs(av - bv) / denom)
    return worst


BINS = [
    ("exactly 0", 0.0, 0.0),
    ("(0, 0.005]", 0.0, 0.005),
    ("(0.005, 0.01]", 0.005, 0.01),
    ("(0.01, 0.02]", 0.01, 0.02),
    ("(0.02, 0.05]", 0.02, 0.05),
    ("(0.05, 0.10]", 0.05, 0.10),
    ("(0.10, 0.25]", 0.10, 0.25),
    ("(0.25, 0.50]", 0.25, 0.50),
    ("(0.50, 1.00]", 0.50, 1.00),
    ("> 1.00", 1.00, float("inf")),
]


def bin_of(d: float) -> str:
    for label, lo, hi in BINS:
        if lo == hi == 0.0:
            if d == 0.0:
                return label
        elif lo < d <= hi:
            return label
    return BINS[-1][0]


def ascii_hist(counter: Counter, total: int, width: int = 46) -> list[str]:
    peak = max(counter.values(), default=0)
    lines = []
    for label, _, _ in BINS:
        n = counter.get(label, 0)
        bar = "#" * int(round(width * n / peak)) if peak else ""
        pct = (100.0 * n / total) if total else 0.0
        lines.append(f"  {label:>14}  {n:6d}  {pct:5.1f}%  {bar}")
    return lines


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def load_corpus(args):
    """Parse the whole active modlist. Returns (vanilla, modded, meta)."""
    counters = Counter()
    all_nodes: list[tuple[ET.Element, str]] = []
    by_name: dict[str, ET.Element] = {}

    core_defs_dir = args.rimworld / "Data" / "Core" / "Defs"
    if not core_defs_dir.is_dir():
        sys.exit(f"no Core defs at {core_defs_dir}")
    collect(sorted(core_defs_dir.rglob("*.xml")), "core", all_nodes, by_name, counters)
    core_node_count = len(all_nodes)
    core_names = dict(by_name)

    active = active_mod_ids(args.mods_config)
    mods, missing = resolve_mod_folders(args.rimworld, args.workshop, active)
    for pid, folder in mods:
        collect(def_files(folder), pid, all_nodes, by_name, counters)

    shadowed = sorted(set(core_names) & {k for k in by_name if by_name[k] is not core_names.get(k)})
    print(
        f"parsed {counters['files']} files "
        f"({counters['unparseable_files']} unparseable), "
        f"{len(all_nodes)} def nodes, {len(mods)} mods "
        f"({len(missing)} active mods not found on disk); "
        f"{len(shadowed)} Core abstract Names shadowed by mods: {shadowed}",
        file=sys.stderr,
    )

    # Resolve Core against a Core-only Name index. The snapshot must be the
    # pristine vanilla baseline; a mod redefining a Core abstract parent would
    # otherwise leak its values into what we call "vanilla".
    resolve_all([n for n, _ in all_nodes[:core_node_count]], core_names)
    resolve_all([n for n, _ in all_nodes[core_node_count:]], by_name)

    vanilla: list[dict] = []
    modded: list[dict] = []
    for idx, (node, source) in enumerate(all_nodes):
        if node.get("Abstract", "").lower() == "true":
            continue
        fp = extract(node, source)
        if fp is None:
            continue
        (vanilla if idx < core_node_count else modded).append(fp)

    core_defnames = {d["defName"] for d in vanilla}
    overrides = [d for d in modded if d["defName"] in core_defnames]
    modded = [d for d in modded if d["defName"] not in core_defnames]

    meta = {
        "files": counters["files"],
        "unparseable": counters["unparseable_files"],
        "active_listed": len(active),
        "mods_resolved": len(mods),
        "mods_missing": len(missing),
        "overrides": len(overrides),
    }
    return vanilla, modded, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out")
    ap.add_argument("--epsilon", type=float, default=0.02)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    vanilla, modded, meta = load_corpus(args)
    counters = Counter(files=meta["files"], unparseable_files=meta["unparseable"])
    active = range(meta["active_listed"])
    mods = range(meta["mods_resolved"])
    missing = range(meta["mods_missing"])
    overrides = range(meta["overrides"])

    corpus_path = args.out / "corpus.json"
    corpus_path.write_text(
        json.dumps(
            {
                "vanilla": [serialise(d) for d in vanilla],
                "modded": [serialise(d) for d in modded],
                "meta": meta,
            }
        )
    )

    # Index vanilla by stat key set -- makes matching an O(1) lookup.
    by_keyset: dict[frozenset, list[dict]] = defaultdict(list)
    for d in vanilla:
        by_keyset[d["statKeys"]].append(d)

    rows = []
    no_match = 0
    for m in modded:
        candidates = by_keyset.get(m["statKeys"])
        if not candidates:
            no_match += 1
            continue
        scored = sorted((stat_distance(m, v), v["defName"], v) for v in candidates)
        dist, _, best = scored[0]
        tight = [s for s in scored if s[0] <= args.epsilon]
        rows.append(
            {
                "modded_defName": m["defName"],
                "modded_label": m["label"] or "",
                "source_mod": m["source"],
                "defType": m["defType"],
                "vanilla_defName": best["defName"],
                "vanilla_label": best["label"] or "",
                "distance": round(dist, 6),
                "bin": bin_of(dist),
                "n_stat_keys": len(m["statKeys"]),
                "n_candidates": len(candidates),
                "n_tight_matches": len(tight),
                "comps_subset": best["comps"].issubset(m["comps"]),
                "comps_overlap": len(best["comps"] & m["comps"]),
                "n_comps_vanilla": len(best["comps"]),
                "n_comps_modded": len(m["comps"]),
                "modded_thingClass": m["thingClass"] or "",
                "vanilla_thingClass": best["thingClass"] or "",
                "same_thingClass": m["thingClass"] == best["thingClass"],
                "modded_desigCat": m["designationCategory"] or "",
                "vanilla_desigCat": best["designationCategory"] or "",
                "same_desigCat": m["designationCategory"] == best["designationCategory"],
                "cost_match": m["costList"] == best["costList"] and bool(m["costList"]),
                "has_cost": bool(m["costList"]) or m["costStuffCount"] is not None,
                "modded_cost": json.dumps(m["costList"], sort_keys=True),
                "vanilla_cost": json.dumps(best["costList"], sort_keys=True),
            }
        )

    rows.sort(key=lambda r: (r["distance"], r["modded_defName"]))

    csv_path = args.out / "fingerprint_pairs.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["modded_defName"])
        writer.writeheader()
        writer.writerows(rows)

    # ---- report ----------------------------------------------------------
    dists = [r["distance"] for r in rows]
    hist = Counter(r["bin"] for r in rows)
    rich = [r for r in rows if r["n_stat_keys"] >= 4]
    thin = [r for r in rows if r["n_stat_keys"] < 4]
    passing = [r for r in rows if r["distance"] <= args.epsilon]
    passing_gated = [r for r in passing if r["comps_subset"]]
    ambiguous = [r for r in passing_gated if r["n_tight_matches"] > 1]

    tight_mass = sum(1 for d in dists if d <= args.epsilon)
    mid_mass = sum(1 for d in dists if args.epsilon < d <= 0.25)

    out = []
    w = out.append
    w("=" * 72)
    w("FINGERPRINT DISTANCE HISTOGRAM — Universal Rebalancer open question 1")
    w("=" * 72)
    w("")
    w(f"RimWorld       {args.rimworld}")
    w(f"active mods    {len(active)} listed, {len(mods)} resolved on disk, {len(missing)} missing")
    w(f"files parsed   {counters['files']} ({counters['unparseable_files']} unparseable)")
    w("")
    w("POPULATION (defs carrying at least one numeric statBases entry)")
    w(f"  vanilla (Core)                  {len(vanilla):6d}")
    w(f"  modded, new defNames            {len(modded):6d}")
    w(f"  modded, overriding a vanilla def{len(overrides):6d}   (excluded)")
    w("")
    w("STAGE 1 — stat key-set match (the comparability gate)")
    w(f"  modded defs with >=1 vanilla def sharing an identical stat key set")
    pct = 100.0 * len(rows) / len(modded) if modded else 0.0
    w(f"    {len(rows):6d} / {len(modded)}  ({pct:.1f}%)")
    w(f"  modded defs with no key-set match at all: {no_match}")
    w("")
    w("STAGE 2 — distance to nearest key-set-matching vanilla def")
    w(f"  (max relative deviation across stat values; n = {len(rows)})")
    w("")
    w("  ALL")
    out.extend(ascii_hist(hist, len(rows)))
    w("")
    w(f"  RICH FINGERPRINTS (>=4 stat keys, n={len(rich)})")
    out.extend(ascii_hist(Counter(r["bin"] for r in rich), len(rich)))
    w("")
    w(f"  THIN FINGERPRINTS (<4 stat keys, n={len(thin)})")
    out.extend(ascii_hist(Counter(r["bin"] for r in thin), len(thin)))
    w("")
    w("BIMODALITY")
    w(f"  tight   d <= {args.epsilon}          {tight_mass:6d}  ({100.0*tight_mass/len(rows):5.1f}%)")
    w(f"  valley  {args.epsilon} < d <= 0.25      {mid_mass:6d}  ({100.0*mid_mass/len(rows):5.1f}%)")
    w(f"  far     d > 0.25             {len(rows)-tight_mass-mid_mass:6d}"
      f"  ({100.0*(len(rows)-tight_mass-mid_mass)/len(rows):5.1f}%)")
    w("")
    w("  A deep valley means the tolerance sits in a gap and needs no tuning.")
    w("  A flat or rising valley means there is no natural copy-paste population.")
    w("")
    w(f"STAGE 3 — comp-subset gate, applied to the d <= {args.epsilon} population")
    w(f"  tight matches                        {len(passing):6d}")
    w(f"  ...also passing vanilla comps subset {len(passing_gated):6d}")
    if passing:
        w(f"  gate rejects                         {len(passing)-len(passing_gated):6d}"
          f"  ({100.0*(len(passing)-len(passing_gated))/len(passing):.1f}%)")
    w(f"  ...of which ambiguous (>1 tight match){len(ambiguous):6d}")
    w("")
    w("TOP SOURCE MODS AMONG AUTO-MAPPABLE PAIRS")
    for pid, n in Counter(r["source_mod"] for r in passing_gated).most_common(15):
        w(f"  {n:5d}  {pid}")
    w("")
    w("SAMPLE — 40 auto-mappable pairs, hand-check these for precision")
    w(f"  {'modded':<42} {'->':2} {'vanilla':<24} {'d':>7}")
    for r in passing_gated[:40]:
        left = f"{r['modded_label'] or r['modded_defName']} [{r['source_mod']}]"
        w(f"  {left[:42]:<42} -> {(r['vanilla_label'] or r['vanilla_defName'])[:24]:<24}"
          f" {r['distance']:7.4f}")
    w("")
    w("LIMITATIONS")
    w("  - PatchOperations are NOT applied. Raw XML only, so a rebalance mod's")
    w("    changes to vanilla are absent. That is fine for the bimodality")
    w("    question but means these are not the mod's real runtime numbers.")
    w("  - LoadFolders.xml ignored; root, 1.6 and Common def folders only.")
    w("  - Inheritance is an approximation of RimWorld's XmlInheritance.")
    w("  - No DLC installed on this machine, so the vanilla side is Core only.")
    w("")
    w(f"full pair list: {csv_path}")

    report = "\n".join(out)
    (args.out / "report.txt").write_text(report + "\n")
    (args.out / "summary.json").write_text(
        json.dumps(
            {
                "vanilla_defs": len(vanilla),
                "modded_defs": len(modded),
                "keyset_matched": len(rows),
                "histogram": dict(hist),
                "epsilon": args.epsilon,
                "tight": tight_mass,
                "valley": mid_mass,
                "far": len(rows) - tight_mass - mid_mass,
                "comp_gated": len(passing_gated),
                "ambiguous": len(ambiguous),
            },
            indent=2,
        )
        + "\n"
    )
    print(report)


if __name__ == "__main__":
    main()
