#!/usr/bin/env python3
"""Where is the knee? Cumulative coverage per rule, and the XML for the top ones.

Orders derived rules by marginal modded-def coverage and reports what each
one buys, so the 80/20 cut is a measured number rather than a judgment.
Then emits real, shippable PatchOperation XML for the top-k rules.

Amounts are emitted as size bands, not a ratio: RimWorld xpath cannot
compute sqrt, and bands match how the author actually picks amounts
(a short menu of round numbers). See amount_model.py.

  python3 pareto.py mopolita.bame.morematerials  (emit=1)
"""

from __future__ import annotations

import argparse
import statistics
import sys
import math
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from derive_rules import features, search  # noqa: E402
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

# Finer at the low end on purpose. Coarse bands invert the author's intent:
# with a single 5-30 band, a 10-steel power shower received the same 30 units
# of metal as a 30-steel item, a +273% cost increase, while a 1500-steel
# Rimatomics turbine gained 6%. The measured relationship is sublinear
# (~Steel^0.5), so the bands have to be dense where recipes are cheap.
BANDS = [(0, 3), (3, 8), (8, 15), (15, 30), (30, 60), (60, 120),
         (120, 250), (250, 10_000)]

# statBases entries that are levers, not function. Never part of a fingerprint.
LEVER_STATS = {"WorkToBuild", "WorkToMake", "MarketValue", "SellPriceFactor",
               "RoyalFavorValue"}
SIZE_EXPONENT = 0.5   # measured: added amount tracks ~Steel^0.5, not Steel


# Tokens that appear in almost every thingClass and carry no information.
GENERIC_CLASS_TOKENS = {"Building", "Thing", "Def", "Comp"}


def class_tokens(thing_class):
    """Meaningful CamelCase tokens of a thingClass.

    A code identifier, not a display label: Building_HeaterWithOffset and
    Building_Heater share "Heater", while Building_WorkTable and
    Building_NutrientPasteDispenser share nothing. This is the same technique
    the emitted xpaths already use on comp classes, and it is what stops a
    prosthetics bench being paired with a food dispenser once statBases is out
    of the fingerprint.
    """
    import re
    if not thing_class:
        return set()
    name = thing_class.split(".")[-1]
    return {t for t in re.findall(r"[A-Z][a-z0-9]*", name)
            if t not in GENERIC_CLASS_TOKENS}


def fingerprint(node):
    """Functional identity, weighted the way RimWorld actually stores function.

    Comp PROPERTY VALUES, not statBases, are where a building's function
    lives. A cooler and a heater are distinguished by CompProperties_TempControl
    energyPerSecond, +21 against -21, while their statBases differ only in
    incidental durability numbers. Matching on statBases pairs a wall heater
    with the cooler; matching on comp properties pairs it with the heater.

    statBases is deliberately excluded: MaxHitPoints, Flammability, Mass and
    Beauty describe what a thing is made of and how tough it is, not what it
    does.
    """
    stats = {}
    sb = node.find("statBases")
    if sb is not None:
        for c in sb:
            if c.tag in LEVER_STATS:
                continue
            try:
                stats[c.tag] = float((c.text or "").strip())
            except ValueError:
                pass
    comps = {}
    for li in node.findall("comps/li"):
        cls = li.get("Class")
        if not cls:
            continue
        props = {}
        for c in li:
            if len(c):
                continue
            txt = (c.text or "").strip()
            if txt:
                props[c.tag] = txt
        comps[cls.split(".")[-1]] = props
    return (comps, (node.findtext("designationCategory") or "").strip(),
            class_tokens(node.findtext("thingClass")), stats)


def comps_agree(anchor, target):
    """Anchor's comp classes present in target, and shared properties equal.

    Properties only one side declares are ignored: the vanilla heater sets
    shortCircuitInRain and VTE's wall heater does not, which says nothing
    about whether they are the same kind of device. Properties BOTH declare
    must agree, which is what rejects the cooler at energyPerSecond.
    """
    if not set(anchor) <= set(target):
        return False
    discriminating = 0
    for cls, aprops in anchor.items():
        tprops = target[cls]
        shared = set(aprops) & set(tprops)
        if any(aprops[k] != tprops[k] for k in shared):
            return False
        discriminating += len(shared)
    return discriminating >= 1


