#!/usr/bin/env python3
"""Machine-verified checks for the SHIPPED patch — reproducible, no personal modlist.

The mod's correctness does not depend on any particular set of content mods, so
neither does this harness. It runs three kinds of check:

  1. Artifact integrity (static)   — the shipped XML parses strict, every xpath
     compiles, no raw '<', and — the regression that has actually shipped — no
     em-dash comment delimiters and no operations swallowed inside a comment.
  2. Structure (static)            — every operation is wrapped in the
     FindMod(More Materials) guard; every rule carries its own material guard and
     the author-exclusive electrum/lithium/white-gold guards; the vanilla
     exclusions are present; no self-defeating prefix guard; and the analogue
     transfers are well-formed (the wall heater takes the heater's metals, not
     the cooler's lithium).
  3. Replay against Core + More Materials ONLY (the mod's actual dependencies,
     not a snapshot of a personal modlist) plus a couple of SYNTHETIC modded
     defs — so the rules have something to fire on. Asserts: UPMM modifies zero
     Ludeon defs, a powered steel def gains copper, an author-handled (electrum)
     def is skipped, the patch is a no-op without More Materials, and it is
     idempotent.

Coverage counts and the real analogue targets (VTE_WallHeater, …) are inherently
modlist-specific and are left to the in-game pass in TESTPLAN — see it for the
live-modlist replay and the residual cross-mod caveat.

  python3 test/verify.py            # all checks, exit non-zero on any failure

Fidelity: leaf ops (Add/…) delegate to tools/who_patched, faithful to RimWorld;
PatchOperationFindMod is matched by the About.xml <name> (RimWorld's
ModLister.HasActiveModWithName), not packageId.
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from who_patched import (  # noqa: E402
    DEFAULT_RW,
    DEFAULT_WORKSHOP,
    apply_op,
    op_class,
    read,
    resolve_mods,
    xml_files,
)
from mod_rule import cost_of  # noqa: E402

PATCHES = REPO / "Patches"
MM_NAME = "More Materials"
MM_ID = "mopolita.bame.morematerials"
EXCLUSIVE_GUARDS = ("ME_ElectrumIngot", "ME_Lithium", "ME_WhiteGoldIngot")

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


# --------------------------------------------------------------------------
# Applier: FindMod matches the About.xml <name>, Sequence recurses, leaf ops
# delegate to who_patched (faithful for those).
# --------------------------------------------------------------------------

def apply_faithful(tree, op, active_names, unhandled) -> None:
    cls = op_class(op)
    if cls == "PatchOperationFindMod":
        wanted = {li.text.strip() for li in op.findall("mods/li") if li.text}
        branch = op.find("match" if (wanted & active_names) else "nomatch")
        if branch is not None:
            apply_faithful(tree, branch, active_names, unhandled)
        return
    if cls == "PatchOperationSequence":
        seq = op.find("operations")
        for child in (list(seq) if seq is not None else []):
            apply_faithful(tree, child, active_names, unhandled)
        return
    apply_op(tree, op, set(), unhandled)


def apply_patch_files(tree, files, active_names):
    unhandled = []
    for path in files:
        root = read(path)
        if root is None:
            continue
        for op in root:
            if isinstance(op.tag, str):
                apply_faithful(tree, op, active_names, unhandled)
    return unhandled


def snapshot(tree) -> dict:
    out = {}
    for n in tree.getroot():
        if not isinstance(n.tag, str):
            continue
        dn = n.findtext("defName")
        c = cost_of(n)
        if dn and c is not None:
            out[dn] = c
    return out


def diff(before: dict, after: dict) -> dict:
    changed = {}
    for dn, a in after.items():
        b = before.get(dn)
        if b != a:
            changed[dn] = {k: v for k, v in a.items() if k not in (b or {})}
    return changed


def costlist_sig(tree) -> dict:
    """defName -> serialized costList. Unlike cost_of/snapshot (a tag-keyed dict,
    which collapses a duplicate <ME_Copper> node), this preserves node order and
    duplicates, so a non-idempotent double-apply is actually visible."""
    out = {}
    for n in tree.getroot():
        if not isinstance(n.tag, str):
            continue
        dn = n.findtext("defName")
        cl = n.find("costList")
        if dn and cl is not None:
            out[dn] = etree.tostring(cl, encoding="unicode")
    return out


# Synthetic MODDED defs so the rules have something to fire on without any
# content mod. A powered steel bench the copper rule must hit, and an
# author-handled (electrum) one it must skip.
FIXTURES = """<Defs>
  <ThingDef><defName>MMUP_TestPoweredBench</defName>
    <costList><Steel>50</Steel></costList>
    <comps><li Class="CompProperties_Power"/></comps></ThingDef>
  <ThingDef><defName>MMUP_TestElectrumBench</defName>
    <costList><Steel>50</Steel><ME_ElectrumIngot>3</ME_ElectrumIngot></costList>
    <comps><li Class="CompProperties_Power"/></comps></ThingDef>
