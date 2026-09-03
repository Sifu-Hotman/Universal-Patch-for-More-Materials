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
2. **Run the machine-verified harness — it must print `ALL CHECKS PASSED`:**

   ```bash
   python3 test/verify.py
   ```

   It automates the offline test plan: both files strict-parse; every xpath
   compiles; no raw `<`; **no em-dash comment delimiters and no operations
   swallowed in a comment** (the header sanitiser running over the operations has
   shipped broken before); replay with More Materials → ~221 defs, ~650
   assignments, **0 vanilla**; replay without it → **0 defs**; idempotent. Do not
   hand-assemble the header — a blanket `--`→em-dash pass corrupts the operation
   delimiters; keep `--` out of the header prose and use proper `<!--`/`-->`.
3. In-game: load the full modlist, confirm no red errors, and check one target
   in the architect menu — VTE's wall-mounted cooler should list copper.
4. In-game with More Materials disabled: confirm a clean load.
5. Record the More Materials version tested; tag `v1.0.0`.
6. Upload via in-game Mods → Upload to Steam.

For attribution of any single def ("why does my cooler cost this?"),
`tools/who_patched.py` runs the same replay against arbitrary defNames.

## Versioning

Semver. No save footprint — costs are read at build time, so adding or removing
mid-save is safe. A change that alters existing recipes is a minor bump; a
change to which defs are selected is a major one.

## If More Materials updates

Its patches are the training data. Regenerate, diff the rule table, and re-read
the vanilla exclusion list — new vanilla defs he patches must drop out of ours.