# Hand-curated overrides for cases the automatic matcher cannot resolve. Map a
# modded defName to an anchor to FORCE that pairing, or to "" to EXCLUDE it from
# analogue matching (it then falls through to the categorical rules). Every entry
# needs a reason and a deletion condition, or it becomes a permanent substitute
# for fixing the matcher.
OVERRIDES: dict[str, str] = {
    # An electric stonecutter is not a component fabricator, but structure cannot
    # tell them apart: both are Production worktables with a standard power comp,
    # they share the generic {Work,Table} thingClass tokens, and recipes are no
    # help — this def reaches its stone recipes only through a modExtensions-nested
    # inheritRecipesFrom, while both benches also carry unrelated modded recipes
    # via recipeUsers (ammo, grenades). Excluded so it takes the categorical rules,
    # which give a Production + ComponentIndustrial bench cast iron and lead, not
    # the fabricator's brass. Delete if the matcher ever gains a reliable function
    # signal, or if this def stops being a false twin.
    "VFE_TableStonecutterElectric": "",
}


def analogue_ops(nodes, before, added, core, modded):
    """Per-def operations copying a confident vanilla twin's exact signature.

    Categorical rules cannot express a material the author gave to one def and
    withheld from a near-identical one -- the vanilla Cooler got lithium and no
    cast iron, while the rules give its modded twin cast iron and no lithium.
    Where a modded def matches an anchor exactly on function, copy the anchor's
    actual materials instead of guessing.
    """
    fps = {d: fingerprint(n) for d, n in nodes.items()}
    anchors = [d for d in added if d in core]
    out, covered = [], {}
    for m in modded:
        mc, mcat, mtok, ms = fps[m]
        if not mc or not mcat:
            continue
        forced = OVERRIDES.get(m)
        if forced is not None:
            if forced == "":
                continue          # explicitly excluded — structure cannot place it
            if forced not in added:
                continue          # anchor gained nothing; nothing to transfer
            hits = [forced]
        else:
            def eligible(a):
                if fps[a][1] != mcat:
                    return False
                # thingClass tokens veto, never require: plain "Building"
                # yields no tokens and must not disqualify a good match.
                if fps[a][2] and mtok and not (fps[a][2] & mtok):
                    return False
                return True

            # Comp properties only. A statBases fallback was tried and
            # reverted: it recovers VTE_ACUnit but pairs VTE_StandingCooler
            # with the Heater, because their durability stats happen to match
            # while their TempControl energyPerSecond is opposite in sign.
            # Trading one wrong answer for another is not progress, and defs
            # that find no anchor still get covered by the categorical rules.
            hits = [a for a in anchors if eligible(a) and comps_agree(fps[a][0], mc)]
        if len(hits) != 1:
            continue
        a = hits[0]
        a_steel, m_steel = before[a].get("Steel"), before[m].get("Steel")
        if not a_steel or not m_steel:
            continue
        factor = (m_steel / a_steel) ** SIZE_EXPONENT
        vals = {k: max(1, round(v * factor)) for k, v in added[a].items()}
        body = "".join(f"<{k}>{v}</{k}>" for k, v in sorted(vals.items()))
        guard = " and ".join(f"not(costList/{k})" for k in sorted(vals))
        out.append(
            f"  <!-- {m}: {'hand-assigned anchor' if m in OVERRIDES else 'exact functional twin'} {a} -->\n"
            '  <li Class="PatchOperationAdd">\n'
            f'    <xpath>/Defs/ThingDef[defName="{m}" and {guard}]/costList</xpath>\n'
            f"    <value>{body}</value>\n"
            "  </li>"
        )
        covered[m] = (a, vals)
    return out, covered


