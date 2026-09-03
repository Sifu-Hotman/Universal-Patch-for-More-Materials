# Test plan

Most of this is machine-verified and reproducible. `tools/` reimplements
RimWorld's PatchOperation pipeline, so the offline checks need no game launch and
no particular modlist.

## 1. Automated harness — must print `ALL CHECKS PASSED`

```bash
python3 test/verify.py
```

Runs in ~1s against **Core + More Materials only** (the mod's actual dependencies,
not a snapshot of a personal modlist) plus a couple of synthetic modded defs, and
asserts:

- **Integrity** (static): both files strict-parse; every xpath compiles; no raw
  `<`; **no em-dash comment delimiters and no operations swallowed inside a
  comment** — the header sanitiser running over the operations has shipped broken
  before.
- **Structure** (static): every operation is wrapped in `FindMod(More Materials)`;
  every rule carries its own material guard plus the author-exclusive
  electrum/lithium/white-gold guards; the vanilla exclusions are present; no
  self-defeating `starts-with` prefix guard; the 8 analogue transfers are
  well-formed and the wall heater takes the heater's metals (copper, no lithium).
- **Replay** (Core + MM + synthetic fixtures): UPMM modifies **zero Ludeon defs**;
  a powered steel def gains copper (the rule fires); an electrum-carrying def is
  skipped; it is a **no-op without More Materials**; it is **idempotent**.

Do not hand-assemble the header — a blanket `--`→em-dash pass corrupts the
operation delimiters; keep `--` out of the header prose and use proper
`<!--`/`-->`. (`test/verify.py` fails loudly if it recurs.)

## 2. In-game / live-modlist (the modlist-specific part)

The automated harness deliberately does not pin a content modlist. These are the
checks that need one, done by hand on your actual install:

- Load the full modlist: no red errors.
- Architect menu: a modded powered building (e.g. VTE's wall-mounted cooler) lists
  copper in its cost, and a build order for it completes with copper in stock.
- With More Materials disabled: clean load, no missing-def errors.
- Coverage sanity (optional): a full-modlist replay reproduces ~221 defs / ~650
  assignments / **0 vanilla** — a measurement, not a gate; it moves with your mods.

## 3. Known limitations (documented, not chased)

- **DLC exclusions require the DLC installed to generate.** The generator loads
  every official `Data/<expansion>/Defs` present, so on a Core-only machine the
  exclusion list is Core-only and DLC buildings would be patched in-game.
  Regenerate on a machine that owns the expansions to bake in the DLC names.
- **Cross-mod residue.** A rule can fire on a Ludeon def that *another* mod patched
  into its shape at load (a minification mod adding `Mass` to a vanilla generator).
  On the reference modlist that is three defs, each gaining a couple of units of
  one material on a still-buildable recipe, each already modified by that other
  mod. A universal xpath rule cannot see another mod's load-time patch without
  enumerating every Ludeon building, so this is documented, not fixed.

## Regenerating

Never edit `Patches/*.xml` by hand — change `tools/pareto.py` and regenerate
(`RELEASING.md`), or the next run reverts you. `who_patched.py` attributes any one
def ("why does my cooler cost this?").
