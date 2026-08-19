#!/usr/bin/env python3
"""Replay RimWorld's PatchOperation pipeline offline and attribute every
change to the mod that made it.

Answers "why does my cooler cost this?" without launching the game, and
doubles as a check on the mod's core premise: it shows exactly what a
rebalance mod does to a vanilla def, and whether the modded analogue was
left behind.

  python3 who_patched.py Cooler
  python3 who_patched.py Cooler VTE_WallMountedCooler --verbose

Implements Replace/Add/Remove/Insert/AttributeSet/AttributeAdd/
AttributeRemove/Sequence/FindMod/Conditional/Test. Anything else is
reported as UNHANDLED when its xpath touches a watched def, so silent
misattribution is not possible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lxml import etree

HOME = Path.home()
DEFAULT_RW = HOME / ".local/share/Steam/steamapps/common/RimWorld"
DEFAULT_WORKSHOP = HOME / ".local/share/Steam/steamapps/workshop/content/294100"
DEFAULT_CONFIG = (
    HOME / ".config/unity3d/Ludeon Studios/RimWorld by Ludeon Studios/Config/ModsConfig.xml"
)
OLD_VERSIONS = {"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"}
CORE_PACKAGE_ID = "ludeon.rimworld"

# Fields worth reporting a diff on. Everything else is tracked but summarised.
WATCH_FIELDS = ("costList", "costStuffCount", "statBases", "researchPrerequisites")

PARSER = etree.XMLParser(recover=True, remove_comments=True)


def read(path: Path):
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    try:
        return etree.fromstring(raw, PARSER)
    except etree.XMLSyntaxError:
        return None


def xml_files(root: Path, subdir: str):
    """All XML under <mod>/**/<subdir>/**, skipping stale version folders."""
    out = []
    for p in root.rglob("*.xml"):
        parts = set(p.parts)
        if parts & OLD_VERSIONS:
            continue
        if subdir in p.parts:
            out.append(p)
    return sorted(out)


def package_id_of(mod_root: Path):
    root = read(mod_root / "About" / "About.xml")
    if root is None:
        return None
    node = root.find("packageId")
    return node.text.strip().lower() if node is not None and node.text else None


def active_mod_ids(config_path: Path):
    root = read(config_path)
    node = root.find("activeMods") if root is not None else None
    if node is None:
        sys.exit(f"cannot read activeMods from {config_path}")
    return [li.text.strip().lower() for li in node.findall("li") if li.text]


def resolve_mods(rw_dir: Path, workshop: Path, active):
    index = {}
    for base in (workshop, rw_dir / "Mods"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            pid = package_id_of(child)
            if pid and (pid not in index or base.name == "Mods"):
                index[pid] = child
    return [(pid, index[pid]) for pid in active if pid in index and pid != CORE_PACKAGE_ID]


# --------------------------------------------------------------------------
# PatchOperation execution
# --------------------------------------------------------------------------


def op_class(op) -> str:
    return (op.get("Class") or "").split(".")[-1]


def select(doc, xpath: str):
    """Evaluate a patch xpath the way RimWorld does.

    RimWorld runs SelectNodes on the XmlDocument, so the context is the
    DOCUMENT node and relative forms like `Defs/ThingDef[...]` or
    `*/ThingDef[...]` -- which most patches in the wild use -- resolve from
    above the root element. lxml's ElementTree.xpath() instead treats a
    relative path as relative to the root ELEMENT, silently matching nothing.
    Normalise by prefixing '/'.
    """
    xp = xpath.strip()
    if not xp:
        return []
    if not xp.startswith(("/", ".", "(")):
        xp = "/" + xp
    try:
        found = doc.xpath(xp)
    except etree.XPathEvalError:
        return []
    return [n for n in found if isinstance(n, etree._Element)]


def value_children(op):
    v = op.find("value")
    return list(v) if v is not None else []


def apply_op(doc, op, active_ids, unhandled) -> None:
    cls = op_class(op)
    xp = op.findtext("xpath")

    if cls == "PatchOperationSequence":
        seq = op.find("operations")
        for child in (list(seq) if seq is not None else []):
            apply_op(doc, child, active_ids, unhandled)
        return

    if cls == "PatchOperationFindMod":
        wanted = {li.text.strip().lower() for li in op.findall("mods/li") if li.text}
        # About.xml <name> is what FindMod matches, but packageId is close
        # enough for attribution purposes; both branches are recorded.
        hit = bool(wanted & active_ids) or any(
            any(w in a for a in active_ids) for w in wanted
        )
        # <match Class="..."> IS the operation. Iterating its children instead
        # silently drops the entire branch -- and FindMod is how mods do
        # cross-mod compat, so that mistake hides a lot of real patching.
        branch = op.find("match" if hit else "nomatch")
        if branch is not None:
            apply_op(doc, branch, active_ids, unhandled)
        return

    if cls in ("PatchOperationConditional", "PatchOperationTest"):
        hit = bool(select(doc, xp)) if xp else False
        if cls == "PatchOperationTest":
            return
        branch = op.find("match" if hit else "nomatch")
        if branch is not None:
            apply_op(doc, branch, active_ids, unhandled)
        return

    if not xp:
        return
    targets = select(doc, xp)
    if not targets:
        return

    if cls == "PatchOperationReplace":
        for t in targets:
            parent = t.getparent()
            if parent is None:
                continue
            idx = list(parent).index(t)
            parent.remove(t)
            for off, nv in enumerate(value_children(op)):
                import copy as _c
                parent.insert(idx + off, _c.deepcopy(nv))

    elif cls == "PatchOperationAdd":
        order = op.findtext("order") or "Append"
        for t in targets:
            import copy as _c
            kids = [_c.deepcopy(nv) for nv in value_children(op)]
            if order.lower() == "prepend":
                for off, nv in enumerate(kids):
                    t.insert(off, nv)
            else:
                t.extend(kids)

    elif cls == "PatchOperationRemove":
        for t in targets:
            if t.getparent() is not None:
                t.getparent().remove(t)

    elif cls == "PatchOperationInsert":
        order = op.findtext("order") or "Prepend"
        for t in targets:
            parent = t.getparent()
            if parent is None:
                continue
            import copy as _c
            idx = list(parent).index(t) + (1 if order.lower() == "append" else 0)
            for off, nv in enumerate(value_children(op)):
                parent.insert(idx + off, _c.deepcopy(nv))

    elif cls in ("PatchOperationAttributeSet", "PatchOperationAttributeAdd"):
        a, v = op.findtext("attribute"), op.findtext("value")
        for t in targets:
            if a and (cls == "PatchOperationAttributeSet" or t.get(a) is None):
                t.set(a, v or "")

    elif cls == "PatchOperationAttributeRemove":
        a = op.findtext("attribute")
        for t in targets:
            if a and a in t.attrib:
                del t.attrib[a]

    else:
        unhandled.append((cls, xp))


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def snapshot(doc, defname: str):
    nodes = select(doc, f'/Defs/*[defName="{defname}"]')
    if not nodes:
        return None
    node = nodes[-1]
    out = {}
    for field in WATCH_FIELDS:
        e = node.find(field)
        if e is None:
            continue
        if len(e):
            out[field] = {c.tag: (c.text or "").strip() for c in e}
        else:
            out[field] = (e.text or "").strip()
    return out


def render(state) -> str:
    if state is None:
        return "<def absent>"
    bits = []
    for field in WATCH_FIELDS:
        if field in state:
            bits.append(f"{field}={state[field]}")
    return "; ".join(bits) or "<no watched fields>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("defnames", nargs="+")
    ap.add_argument("--rimworld", type=Path, default=DEFAULT_RW)
    ap.add_argument("--workshop", type=Path, default=DEFAULT_WORKSHOP)
    ap.add_argument("--mods-config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    active = active_mod_ids(args.mods_config)
    mods = resolve_mods(args.rimworld, args.workshop, active)
    active_ids = set(active)

    # Combined Defs document -- this is what RimWorld patches against.
    doc = etree.Element("Defs")
    origin = {}
    core_defs = args.rimworld / "Data" / "Core" / "Defs"
    sources = [("ludeon.rimworld", sorted(core_defs.rglob("*.xml")))]
    sources += [(pid, xml_files(folder, "Defs")) for pid, folder in mods]

    for pid, files in sources:
        for path in files:
            root = read(path)
            if root is None:
                continue
            for node in root:
                if not isinstance(node.tag, str):
                    continue
                doc.append(node)
                dn = node.findtext("defName")
                if dn:
                    origin.setdefault((dn, node.tag), []).append(pid)

    tree = etree.ElementTree(doc)
    print(f"combined document: {len(doc)} def nodes from Core + {len(mods)} mods\n")

    for dn in args.defnames:
        owners = [v for k, v in origin.items() if k[0] == dn]
        flat = [p for sub in owners for p in sub]
        print(f"{dn}: defined by {flat or ['<not found>']}")
    print()

    state = {dn: snapshot(tree, dn) for dn in args.defnames}
    for dn in args.defnames:
        print(f"  BASE  {dn}: {render(state[dn])}")
    print()

    unhandled_all = []
    touched_by = {dn: [] for dn in args.defnames}

    for pid, folder in mods:
        patch_files = xml_files(folder, "Patches")
        if not patch_files:
            continue
        unhandled = []
        for path in patch_files:
            root = read(path)
            if root is None:
                continue
            for op in root:
                if isinstance(op.tag, str):
                    apply_op(tree, op, active_ids, unhandled)

        for dn in args.defnames:
            after = snapshot(tree, dn)
            if after != state[dn]:
                touched_by[dn].append(pid)
                print(f"### {pid}  changed  {dn}")
                for field in WATCH_FIELDS:
                    b, a = (state[dn] or {}).get(field), (after or {}).get(field)
                    if b != a:
                        print(f"      {field}:")
                        print(f"         before {b}")
                        print(f"         after  {a}")
                state[dn] = after
        if unhandled:
            unhandled_all.append((pid, unhandled))

    print("\n" + "=" * 70)
    print("FINAL")
    print("=" * 70)
    for dn in args.defnames:
        print(f"\n{dn}")
        print(f"  patched by: {touched_by[dn] or ['nothing']}")
        print(f"  final: {render(state[dn])}")

    if args.verbose and unhandled_all:
        print("\nUNHANDLED operation classes (not applied):")
        seen = set()
        for pid, ops in unhandled_all:
            for cls, xp in ops:
                if (pid, cls) in seen:
                    continue
                seen.add((pid, cls))
                print(f"  {pid}: {cls}")


if __name__ == "__main__":
    main()