def fit_power(pairs):
    """Least-squares fit of amount = k * Steel^p in log space."""
    pts = [(s, a) for s, a in pairs if s > 0 and a > 0]
    if len(pts) < 3:
        return None
    xs = [math.log(s) for s, _ in pts]
    ys = [math.log(a) for _, a in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if not den:
        return None
    pw = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den
    return math.exp(my - pw * mx), pw


SHRINK_N0 = 15   # prior strength: a material needs ~15 examples to outweigh the pool


def band_amounts_from_curve(pairs, pooled_exponent=None):
    """Amount per band from the fitted curve, not per-band medians.

    Per-band medians break down once the bands are fine: each holds few
    examples, so a single outlier drives the value and the result stops being
    monotonic -- cast iron read 8, then 30, then 10 across consecutive bands
    because one crematorium sat at r=1.5. Evaluating the curve fitted over ALL
    the data at each band's geometric midpoint uses every observation and
    cannot invert.
    """
    fit = fit_power(pairs)
    if fit is None:
        return None
    k, pw = fit
    # Shrink the exponent toward the pooled value, weighted by sample size.
    # Per-material exponents range 0.37 to 0.77, and the spread tracks n
    # rather than anything physical: the three best-sampled materials sit near
    # 0.5 while every material with n <= 14 drifts high. Bronze fits 0.77 from
    # six points and scores a suspicious 100% in sample, which is two
    # parameters memorising six observations. Left alone that exponent drives
    # the top band's extrapolation.
    if pooled_exponent is not None:
        n = len([1 for st, a in pairs if st > 0 and a > 0])
        pw = (n * pw + SHRINK_N0 * pooled_exponent) / (n + SHRINK_N0)
        # refit k for the new exponent so the curve keeps the data's centroid
        pts = [(st, a) for st, a in pairs if st > 0 and a > 0]
        mx = sum(math.log(st) for st, _ in pts) / len(pts)
        my = sum(math.log(a) for _, a in pts) / len(pts)
        k = math.exp(my - pw * mx)
    out = []
    for lo, hi in BANDS:
        top = min(hi, lo * 4 if lo else 3)      # keep the open band honest
        mid = math.sqrt(max(lo, 0.5) * top)
        out.append(max(1, round(k * mid ** pw)))
    return out


def xpath_term(term: str) -> str:
    kind, _, val = term.partition("=")
    if kind == "comp":
        return f'comps/li[contains(@Class, "{val}")]'
    if kind == "cost":
        return f"costList/{val}"
    if kind == "stat":
        return f"statBases/{val}"
    if kind == "cat":
        return f'thingCategories/li[text()="{val}"]'
    if kind.startswith("building."):
        return f"building/{kind.split('.', 1)[1]}"
    return f'{kind}[text()="{val}"]'


def common_prefix(names) -> str:
    """Shared prefix of a mod's introduced materials, e.g. 'ME_'."""
    names = list(names)
    if len(names) < 2:
        return ""
    first, last = min(names), max(names)
    i = 0
    while i < len(first) and i < len(last) and first[i] == last[i]:
        i += 1
    return first[:i]


def wrap_findmod(mod_name: str, body: str) -> str:
    """Guard the whole patch behind the parent mod being present.

    Without this, installing the patch alone injects material defNames that
    do not exist, producing broken recipes and load errors. <mods> matches
    the parent's About.xml <name>, not its packageId.
    """
    indented = "\n".join(("    " + ln) if ln.strip() else ln for ln in body.split("\n"))
    return (
        '  <Operation Class="PatchOperationFindMod">\n'
        f"    <mods>\n      <li>{mod_name}</li>\n    </mods>\n"
        '    <match Class="PatchOperationSequence">\n'
        "      <success>Always</success>\n"
        "      <operations>\n"
        f"{indented}\n"
        "      </operations>\n"
        "    </match>\n"
        "  </Operation>"
    )


def emit_xml(mat: str, combo, band_amounts, exclusive=(), exclude_defs=()) -> str:
    pred = " and ".join(xpath_term(t) for t in combo)
    # Skip defs the author already handled. A prefix guard such as
    # not(costList/*[starts-with(name(), "ME_")]) looks right and is
    # self-defeating: the first rule adds a prefixed material, so every later
    # rule then sees one and skips. Guard instead on this rule's own material
    # plus the author-exclusive materials -- the ones he used that we do not
    # emit, which are therefore proof he handled the def himself and stay
    # true no matter what we add.
    terms = [f"not(costList/{mat})"] + [f"not(costList/{m})" for m in sorted(exclusive)]
    # Never modify vanilla. The parent author already made every Core decision
    # deliberately; this patch exists to cover the modded content he could not.
    # Without this, the rules would hand the vanilla heater cast iron he chose
    # not to give it, and rewrite the flatscreen television's cost outright.
    terms += [f'not(defName="{d}")' for d in sorted(exclude_defs)]
    guard = " and ".join(terms)
    out = [f"  <!-- {mat}: {' AND '.join(combo)} -->"]
    for (lo, hi), amt in zip(BANDS, band_amounts):
        if amt is None:
            continue
        # No '<' anywhere: it is illegal in XML text. Upper bound as not(> hi).
        rng = f"costList/Steel > {lo}" + (f" and not(costList/Steel > {hi})" if hi < 10_000 else "")
        out.append(
            "  <li Class=\"PatchOperationAdd\">\n"
            f"    <xpath>/Defs/ThingDef[{pred} and {rng} and {guard}]/costList</xpath>\n"
            f"    <value><{mat}>{amt}</{mat}></value>\n"
            "  </li>"
        )
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("packageId")
    ap.add_argument("--emit", type=int, default=1, help="emit XML for the top N rules")
    ap.add_argument("--parent-name", default="More Materials",
                    help="parent mod's About.xml <name>, for the FindMod guard")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    args = ap.parse_args()

    tree, mods, active_ids, src = build_doc(args.rimworld, args.workshop, args.mods_config)
    folder = next((f for pid, f in mods if pid == args.packageId), None)
    if folder is None:
        sys.exit(f"{args.packageId} not active")

    nodes, before, feats = {}, {}, {}
    for n in select(tree, "/Defs/ThingDef[defName]"):
        dn, c = n.findtext("defName"), cost_of(n)
        if dn and c:
            nodes[dn], before[dn], feats[dn] = n, c, features(n)

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
    mats = Counter()
    for a in added.values():
        mats.update(a.keys())

    # The guard skips defs the author already touched with one of his
    # materials, so false positives must be counted with it applied -- the
    # raw F1 from derive_rules.py overstates the damage badly.
    prefix = common_prefix(mats)
    after_all = {dn: (cost_of(n) or {}) for dn, n in nodes.items()}

    def untouched(dn):
        return not prefix or not any(
            k.startswith(prefix) for k in after_all.get(dn, {})
        )

    rules = []
    for mat, _ in mats.most_common():
        pos = {dn for dn, a in added.items() if mat in a} & core
        if len(pos) < 2:
            continue
        score, combo, tp, fp, fn = search(pos, core, feats, 2)
        if not combo:
            continue
        cs = set(combo)
        sel_mod = {i for i in modded if cs <= feats[i] and untouched(i)}
        van_fp = {i for i in core if cs <= feats[i] and untouched(i)} - pos
        rules.append({"mat": mat, "combo": combo, "f1": score, "pos": pos,
                      "mod": sel_mod, "fp_guarded": van_fp})

    # Rank by ASSIGNMENTS, not by defs-touched-at-least-once. Ranking by defs
    # scored cast iron and nickel at "0 new" purely because copper had already
    # claimed the same defs, hiding the second and third most valuable rules.
    rules.sort(key=lambda r: -len(r["mod"]))

    print("=" * 78)
    print(f"PARETO BY ASSIGNMENT — {args.packageId}")
    print("=" * 78)
    total_assign = sum(len(r["mod"]) for r in rules)
    covered = set().union(*[r["mod"] for r in rules]) if rules else set()
    print(f"\n{'#':>2}  {'material':<20} {'F1':>5} {'assigns':>8} {'cum %':>7} {'FP':>4}")
    print("-" * 78)
    run = 0
    for i, r in enumerate(rules, 1):
        if not r["mod"]:
            continue
        run += len(r["mod"])
        print(f"{i:>2}  {r['mat']:<20} {r['f1']:>5.2f} {len(r['mod']):>8}"
              f" {100.0*run/total_assign:>6.0f}% {len(r['fp_guarded']):>4}")
    print(f"\ntotal modded material-assignments: {total_assign}")
    print(f"distinct modded defs touched:      {len(covered)}")
    print(f"vanilla false positives, guarded:  {sum(len(r['fp_guarded']) for r in rules)}")

    top = [r for r in rules if r["mod"]][: args.emit]
    # Pooled exponent across every material, for the shrinkage above.
    _fits = []
    for _mat in mats:
        _pairs = [(before[dn].get("Steel", 0), added[dn][_mat])
                  for dn in added if _mat in added[dn] and dn in core]
        _f = fit_power(_pairs)
        if _f:
            _fits.append((_f[1], len([1 for st, a in _pairs if st > 0 and a > 0])))
    pooled_exp = (sum(pw * n for pw, n in _fits) / sum(n for _, n in _fits)) if _fits else None
    print(f"\npooled exponent across all materials: {pooled_exp:.3f}")

    ana_ops, ana_covered = analogue_ops(nodes, before, added, core, modded)
    print(f"\nanalogue transfers (exact functional twin): {len(ana_covered)}")
    for m, (a, v) in sorted(ana_covered.items()):
        print(f"   {m:<32} <- {a:<22} {v}")
    # Materials the author used but this patch does not emit: unambiguous
    # evidence he handled the def, and unaffected by our own additions.
    exclusive = set(mats) - {r["mat"] for r in top}
    print(f"\nauthor-exclusive guard materials: {sorted(exclusive)}")
    print("\n" + "=" * 78)
    print(f"SHIPPABLE XML — top {len(top)} rule(s)")
    print("=" * 78)

    for r in top:
        pos = r["pos"]
        pairs = [(before[dn].get("Steel", 0), added[dn][r["mat"]]) for dn in pos]
        band_amounts = band_amounts_from_curve(pairs, pooled_exp)
        if band_amounts is None:
            band_amounts = []
            for lo, hi in BANDS:
                vals = [a for st, a in pairs if lo < st <= hi]
                band_amounts.append(round(statistics.median(vals)) if vals else None)
        print(f"\n  band medians for {r['mat']}: "
              + ", ".join(f"{lo}-{hi if hi<10000 else '+'}:{a}"
                          for (lo, hi), a in zip(BANDS, band_amounts)))

    print("\n===RULES===")
    print("\n<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n<Patch>")
    bodies = []
    for r in top:
        pos = r["pos"]
        pairs = [(before[dn].get("Steel", 0), added[dn][r["mat"]]) for dn in pos]
        band_amounts = band_amounts_from_curve(pairs, pooled_exp)
        if band_amounts is None:
            band_amounts = []
            for lo, hi in BANDS:
                vals = [a for st, a in pairs if lo < st <= hi]
                band_amounts.append(round(statistics.median(vals)) if vals else None)
        # Analogue-covered defs are handled exactly; keep the rules off them.
        core_hits = {d for d in core if set(r["combo"]) <= feats[d]} | set(ana_covered)
        bodies.append(emit_xml(r["mat"], r["combo"], band_amounts, exclusive, core_hits))
    # Two files, because they are two different kinds of claim. The rules are
    # universal: they fire on any def with the right structure, from any mod,
    # including mods that do not exist yet. The analogue transfers name
    # specific defs from the modlist this was generated against.
    print(wrap_findmod(args.parent_name, "\n".join(bodies)))
    print("</Patch>")
    print("\n===ANALOGUES===")
    print("\n<?xml version=\"1.0\" encoding=\"utf-8\" ?>\n<Patch>")
    print(wrap_findmod(args.parent_name, "\n".join(ana_ops)))
    print("</Patch>")


if __name__ == "__main__":
    main()
