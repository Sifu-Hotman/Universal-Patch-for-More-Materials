#!/usr/bin/env python3
"""Gate ablation over the corpus dumped by fingerprint_histogram.py.

Which combination of structural gates actually isolates real analogues?

Read fingerprint_histogram.py's LEVER_STATS comment first: lever fields live
inside statBases, and including them in the identity test is what made the
first version of this experiment conclude the wrong thing.

Config J is tier A (functional-exact, unique candidate, levers must differ).
Config H is tier B (near-functional, proposals only).

Precision proxy: label-token overlap between the modded and vanilla labels.
The matcher never sees names, so name agreement is an INDEPENDENT signal --
not ground truth, but it cannot be gamed by the features being tested.

  python3 gate_ablation.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

OUT = Path(__file__).parent / "out"

# Spot-check cases: hand-known correct analogues from this modlist.
KNOWN = {
    "VTE_WallMountedCooler": "Cooler",
    "VTE_WallMountedHeater": "Heater",
    "VTE_ACUnitWall": "Cooler",
    "VFES_WallMountedTelevision": "FlatscreenTelevision",
}

STOPWORDS = {
    "a", "an", "the", "of", "and", "with", "for", "in", "on", "mounted",
    "wall", "small", "large", "advanced", "basic", "simple", "improved",
}


def tokens(label: str | None) -> set[str]:
    if not label:
        return set()
    return {t for t in re.findall(r"[a-z]+", label.lower()) if t not in STOPWORDS and len(t) > 2}


def stat_distance(a: dict, b: dict) -> float:
    worst = 0.0
    for key, av in a["stats"].items():
        bv = b["stats"][key]
        if av == bv:
            continue
        worst = max(worst, abs(av - bv) / max(abs(bv), 0.01))
    return worst


def load():
    data = json.loads((OUT / "corpus.json").read_text())
    for group in ("vanilla", "modded"):
        for d in data[group]:
            d["statKeys"] = frozenset(d["statKeys"])
            d["comps"] = frozenset(d["comps"])
            d["costKeys"] = frozenset(d["costList"])
    return data["vanilla"], data["modded"]


# --------------------------------------------------------------------------
# Gates. Each takes (modded, vanilla_candidate) and returns bool.
# --------------------------------------------------------------------------

def g_comps_subset(m, v):
    return v["comps"].issubset(m["comps"])


def g_comps_nontrivial(m, v):
    return len(v["comps"]) >= 2 and v["comps"].issubset(m["comps"])


def g_same_desig(m, v):
    return m["designationCategory"] == v["designationCategory"]


def g_desig_nonempty(m, v):
    return bool(m["designationCategory"]) and m["designationCategory"] == v["designationCategory"]


def g_same_cost_materials(m, v):
    return bool(m["costKeys"]) and m["costKeys"] == v["costKeys"]


def g_same_thingclass(m, v):
    return m["thingClass"] == v["thingClass"]


def lever_gap(m, v) -> float:
    """Max relative divergence across lever stats. 999 if the lever sets differ."""
    keys = set(m["levers"]) | set(v["levers"])
    worst = 0.0
    for k in keys:
        mv, vv = m["levers"].get(k), v["levers"].get(k)
        if mv is None or vv is None:
            return 999.0
        if mv != vv:
            worst = max(worst, abs(mv - vv) / max(abs(vv), 0.01))
    return worst


# (label, gates, dist_cap, margin, unique, require_lever_divergence)
CONFIGS = [
    ("A  d<=0.02 + comps subset",
     [g_comps_subset], 0.02, 0.0, False, False),
    ("B  structural + rank, no distance cap",
     [g_comps_subset, g_same_desig], None, 0.0, False, False),
    ("C  B + margin>=0.05 over runner-up",
     [g_comps_subset, g_same_desig], None, 0.05, False, False),
    ("D  C + comps non-trivial (>=2)",
     [g_comps_nontrivial, g_same_desig], None, 0.05, False, False),
    ("E  C + designationCategory must be non-empty",
     [g_comps_subset, g_desig_nonempty], None, 0.05, False, False),
    ("F  E + identical cost material set",
     [g_comps_subset, g_desig_nonempty, g_same_cost_materials], None, 0.05, False, False),
    ("G  E + same thingClass",
     [g_comps_subset, g_desig_nonempty, g_same_thingclass], None, 0.05, False, False),
    ("H  TIER B: E with loose distance cap d<=0.5",
     [g_comps_subset, g_desig_nonempty], 0.5, 0.05, False, False),
    ("I  functional-exact + gates + unique candidate",
     [g_comps_subset, g_desig_nonempty], 0.001, 0.0, True, False),
    ("J  TIER A: I + levers must actually differ",
     [g_comps_subset, g_desig_nonempty], 0.001, 0.0, True, True),
]


def run(vanilla, modded, gates, dist_cap, margin, unique=False, require_lever=False):
    by_keyset = {}
    for v in vanilla:
        by_keyset.setdefault(v["statKeys"], []).append(v)

    accepted, rejected_ambiguous = [], 0
    for m in modded:
        cands = by_keyset.get(m["statKeys"])
        if not cands:
            continue
        cands = [v for v in cands if all(g(m, v) for g in gates)]
        if dist_cap is not None:
            cands = [v for v in cands if stat_distance(m, v) <= dist_cap]
        if require_lever:
            cands = [v for v in cands if 0 < lever_gap(m, v) < 900]
        if not cands:
            continue
        if unique and len(cands) > 1:
            rejected_ambiguous += 1
            continue
        scored = sorted((stat_distance(m, v), v["defName"], v) for v in cands)
        d1, _, best = scored[0]
        if margin > 0 and len(scored) > 1 and (scored[1][0] - d1) < margin:
            rejected_ambiguous += 1
            continue
        accepted.append({"m": m, "v": best, "d": d1, "n_cands": len(cands)})
    return accepted, rejected_ambiguous


def score(accepted):
    """Independent precision proxy via label-token overlap."""
    hit = miss = unscoreable = 0
    for a in accepted:
        tm, tv = tokens(a["m"]["label"]), tokens(a["v"]["label"])
        if not tm or not tv:
            unscoreable += 1
        elif tm & tv:
            hit += 1
        else:
            miss += 1
    scored = hit + miss
    return hit, miss, unscoreable, (100.0 * hit / scored if scored else 0.0)


def main() -> None:
    if not (OUT / "corpus.json").exists():
        sys.exit("run fingerprint_histogram.py first to produce out/corpus.json")
    vanilla, modded = load()

    lines = []
    w = lines.append
    w("=" * 78)
    w("GATE ABLATION — which gates isolate real analogues?")
    w("=" * 78)
    w("")
    w(f"vanilla defs {len(vanilla)}   modded defs {len(modded)}")
    w("")
    w("  name-overlap %% is an INDEPENDENT precision proxy: the matcher never")
    w("  reads labels, so label agreement is evidence it found a real analogue.")
    w("  It undercounts (rose quartz tile / granite tile share nothing), so read")
    w("  it as a floor, not a score.")
    w("")
    header = f"  {'config':<46} {'kept':>5} {'ambig':>6} {'name-ok':>8} {'flagship':>9}"
    w(header)
    w("  " + "-" * (len(header) - 2))

    best_config = None
    for name, gates, cap, margin, uniq, req_lev in CONFIGS:
        accepted, ambig = run(vanilla, modded, gates, cap, margin, uniq, req_lev)
        hit, miss, unscoreable, pct = score(accepted)
        found = {a["m"]["defName"]: a["v"]["defName"] for a in accepted}
        flag = sum(1 for k, want in KNOWN.items() if found.get(k) == want)
        w(f"  {name:<46} {len(accepted):>5} {ambig:>6} {pct:>7.1f}% {flag:>6}/{len(KNOWN)}")
        if name.startswith("J"):
            best_config = (name, accepted, ambig)

    w("")
    w("  ambig = rejected because the runner-up was within the margin (abstain)")
    w("")

    # ---- detail on the flagship cases under each config --------------------
    w("=" * 78)
    w("FLAGSHIP CASES (hand-known correct answers)")
    w("=" * 78)
    for name, gates, cap, margin, uniq, req_lev in CONFIGS:
        accepted, _ = run(vanilla, modded, gates, cap, margin, uniq, req_lev)
        found = {a["m"]["defName"]: a for a in accepted}
        bits = []
        for k, want in KNOWN.items():
            a = found.get(k)
            if a is None:
                bits.append(f"{k.split('_')[-1]}:MISS")
            elif a["v"]["defName"] == want:
                bits.append(f"{k.split('_')[-1]}:ok(d={a['d']:.2f})")
            else:
                bits.append(f"{k.split('_')[-1]}:WRONG({a['v']['defName']})")
        w(f"  {name[:2]}  " + "  ".join(bits))
    w("")

    # ---- hand-check sample from the chosen config --------------------------
    name, accepted, ambig = best_config
    accepted.sort(key=lambda a: (a["m"]["source"], a["d"]))
    w("=" * 78)
    w(f"HAND-CHECK SAMPLE — config {name}")
    w("=" * 78)
    w(f"  {len(accepted)} pairs accepted. All shown.")
    w("")
    for a in accepted:
        m, v = a["m"], a["v"]
        tm, tv = tokens(m["label"]), tokens(v["label"])
        mark = "  " if (tm & tv) else "??"
        left = f"{m['label'] or m['defName']}"
        w(f"  {mark} {left[:38]:<38} -> {(v['label'] or v['defName'])[:22]:<22}"
          f" d={a['d']:.2f} [{m['source'][:26]}]")
    w("")
    w("  '??' = no label-token overlap. Check these first; they are where the")
    w("  structural gates and the naming disagree.")

    report = "\n".join(lines)
    (OUT / "gate_ablation.txt").write_text(report + "\n")
    print(report)


if __name__ == "__main__":
    main()
