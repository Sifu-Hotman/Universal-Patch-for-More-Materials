# Releasing

Pure XML patch mod. No build step, no assembly, no CI.

## Regenerating the patch

The patch is generated, not hand-edited. Never edit `Patches/*.xml` directly —
change `tools/pareto.py` and regenerate, or the next run silently reverts you.

```bash
python3 tools/pareto.py mopolita.bame.morematerials --emit 99
```

Needs `lxml` and a local RimWorld install with More Materials subscribed. Reads
the game and Workshop folders directly; no game launch.

## Checklist

1. Regenerate; confirm the rule table in the emitted header still matches the
   `pareto.py` output.
2. Validate the XML and every xpath — see the verification snippet below. `--`
   inside an XML comment and a raw `<` inside an xpath have both shipped broken
   before.
3. Replay verification, both branches:
   - with More Materials: ~221 defs changed, ~495 assignments, **0 vanilla**
   - without More Materials: **0 defs changed** (the FindMod guard)
4. In-game: load the full modlist, confirm no red errors, and check one target
   in the architect menu — VTE's wall-mounted cooler should list copper.
5. In-game with More Materials disabled: confirm a clean load.
6. Record the More Materials version tested; tag `v1.0.0`.
7. Upload via in-game Mods → Upload to Steam.

## Verification snippet

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, 'tools')
from lxml import etree
doc = etree.parse('Patches/MoreMaterials_Universal.xml')
ops = doc.getroot().findall('.//li[@Class]')
for o in ops:
    etree.XPath(o.findtext('xpath').strip())
print(f"{len(ops)} operations, all xpaths compile")
PY
```

For the replay check see `docs/derivation.md`; `tools/who_patched.py` runs the
same pipeline against arbitrary defNames.

## Versioning

Semver. No save footprint — costs are read at build time, so adding or removing
mid-save is safe. A change that alters existing recipes is a minor bump; a
change to which defs are selected is a major one.

## If More Materials updates

Its patches are the training data. Regenerate, diff the rule table, and re-read
the vanilla exclusion list — new vanilla defs he patches must drop out of ours.