</Defs>"""


def build_core_mm_doc(with_fixtures=True):
    """Core + installed DLC + More Materials only — pinned dependencies, not a
    personal modlist. Optional synthetic modded fixtures. Returns (tree, mods, src)."""
    mods = resolve_mods(DEFAULT_RW, DEFAULT_WORKSHOP, [MM_ID])
    doc = etree.Element("Defs")
    src = {}
    for expansion in sorted(p for p in (DEFAULT_RW / "Data").iterdir() if p.is_dir()):
        d = expansion / "Defs"
        if not d.is_dir():
            continue
        for path in sorted(d.rglob("*.xml")):
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
    if with_fixtures:
        for n in etree.fromstring(FIXTURES):
            doc.append(n)
            src[n.findtext("defName")] = "fixture"
    return etree.ElementTree(doc), mods, src


def replay(with_mm: bool, with_fixtures=True):
    tree, mods, src = build_core_mm_doc(with_fixtures)
    names = {MM_NAME}
    if mods:
        apply_patch_files(tree, xml_files(mods[0][1], "Patches"), names)
    baseline = snapshot(tree)
    apply_patch_files(tree, sorted(PATCHES.glob("*.xml")),
                      names if with_mm else set())
    return diff(baseline, snapshot(tree)), src


# --------------------------------------------------------------------------
# 1. Artifact integrity (static)
# --------------------------------------------------------------------------

EMDASH = "—"


def _bad_xpath(xp: str) -> bool:
    try:
        etree.XPath(xp if xp.strip().startswith(("/", ".", "(")) else "/" + xp)
        return False
    except etree.XPathSyntaxError:
        return True


def check_integrity():
    print("\n1. Artifact integrity")
    for path in sorted(PATCHES.glob("*.xml")):
        raw = path.read_text(encoding="utf-8")
        try:
            tree = etree.parse(str(path), etree.XMLParser(recover=False))
        except etree.XMLSyntaxError as e:
            check(f"{path.name} parses (strict)", False, str(e).splitlines()[0])
            continue
        check(f"{path.name} parses (strict)", True)
        root = tree.getroot()
        xpaths = [e.text for e in root.iter("xpath") if e.text]
        check(f"{path.name}: all {len(xpaths)} live xpaths compile",
              not any(_bad_xpath(xp) for xp in xpaths))
        check(f"{path.name}: no raw '<' in xpaths", not any("<" in xp for xp in xpaths))
        check(f"{path.name}: no em-dash comment delimiters",
              ("<!" + EMDASH) not in raw and (EMDASH + ">") not in raw)
        comments = [c for c in root.itersiblings(preceding=True) if c.tag is etree.Comment]
        comments += [c for c in tree.iter() if c.tag is etree.Comment]
        swallowed = [c for c in comments
                     if any(tok in (c.text or "")
                            for tok in ("<xpath>", "<li Class=", "<Operation Class="))]
        check(f"{path.name}: no operations swallowed inside a comment", not swallowed,
              "" if not swallowed else f"{len(swallowed)} comment(s) carry op markup")


# --------------------------------------------------------------------------
# 2. Structure (static)
# --------------------------------------------------------------------------

def _adds(root):
    return [li for li in root.iter("li") if (li.get("Class") or "").endswith("PatchOperationAdd")]


def check_structure():
    print("\n2. Structure")
    rules = etree.parse(str(PATCHES / "01_Rules.xml"), etree.XMLParser(recover=False)).getroot()
    ana = etree.parse(str(PATCHES / "02_Analogues.xml"), etree.XMLParser(recover=False)).getroot()

    # Every operation lives under a FindMod(More Materials) guard — so the patch
    # is inert without the parent (it would otherwise inject ME_ defNames that do
    # not exist).
    for root, name in ((rules, "01_Rules.xml"), (ana, "02_Analogues.xml")):
        fm = root.findall("Operation")
        wrapped = all((op.get("Class") or "").endswith("PatchOperationFindMod")
                      and {li.text.strip() for li in op.findall("mods/li") if li.text} == {MM_NAME}
                      for op in fm)
        check(f"{name}: all operations wrapped in FindMod(More Materials)", bool(fm) and wrapped)

    rule_xps = [li.findtext("xpath") or "" for li in _adds(rules)]
    # Each rule guards its own material AND the three author-exclusive materials,
    # and skips at least one named vanilla def. A single ME_ prefix guard would
    # be self-defeating.
    joined = " ".join(rule_xps)
    check("rules: no self-defeating ME_ prefix guard", "starts-with" not in joined)
    check("rules: every rule carries the author-exclusive guards",
          all(all(f"not(costList/{g})" in xp for g in EXCLUSIVE_GUARDS) for xp in rule_xps))
    # own material + the 3 author-exclusive materials = at least 4 ME_ guards.
    check("rules: every rule carries a per-material self-guard",
          all(xp.count("not(costList/ME_") >= 4 for xp in rule_xps))
    check("rules: vanilla exclusions present",
          all("not(defName=" in xp for xp in rule_xps),
          f"{joined.count('not(defName=')} guards across {len(rule_xps)} rules")

    ana_adds = _adds(ana)
    check("analogues: 8 well-formed transfers", len(ana_adds) == 8, f"{len(ana_adds)} ops")
    check("analogues: each names a def, guards it, and adds a value",
          all(('defName="' in (li.findtext("xpath") or "")
               and "not(costList/" in (li.findtext("xpath") or "")
               and li.find("value") is not None and len(li.find("value")))
              for li in ana_adds))
    # The wall heater must take the HEATER's metals (copper, no lithium) — the
    # comp-property fingerprint regressing to statBases shows up here.
    wh = next((li for li in ana_adds
               if 'defName="VTE_WallHeater"' in (li.findtext("xpath") or "")), None)
    wh_mats = {c.tag for c in wh.find("value")} if wh is not None else set()
    check("analogues: VTE_WallHeater takes heater metals, not the cooler's",
          "ME_Copper" in wh_mats and "ME_Lithium" not in wh_mats, f"{sorted(wh_mats)}")


# --------------------------------------------------------------------------
# 3. Replay against Core + More Materials (+ synthetic fixtures)
# --------------------------------------------------------------------------

def check_replay():
    print("\n3. Replay — Core + More Materials only (+ synthetic modded fixtures)")
    changed, src = replay(with_mm=True)
    vanilla = sorted(dn for dn in changed if src.get(dn) == "core")
    check("UPMM modifies ZERO Ludeon defs", not vanilla,
          "" if not vanilla else f"{len(vanilla)} touched: {vanilla[:8]}")
    check("a powered steel def gains copper (the rule fires)",
          "ME_Copper" in changed.get("MMUP_TestPoweredBench", {}),
          f"added={changed.get('MMUP_TestPoweredBench', {})}")
    check("an author-handled (electrum) def is skipped",
          "MMUP_TestElectrumBench" not in changed)

    print("\n3b. No-op without More Materials")
    changed_off, _ = replay(with_mm=False)
    check("zero defs changed with MM absent", not changed_off,
          "" if not changed_off else f"{len(changed_off)} changed")

    print("\n3c. Idempotence")
    tree, mods, _src = build_core_mm_doc()
    names = {MM_NAME}
    if mods:
        apply_patch_files(tree, xml_files(mods[0][1], "Patches"), names)
    files = sorted(PATCHES.glob("*.xml"))
    apply_patch_files(tree, files, names)
    once = costlist_sig(tree)  # serialized, so a duplicate-node re-add would show
    apply_patch_files(tree, files, names)
    twice = costlist_sig(tree)
    diffed = [dn for dn in twice if once.get(dn) != twice[dn]]
    check("second application adds nothing", not diffed,
          "" if not diffed else f"{len(diffed)} defs differ")


def main() -> int:
    print("=" * 70)
    print("UPMM shipped-patch verification (reproducible; Core + More Materials)")
    print("=" * 70)
    check_integrity()
    check_structure()
    check_replay()
    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED — {len(failures)} check(s): {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
