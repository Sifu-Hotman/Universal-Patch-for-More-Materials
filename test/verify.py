#!/usr/bin/env python3
"""Machine-verified checks for the SHIPPED patch — automates TESTPLAN sections 1, 2, 4.

Reuses the offline replay infrastructure in tools/ (def loading, the leaf
PatchOperation appliers) but applies the shipped Patches/*.xml independently of
the generator and asserts the invariants the test plan lists by hand. Runs
against the live modlist; the 0-vanilla invariant holds for any modlist, the
coverage counts are range-checked because they depend on which content mods are
active.

  python3 test/verify.py            # all checks, exit non-zero on any failure

Note on fidelity: this reuses tools/who_patched.apply_op for LEAF operations
(Add/Replace/Remove/...), which are faithful, but replaces its
PatchOperationFindMod handling — that matcher keys on packageId, while RimWorld
(and this patch's `<mods><li>More Materials</li>`) keys on the About.xml <name>.
Applier fidelity itself is covered by TESTPLAN section 3 (in-game).
"""

from __future__ import annotations

import sys
from pathlib import Path

from lxml import etree

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from who_patched import (  # noqa: E402
    DEFAULT_CONFIG,
    DEFAULT_RW,
    DEFAULT_WORKSHOP,
    apply_op,
    op_class,
    read,
    xml_files,
)
from mod_rule import build_doc, cost_of  # noqa: E402

PATCHES = REPO / "Patches"
MM_NAME = "More Materials"
MM_ID = "mopolita.bame.morematerials"

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)
    return ok


# --------------------------------------------------------------------------
# A name-faithful applier: FindMod matches the About.xml <name>, Sequence
# recurses, every leaf op delegates to who_patched (faithful for those).
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
    # Leaf op — who_patched applies these correctly (no FindMod inside).
    apply_op(tree, op, set(), unhandled)


def about_names(mods) -> set[str]:
    names = set()
    for _pid, folder in mods:
        root = read(folder / "About" / "About.xml")
        node = root.find("name") if root is not None else None
        if node is not None and node.text:
            names.add(node.text.strip())
    return names


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
    """defName -> {'added': {mat: amt}, 'from': before, 'to': after} for changed defs."""
    changed = {}
    for dn, a in after.items():
        b = before.get(dn)
        if b != a:
            added = {k: v for k, v in a.items() if k not in (b or {})}
            changed[dn] = {"added": added, "from": b, "to": a}
    return changed


def replay(with_mm: bool):
    """Build the doc, apply MM, snapshot, apply the shipped UPMM patches; return
    (changed, src). When with_mm is False, MM is dropped from the FindMod name set
    so the shipped patch's guard must make it a no-op."""
    tree, mods, _active_ids, src = build_doc(DEFAULT_RW, DEFAULT_WORKSHOP, DEFAULT_CONFIG)
    names = about_names(mods)
    # Baseline: apply More Materials' own patches (what UPMM sits on top of).
    mm_folder = next((f for pid, f in mods if pid == MM_ID), None)
    if mm_folder is not None:
        apply_patch_files(tree, xml_files(mm_folder, "Patches"), names)
    baseline = snapshot(tree)
    # Apply the shipped patch, with or without MM visible to its FindMod guard.
    eff_names = names if with_mm else (names - {MM_NAME})
    files = sorted(PATCHES.glob("*.xml"))
    apply_patch_files(tree, files, eff_names)
    return diff(baseline, snapshot(tree)), src, tree


# --------------------------------------------------------------------------
# 1. Artifact integrity
# --------------------------------------------------------------------------

EMDASH = "—"

def check_integrity():
    print("\n1. Artifact integrity")
    for path in sorted(PATCHES.glob("*.xml")):
        raw = path.read_text(encoding="utf-8")
        # Strict parse — RimWorld's XmlDocument is a conformant, strict parser.
        try:
            tree = etree.parse(str(path), etree.XMLParser(recover=False))
        except etree.XMLSyntaxError as e:
            check(f"{path.name} parses (strict)", False, str(e).splitlines()[0])
            continue
        check(f"{path.name} parses (strict)", True)
        root = tree.getroot()
        # Every LIVE xpath compiles and carries no raw '<' (illegal; use not(> n)).
        xpaths = [e.text for e in root.iter("xpath") if e.text]
        bad_compile = [xp for xp in xpaths
                       if _bad_xpath(xp)]
        check(f"{path.name}: all {len(xpaths)} live xpaths compile", not bad_compile,
              "" if not bad_compile else f"{len(bad_compile)} bad")
        check(f"{path.name}: no raw '<' in xpaths", not any("<" in xp for xp in xpaths))
        # The em-dash sanitiser (which converts illegal '--' to em-dash inside the
        # header comment) must NEVER run over the operations: '<!—' / '—>' delimiters
        # are corruption. Their presence collapses real operations into a comment.
        check(f"{path.name}: no em-dash comment delimiters",
              ("<!" + EMDASH) not in raw and (EMDASH + ">") not in raw)
        # No real operation markup swallowed inside a comment (a broken delimiter
        # can collapse a whole block into one comment — often a PROLOG comment
        # before the root, which is why we scan preceding siblings too).
        comments = [c for c in root.itersiblings(preceding=True) if c.tag is etree.Comment]
        comments += [c for c in tree.iter() if c.tag is etree.Comment]
        swallowed = [c for c in comments
                     if any(tok in (c.text or "")
                            for tok in ("<xpath>", "<li Class=", "<Operation Class="))]
        check(f"{path.name}: no operations swallowed inside a comment", not swallowed,
              "" if not swallowed else f"{len(swallowed)} comment(s) carry op markup")


def _bad_xpath(xp: str) -> bool:
    try:
        etree.XPath(xp if xp.strip().startswith(("/", ".", "(")) else "/" + xp)
        return False
    except etree.XPathSyntaxError:
        return True


# --------------------------------------------------------------------------
# 2. Replay, both branches + idempotence
# --------------------------------------------------------------------------

def check_replay():
    print("\n2. Replay (More Materials present)")
    changed, src, _tree = replay(with_mm=True)
    vanilla = sorted(dn for dn in changed if src.get(dn) == "core")
    modded = [dn for dn in changed if src.get(dn) not in ("core", None)]
    reqs = sum(len(c["added"]) for c in changed.values())

    check("ZERO vanilla defs modified", not vanilla,
          "" if not vanilla else f"{len(vanilla)} touched: {vanilla[:8]}")
    check("modded defs changed in range (150-320)", 150 <= len(modded) <= 320,
          f"{len(modded)} changed")
    check("material requirements added in range (450-820)", 450 <= reqs <= 820,
          f"{reqs} added")

    def gained(dn, mat):
        return dn in changed and mat in changed[dn]["added"]

    check("VTE_WallMountedCooler gains ME_Copper", gained("VTE_WallMountedCooler", "ME_Copper"))
    # Analogue: the wall heater must take the HEATER's metals, not the cooler's
    # (cooler = ME_Lithium; heater = ME_Copper/Nickel/Tin, no lithium).
    wh = changed.get("VTE_WallHeater", {}).get("added", {})
    check("VTE_WallHeater takes heater metals, not cooler's",
          "ME_Copper" in wh and "ME_Lithium" not in wh, f"added={wh}")
    check("vanilla Cooler NOT changed by us", "Cooler" not in changed)
    check("vanilla Ship_Reactor NOT changed by us", "Ship_Reactor" not in changed)

    print("\n2b. Replay (More Materials absent → must be a no-op)")
    changed_off, _src, _t = replay(with_mm=False)
    check("zero defs changed with MM absent", not changed_off,
          "" if not changed_off else f"{len(changed_off)} changed")

    print("\n2c. Idempotence (apply twice == apply once)")
    tree, mods, _a, _s = build_doc(DEFAULT_RW, DEFAULT_WORKSHOP, DEFAULT_CONFIG)
    names = about_names(mods)
    mm_folder = next((f for pid, f in mods if pid == MM_ID), None)
    if mm_folder is not None:
        apply_patch_files(tree, xml_files(mm_folder, "Patches"), names)
    files = sorted(PATCHES.glob("*.xml"))
    apply_patch_files(tree, files, names)
    once = snapshot(tree)
    apply_patch_files(tree, files, names)
    twice = snapshot(tree)
    check("second application adds nothing", once == twice,
          "" if once == twice else f"{len(diff(once, twice))} defs differ")


# --------------------------------------------------------------------------
# 4. Regression sensitivity (static)
# --------------------------------------------------------------------------

def check_regression():
    print("\n4. Regression sensitivity (static)")
    tree = etree.parse(str(PATCHES / "01_Rules.xml"), etree.XMLParser(recover=True))
    live_xp = " ".join(e.text or "" for e in tree.getroot().iter("xpath"))
    # The material guard must be per-material ME_ names, never a single prefix
    # guard like starts-with(name(), "ME_") — that collapses coverage. Scan the
    # LIVE xpaths, not the header prose (which discusses the rejected approach).
    check("no self-defeating ME_ prefix guard in live rules", "starts-with" not in live_xp)
    # The vanilla exclusion list must be present and current in the live rules.
    excl = live_xp.count('not(defName="')
    check("vanilla exclusions present in live rules", excl > 0,
          f"{excl} not(defName=...) guards")


def main() -> int:
    print("=" * 70)
    print("UPMM shipped-patch verification")
    print("=" * 70)
    check_integrity()
    check_replay()
    check_regression()
    print("\n" + "=" * 70)
    if failures:
        print(f"FAILED — {len(failures)} check(s): {failures}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
