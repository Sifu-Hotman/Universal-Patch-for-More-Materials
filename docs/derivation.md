# Derivation: how this became four XML rules

Full working history of the project, kept because it contains three things
worth not re-deriving:

- **Rejected alternatives** — why this is not a C# clustering engine with
  five category engines and an in-game review UI. That design was measured
  out of existence, and the reasoning is at the bottom of this file.
- **The census** — why the "N rebalance mods x M content mods" lattice does
  not exist on a real 300-mod list, and how to check whether it exists on
  yours.
- **Five measurement bugs**, each of which produced a confident, plausible,
  wrong answer rather than an obvious failure.

The shipped mod is described in [../README.md](../README.md). Everything
below is the route taken to get there, in the order it happened.

---

# Universal Rebalancer

**Status: design spec, no code.** Rewritten 2026-08-19 after the original clustering
design was cut down. Read this as the spec-so-far. The design it replaced is preserved
at the bottom under "Rejected alternatives" — read that section before proposing
anything it already rules out.

## Objective — the patch-lattice problem

Rebalance mods patch vanilla defs. Functionally-analogous modded items keep their
vanilla-era numbers and become silently mispriced. A materials/rebalance mod tweaks
the vanilla cooler's cost; the "over-wall cooler" from a content mod still matches
vanilla PRE-balance stats and is now strictly better and cheaper. N rebalance mods ×
M content mods = a patch matrix nobody maintains.

**Universal Rebalancer** applies the changes a rebalance mod made to a vanilla def onto
the modded items that should have moved with it.

The user-facing symptom this exists to kill: *"why would I ever build a regular
cooler?"*

### Scope narrowed 2026-08-19: propagation, not balance judgment

Measurement reframed the problem. The dominant real case is not "this item is mispriced"
— it is "**a materials mod added new ingredients to vanilla recipes and every modded
equivalent was left out.**" On the author's list, More Materials patched 61 costLists;
**59 of the 61 targets are vanilla Core.** Essentially zero mod compatibility, by one
popular mod, and that is the entire gap.

Three consequences, all simplifying:

- **No balance model of any kind is needed.** The mod never decides what something
  *should* cost. It only propagates a change someone else already decided on.
- **Discovery is free.** The rebalance mod's own patch set *is* the list of what moved.
  Nothing has to be hunted for. This deletes the entire discovery problem, and with it
  the main justification for the dominance scan (now optional — see below).
- **The match problem shrinks by an order of magnitude.** Analogues are only needed for
  the handful of vanilla defs the rebalance mod actually touched — 58 fingerprintable
  anchors here, not all 693 of vanilla. Precision rises accordingly: tier A produced
  6 proposals with **zero** ambiguous rejections, against 10 proposals and much more
  ambiguity when matching against all of vanilla.

What it does *not* buy: there is no single rule to fit. See "Is a materials mod a rule?"
below — it is hand-authored per item, so analogue matching survives as the mechanism.

## Core principles (binding)

1. **Re-price and re-gate, never re-design.** Levers: `costList`, `costStuffCount`,
   `workToBuild`, `marketValue`, `researchPrerequisites`. NEVER functional stats
   (cooling rate, DPS, grow time). Function is design intent; cost and gating are
   economy positioning. This is also what makes the mod safe alongside Combat Extended
   — CE owns combat stats, we never touch them.
2. **Transfer movement, never values.** The over-wall cooler does not become the
   vanilla cooler's new cost. It gets the same *delta* applied to its own baseline, so
   whatever premium its author intended survives.
3. **The hand-maintained mapping list is the authority.** Automation fills gaps and
   proposes candidates. It never overrides a human entry.
4. **Structure gates, names never bridge.** Automatic matching is exact-ish structural
   equality against a pre-rebalance snapshot, not similarity. There is no distance
   metric, no threshold-tuned clustering, no theme matching. A miss is cheap (falls to
   the hand list); a false positive silently mangles an economy.

## Architecture

Three mechanisms feed **one applier**. Nothing patches except the applier, and it
patches only from mapping entries.

```
vanilla snapshot (shipped data)
        │
        ├─► moved-set detection ──┐
        │                         │
hand mappings ────────────────────┼─► applier ─► runtime def mutation
        │                         │
fingerprint auto-mapping ─────────┘
        │
dominance scan ─► report file (proposes mappings, never patches)
```

### 1. Vanilla snapshot

A static data file shipped with the mod: every vanilla + DLC def's **pre-rebalance**
values.

Per def: lever fields (`costList`, `costStuffCount`, `workToBuild`, `marketValue`,
`researchPrerequisites`), plus `statBases` and comp class names (needed for
fingerprinting).

This single file replaces the entire baseline-reconstruction subsystem the old design
needed — no re-reading raw XML from mod folders, no re-running def inheritance, no
`LoadFolders`/version-folder handling, no PatchOperation hooking.

**Moved set** = vanilla defs whose live values differ from the snapshot on any lever
field. This is the *net* of all installed patches, which is the correct semantics: the
user's complaint is about the cooler as it currently exists, not about which mod moved
it. Attribution is therefore unnecessary.

Generated by a dev-mode dump on a vanilla-only install, once per RimWorld version.
Regenerating on minor version bumps is real ongoing maintenance.

### 2. Hand mappings — the authority

A mapping is a tuple plus optional semantics:

```xml
<UniversalRebalancer.MappingDef>
  <base>Cooler</base>
  <target>WallStuff_OverWallCooler</target>
  <mode>ratio</mode>                    <!-- ratio (default) | absolute | copy | suppress -->
  <fields>                              <!-- default: all levers -->
    <li>costList</li>
    <li>workToBuild</li>
  </fields>
</UniversalRebalancer.MappingDef>
```

- `ratio` — apply the base's proportional movement to the target's own baseline.
- `absolute` — apply the base's absolute delta.
- `copy` — set the target to the base's current values. "Just make it match."
- `suppress` — block any auto-mapping for this target.

`mode` and `fields` exist so the transform engine can be wrong and the product still
works. Worst case the user pins the behaviour by hand.

**Locations, merged at load, later wins:**

1. `Mappings/*.xml` in the mod folder — one file per source mod, community-PR-able.
2. `Config/UniversalRebalancer/personal.xml` — the user's own, survives Workshop updates.

Contribution barrier is a ten-line XML file. That is deliberate: **the mapping data is
the product**; the C# is an applier.

**Constraint, v1: `base` must be a vanilla def.** A modded base would require that
mod's pre-rebalance baseline, which drags back the whole loader-reimplementation
problem the snapshot deleted.

Many-to-one is free (several entries sharing a base). Two bases for one target is a
conflict — rejected at validation.

### 3. Transform engine

Given base's snapshot → live delta, apply to target, per field:

- **`costList`** — per-material ratio. Base `90 steel → 45 steel + 20 copper` means
  steel ×0.5, plus copper added at 20/90 of the target's original steel mass. Round to
  int, minimum 1 where nonzero.
- **`costStuffCount`** — scalar ratio.
- **`workToBuild`, `marketValue`** — scalar ratio.
- **`researchPrerequisites`** — set or clear; not a ratio.

Shape mismatch (base uses `costList`, target is stuff-based, or vice versa) falls back
to a scalar ratio on whatever the target has. This case is common — most furniture is
stuff-based — so it is not an edge case.

**Idempotency is free.** Runtime mutation does not persist to XML and defs reload fresh
each boot, so every apply starts from the shipped baseline. No accumulation across
sessions. Guard against double-apply within a single boot with a flag.

### 4. Fingerprint auto-mapping

Handles the copy-paste majority — items a mod author derived from a vanilla def by
copy-and-tweak, which is exactly the population most likely to be missed by rebalance
mods.

### THE RULE THAT MAKES THIS WORK

**Lever fields are never part of the identity fingerprint. Divergence in a lever is the
signal being detected, not evidence against a match.**

This is easy to get wrong because `WorkToBuild`, `WorkToMake`, `MarketValue` and
`SellPriceFactor` live *inside* `statBases`, right next to genuine functional stats.
Comparing them as identity fields is not merely noisy — it is **anti-correlated with the
goal**: the more a rebalance mod moves vanilla's `WorkToBuild`, the further the untouched
modded twin drifts, so the matcher gets worse at precisely the items it exists to catch.

Measured: `VTE_WallMountedCooler` vs vanilla `Cooler` differ on *exactly one* stat,
`WorkToBuild` (1400 vs 1600). Every functional stat is identical. Include the lever and
they are 12.5% apart and rejected. Exclude it and they are an **exact** match, with the
lever gap as the payload to transfer. Same for the heater (800 vs 1000).

Split `statBases` into:

- **functional** — the fingerprint. Never patched.
- **lever** — `WorkToBuild`, `WorkToMake`, `MarketValue`, `SellPriceFactor`,
  `RoyalFavorValue`. Never fingerprinted. Always patchable.

**And the functional half is not just `statBases`.** Most of what a RimWorld building
actually *does* lives elsewhere: comp property values (`energyPerSecond`,
`basePowerConsumption`, storage capacity, joy), `fillPercent`, `passability`, `size`,
`placeWorkers`, `building/isEdifice`, `building/isAirtight`. A cooler's cooling power is
a comp property. Fingerprinting `statBases` alone rates a wall-*mounted* cooler identical
to a wall-*replacing* one — see finding 5.

### The two tiers

Common gates, against each **moved** vanilla def:

1. **Comparability** — functional stat key sets identical.
2. **Structure** — vanilla def's comp class set ⊆ modded def's comp class set.
3. **Category** — `designationCategory` non-empty and identical on both sides.
4. **Unique** — exactly one surviving candidate, else abstain.

Then:

**Tier A — lever-only divergence.** Functional stats exactly equal, levers differ. This
proves *functional* identity, which is what licenses transferring a movement. It does
**not** prove the two should cost the same — see "Latent value" below. Highest
confidence, and the only tier that should ever auto-apply.

**Tier B — near-functional.** Small functional divergence (`d ≤ 0.5` on max relative
deviation, rank 1 beating rank 2 by `≥ 0.05`). Real variants, not clones: a wall AC unit
with 60 HP against a cooler's 100, a wall television at 7 kg against 8. Still genuine
analogues that should inherit movement — but the algorithm cannot prove it. **Proposals
only, never auto-applied.**

Measured on the author's 305-mod list (Core-only vanilla, 4673 modded defs carrying
functional stats): tier A yields **10 pairs, zero ambiguity**, of which 7 are clearly
correct, 2 are wrong-sibling-right-family, 1 is wrong. Tier B adds roughly 40–120
depending on how the margin is set. Full numbers below.

**Critical direction: compare the modded def's CURRENT values against the vanilla
SNAPSHOT values.** The premise is that the modded item did not move and vanilla did.
Comparing against vanilla's live values would find nothing precisely in the cases that
matter.

**Do not expect stat values to be equal.** Measured: `VTE_WallMountedCooler` vs the
vanilla `Cooler` is 12.5% apart, `VTE_ACUnitWall` 40% apart — both correct matches with
all four comps identical and the same designation category. Authors tweak numbers;
tweaking is what makes it a variant. Stat distance is a *ranking* signal, never a
membership test.

Free consequences of that direction:

- Modded def matching vanilla's **live** values instead → it was already rebalanced →
  skip. That is the double-patch standdown, for free.
- Only **moved** vanilla defs are candidates, which shrinks the search space and
  removes most false-positive opportunity.
- If a rebalance mod changed a vanilla def's *stats*, the fingerprint still matches and
  the stat divergence is real but out of scope. Report it; do not fix it.

Results are written to `Config/UniversalRebalancer/auto-mappings.xml` in the same
format as hand mappings, regenerated each boot. The user can read exactly what matched
and suppress any entry from `personal.xml`.

**Tier B never auto-applies. Tier A auto-applies only behind a setting, defaulting off
until the error rate is measured on more than one modlist.** Measured on the test list,
tier A is 10 rows with 1 clear error and 2 wrong-siblings; tier B adds ~40 more at
visibly lower precision. Both are short enough to read in a minute, so the review-fatigue
argument that would justify silent auto-apply does not apply at this volume. Ship both as
a generated file the user promotes into `personal.xml` by deleting the lines they
disagree with.

Wrong-sibling errors are the benign failure: transferring the cooler's movement to a
wall heater is mostly harmless, because a rebalance mod almost certainly moved the
cooler and the heater together.

### Latent value — why identical function does not mean identical price

Price is not a function of measurable capability alone. A wall-mounted cooler has the
exact functional stats of a vanilla cooler and is still worth something different,
because mounting in a wall frees floor space. Footprint, placement rules, adjacency
requirements, whether it needs power, and plain aesthetics are all real value that no
stat records. Call it latent value.

Latent value is **fatal to absolute pricing** and **harmless to movement transfer**, and
that difference is the reason this design only ever transfers movement.

Worked example. VTE prices its wall cooler at 70 steel against the vanilla cooler's 90 —
a 0.78 ratio encoding whatever the author concluded about wall-mounting. A rebalance mod
moves the vanilla cooler to 135 steel. Ratio transfer puts the wall cooler at 105 and the
0.78 ratio survives untouched. **The latent value was never measured, never priced, and
never disturbed.** `copy` mode would destroy it; absolute-delta mode would distort it;
ratio mode preserves it by construction. This is principle 2 earning its keep.

What the design does *not* fix: if the author priced the latent value wrongly to begin
with, transfer faithfully preserves the mistake. This mod corrects **drift**, not
**original sin**. Original sin is dominance's department, and finding 5 below shows the
scan catching exactly that case in this very modlist.

Latent value is also **far more machine-readable than it first appears**, which is worth
exploiting. In the flagship case it is entirely legible in the XML: an extra comp
(`VEF.Buildings.CompProperties_MountableOnWall`), an extra placeWorker
(`PlaceWorker_OnWall`), and — decisively — `isEdifice: false`, `isAirtight` absent,
`passability: PassThroughOnly`, `fillPercent: 0.75`. Together those say "this mounts on a
wall rather than being one", which is exactly why it costs 70 steel instead of 90.

The first version of this design would have missed all of it and called the pair a clone.
The `vanilla comps ⊆ modded comps` gate already computes a comp *difference* set and
throws it away; the structural fields were not read at all. Both should feed the
proposal, and neither should feed a price.

Rule: **never price a latent-value difference, always flag it.** A proposal whose target
carries extra comps, a smaller footprint, or different placement rules should say so in
the generated file — "target has 1 comp the anchor lacks (`CompProperties_MountableOnWall`);
the price gap is probably deliberate" — so the human reviewing it knows why the numbers
differ instead of assuming the matcher erred.

### 5. Dominance scan — optional, deprioritised

**Demoted by the 2026-08-19 scope narrowing.** Dominance existed to *discover* items worth
looking at. Under the propagation framing the rebalance mod's patch set already names
every def that moved, so discovery is free and this mechanism is no longer on the critical
path. Keep it as a later addition for the case propagation cannot reach — an item
mispriced by its own author, with no rebalance mod involved. Everything below still holds
if it is built.



`A dominates B` when A is at least as good on every capability axis, no worse on every
cost axis, and strictly better somewhere. That is a *proof* of imbalance requiring no
threshold, no weights, and no effectiveness model. It is also the literal formalisation
of "why would I ever build a regular cooler."

v1 rules, chosen for zero tunable parameters:

- **Comparability**: identical functional key sets — the widened set, not just
  `statBases`. Same gate as the fingerprint: fingerprint asks "are the values equal?",
  dominance asks "are they ordered?" One code path, two predicates.
- **Structural difference ⇒ incomparable.** Any divergence in `fillPercent`,
  `passability`, `size`, `placeWorkers`, `building/isEdifice` or `building/isAirtight`
  disqualifies the pair. These encode capability the algorithm cannot rank, and without
  this rule the scan reports the wall-mounted cooler as a violation — a false positive on
  the project's own flagship item. See finding 5.
- **Capability**: stat values ordered consistently, using a shipped direction table
  (~30–50 common stats). Any stat with unknown direction makes the pair
  **incomparable** — conservative, keeps the report short and high-precision.
- **Cost**: elementwise on the material vector plus `workToBuild`. No scalar
  valuation, so no material-value weighting and no circularity with repricing.
  Different material sets → incomparable.
- At least one side modded. Vanilla↔vanilla is presumed intentional.

Output is a readable report file listing violations in prose. **Dominance never
patches.** It has no opinion about what the price should be — only that an ordering is
broken. The fix path is: user reads the report, writes a mapping.

Coverage is deliberately sparse. High precision, low volume, no review fatigue.

### Load sequence

1. Load snapshot.
2. Compute moved set.
3. Load and merge hand mappings (mod folder, then personal).
4. Fingerprint pass over unmapped modded defs; write `auto-mappings.xml`.
5. Validate all mappings; **skip and log, never crash**.
6. Apply transforms.
7. Dominance scan; write report.
8. Log summary.

Runs at startup after defs load and patches apply, before caches warm. "Restart to
apply" convention. Likely **no Harmony dependency** — direct def mutation plus a
possible stat-cache clear.

### Validation

Missing `base` or `target` defName (mod uninstalled, renamed, typo), base not in the
moved set (silent no-op, not an error), field-shape mismatch, duplicate target. Half of
any real user's list will reference mods they have removed — graceful degradation is
the entire UX.

### defName discovery

The actual friction in hand-maintaining the list: the user knows "over-wall cooler",
not `WallStuff_OverWallCooler`. Ship a dev-mode debug action on the inspect pane that
dumps the selected thing's defName and source mod. **Build this first** — everything
else can be alt-tab and a text editor for a long time.

## Non-goals

- No clustering, no buckets, no distance metrics, no per-category nearness.
- No functional-stat changes, ever.
- No in-game review/browse UI in v1.
- No absolute price prediction. The mod only transfers movements that a rebalance mod
  already decided on.
- No discovery of problems in items the user never builds. Dominance covers part of
  this; the rest is accepted loss.

## v1 scope

Snapshot generator + snapshot file, `MappingDef` and loader, transform engine (5 fields,
4 modes), applier, validation logging, fingerprint matcher, dominance scanner + report,
stat direction table, defName debug action, a handful of mod settings.

Modest — roughly a weekend or two of work, and it is the substrate every more ambitious
version needs anyway.

## Precedents

- **RIMMSqol** — runtime def editing with persistence. Proves runtime mutation +
  restart-apply is viable; this is the automated version.
- **Cherry Picker** — runtime DefDatabase surgery at scale.
- **Mod Medicine Patch** — dynamic detection and scaling of modded medicines; single
  hardcoded bucket.
- **CE experimental autopatcher** — algorithmic per-category stat generation for
  unpatched weapons/animals. Closest existing thing, and its hand-written patch library
  is a useful validation corpus — but it is weapons/animals-focused and thin for
  buildables, and its analogue notion is combat-profile, not cost.

## Technical notes

- Plain RimWorld 1.6 mod. CE not required. Harmony likely not required.
- packageId `eebette.UniversalRebalancer`, display name "Universal Rebalancer".
- No ML, no clustering, no runtime inference of any kind.

## Open questions

1. ~~`statTolerance` default.~~ **ANSWERED — see "Experiment: fingerprint distances"
   below.** There is no useful tolerance. Thresholding was the wrong primitive; the
   fingerprint now ranks and abstains on margin.
2. Snapshot format and size (JSON vs XML, compressed?), and the DLC-combination story.
3. Stat direction table: hand-authored list, or is there a usable `higherIsBetter`-style
   signal on `StatDef`? Verify against 1.6 source before hand-authoring.
4. Save-compat mid-colony. `costList` changes look refund-safe-ish. Research re-gating
   of an already-built item's tech is unverified.
5. Rescan cadence — every load, or only on modlist-hash change?
6. ~~Whether auto-apply should default on.~~ **ANSWERED — no.** ~5% error rate, ~40
   rows. Proposal list, not silent apply.
7. Distribution: Workshop vs GitHub-only during the experimental phase.
8. Whether mapping files should carry a schema version from day one (probably yes —
   cheap now, expensive to retrofit once people are sharing them).
9. Coverage is thin — tier A is 10 pairs and tier B ~50, against 4673 modded defs on
   the test list. Most of that gap is correct (Rimatomics and Alpha Biomes content
   genuinely has no vanilla analogue), but the `comp ⊆` and
   non-empty-`designationCategory` gates cost real recall on non-buildings, which have
   few comps and no category. Worth measuring before deciding whether items, weapons
   and apparel need their own gate set.
10. Whether to run the fingerprint against DLC vanilla too. The test machine has Core
    only, so the measured coverage is a floor.
11. **Widened fingerprint, unmeasured.** Finding 5 says the functional fingerprint must
    include comp property values and structural fields. Everything measured so far used
    `statBases` only. Re-run the ablation with the widened fingerprint before trusting
    any tier A number — precision should rise and coverage should fall, but by how much
    is unknown.
12. **`LoadFolders.xml` support.** The harness reaches 72% of def files; nested
    mod-bundle layouts and remaps account for the rest. Needed both in the experiment
    and in the mod itself, since the mod reads the live `DefDatabase` but the snapshot
    generator does not.
13. Which comp properties are functional versus lever-ish. `basePowerConsumption` is
    function; is a workbench's `WorkTableWorkSpeedFactor`? Needs a curated list, same
    shape as `LEVER_STATS`.

## Worked example: the real case, on the real modlist

`tools/who_patched.py` replays RimWorld's PatchOperation pipeline offline and
attributes every change to the mod that made it. Run against the whole temperature-control
family — every def carrying `CompProperties_TempControl`, 15 of them:

```
python3 tools/who_patched.py $(list of TempControl defNames)
```

**Exactly one mod moved anything: `mopolita.bame.morematerials` (More Materials). It
patched exactly the two vanilla defs.**

| def | source | final costList | patched by |
|---|---|---|---|
| `Cooler` | Core | 90 Steel, 3 Component, **5 ME_Copper, 2 ME_Lithium** | More Materials |
| `Heater` | Core | 50 Steel, 1 Component, **5 ME_Copper, 3 ME_Tin, 2 ME_Nickel** | More Materials |
| `VTE_WallMountedCooler` | VTE | 70 Steel, 3 Component | — |
| `VTE_ACUnit` | VTE | 120 Steel, 3 Component | — |
| `VTE_ACUnitWall` | VTE | 80 Steel, 3 Component | — |
| `VTE_IndustrialCooler` | VTE | 180 Steel, 4 Component | — |
| `VTE_WallMountedHeater` | VTE | 40 Steel, 1 Component | — |
| `VTE_WallHeater` | VTE | 60 Steel, 1 Component | — |
| `VTE_IndustrialHeater` | VTE | 90 Steel, 2 Component | — |
| `AB_PropaneHeater` | Alpha Biomes | 50 Steel, 20 CrystalWood, 1 Component | — |
| …5 more | | | — |

Two vanilla defs gained exotic materials. **Thirteen functionally-equivalent modded
buildings did not.** That is the patch lattice, in the wild, from a single rebalance mod,
and it is why the regular cooler stops being worth building.

Note the shape: the change is an **added ingredient**, not a scalar price rise. Scalar
ratio propagation cannot express it. This is the composition-transfer case, and it is the
common case rather than an exotic one.

What the mod would propose, ratio mode, new materials added proportional to the anchor's
steel mass (`5/90` copper and `2/90` lithium for the cooler family):

| target | current | proposed |
|---|---|---|
| `VTE_WallMountedCooler` | 70 Steel, 3 Comp | + 4 ME_Copper, 2 ME_Lithium |
| `VTE_ACUnit` | 120 Steel, 3 Comp | + 7 ME_Copper, 3 ME_Lithium |
| `VTE_ACUnitWall` | 80 Steel, 3 Comp | + 4 ME_Copper, 2 ME_Lithium |
| `VTE_IndustrialCooler` | 180 Steel, 4 Comp | + 10 ME_Copper, 4 ME_Lithium |
| `VTE_WallMountedHeater` | 40 Steel, 1 Comp | + 4 ME_Copper, 2 ME_Tin, 2 ME_Nickel |
| `VTE_WallHeater` | 60 Steel, 1 Comp | + 6 ME_Copper, 4 ME_Tin, 2 ME_Nickel |
| `VTE_IndustrialHeater` | 90 Steel, 2 Comp | + 9 ME_Copper, 5 ME_Tin, 4 ME_Nickel |
| `AB_PropaneHeater` | 50 Steel, 20 CrystalWood, 1 Comp | + 5 ME_Copper, 3 ME_Tin, 2 ME_Nickel |

Thirteen concrete proposals from two observed movements. Note that steel is untouched
throughout — the anchor's steel did not move, so neither does the target's, and each
building keeps whatever premium or discount its author intended.

Coverage check against the fingerprint: `VTE_WallMountedCooler → Cooler`,
`VTE_WallMountedHeater → Heater` and `AB_PropaneHeater → Heater` are tier A matches on
functional stats. `VTE_ACUnitWall` (60 HP) and `VTE_IndustrialCooler` (200 HP) are real
variants and fall to tier B or the hand list — where a human adds them in about thirty
seconds each.

**A caveat this example exposes:** the runtime design compares live defs against the
vanilla snapshot and takes the net, which needs no attribution. That is still correct for
the *math*. But "More Materials did this" is exactly what a user wants to read on a
proposal, and net-delta cannot produce it. Attribution is a UI nicety, not a correctness
requirement — worth revisiting if the PatchOperation hook is ever built for other reasons.

## Census: how many rebalance mods are there actually?

`tools/rebalance_census.py` applies every mod's patches cumulatively in load order
and attributes each **lever** change — costList, costStuffCount, `WorkToBuild`,
`WorkToMake`, `MarketValue`, research — to the mod that made it. Counting only costList
undercounts badly; the biggest patcher on this list touches no costList at all.

Identical results for the 306 active mods and for all 328 installed, so nothing is hiding
among the disabled ones.

| mod | defs changed | foreign | levers | top targets |
|---|---|---|---|---|
| `hawkwood.floorsarealmostworthless` | 746 | 746 | stat | morefloors: 642 |
| `ceteam.combatextended` | 109 | 109 | cost, stuff, stat | VFE Pirates: 40, Core: 16 |
| `mopolita.bame.morematerials` | 55 | 55 | cost, stuff | **Core: 55** |
| `yorbil.missingfabricationrecipes` | 6 | 6 | cost | Core: 6 |
| 4 others | 1 each | 1 | mixed | Core |

**Eight mods total, two of consequence.** On this list the "N rebalance mods × M content
mods" matrix is a single row. That is one sample and other players run overhauls this list
does not — but the premise is not supported here, and anyone reasoning about scope should
run this against their own `ModsConfig.xml` before assuming a lattice.

### Three strategies, and the third one dissolves the problem

The census separates rebalance mods into three kinds by how they treat modded content:

1. **Per-def, vanilla only** — More Materials. 55 patches, all 55 on Core. Every modded
   equivalent is stranded. This is the entire problem.
2. **Per-def plus hand-written compatibility** — Combat Extended. 109 patches, 40 of them
   aimed at VFE Pirates specifically. Correct, laborious, and only covers mods the author
   chose to support.
3. **Categorical xpath** — Floors Are Almost Worthless. **746 defs from a single
   operation:**

   ```xml
   <xpath>/Defs/TerrainDef[boolean(statBases)]/statBases[boolean(MarketValue)]/MarketValue</xpath>
   <value><MarketValue>0</MarketValue></value>
   ```

   Every modded floor, automatically, including mods released after it. No compat patches,
   no analogue matching, no tooling, no maintenance, forever.

**Strategy 3 is the correct one and it is available to any mod author today.** The problem
this project exists to solve is entirely an artifact of authors choosing strategy 1.

### Which suggests a different deliverable

Not "More Materials + VTE compat patch" — that covers VTE, needs a sibling for every other
content mod, and goes stale on update. Instead: **convert strategy 1 into strategy 3.**
Derive a handful of categorical xpath rules from More Materials' 55 per-def edits and ship
them as a pure XML patch mod that covers every content mod, present and future.

Rough shape from the rule analysis below — conduits take copper 1:1 with steel, electronics
about 0.2:1, heating elements copper plus tin and nickel, heavy mechanical cast iron plus
copper. Perhaps five to ten rules. RimWorld xpath can select on the relevant evidence
(`costList/ComponentIndustrial`, `comps/li[@Class="CompProperties_Power"]`,
`designationCategory`), so the rules are expressible.

**This has a free validation loop.** Derive the rules from the 55 anchors, then check the
rules reproduce those same 55 edits. If eight xpath rules regenerate 45 of More Materials'
own 55 patches, that is strong evidence they generalise to content the author never saw.
No hand labels required.

And it needs **no C# whatsoever** — no runtime mod, no vanilla snapshot, no load-time
applier, no mapping file format. A pure XML patch mod, publishable in days.

### Tested: partially. One rule carries the bulk, the tail does not reduce.

`tools/derive_rules.py`. Key decomposition: do **not** model the 35 added-material
*signatures*. Model each **material** separately — "which defs get copper?" is one binary
rule over 55 labelled examples, and the signatures are just intersections of those rules.
That turns 35 combinations into 11 questions.

Features offered to the search are only things an xpath can select on: comp classes,
`designationCategory`, `thingClass`, `thingCategories`, costList keys, statBases keys,
`building/*` flags. Conjunctions up to two terms, scored by F1 against the mod's own edits.

**Copper reduces cleanly, and the rule is the one the author was actually following:**

| material | defs | best rule | F1 |
|---|---|---|---|
| `ME_Copper` | 48 | `comps` contains `CompProperties_Power` | **0.83** |
| `ME_ElectrumIngot` | 8 | `building/shipPart` | 0.71 |
| `ME_Nickel` | 23 | power comp AND `WorkToBuild` | 0.63 |
| `ME_CastIronIngot` | 26 | power comp AND costs `ComponentIndustrial` | 0.61 |
| `ME_Zinc` | 14 | power comp AND `thingClass=Building` | 0.58 |
| `ME_BrassIngot` | 10 | `stat=ShootingAccuracyTurret` | 0.53 |
| `ME_Tin` | 8 | glower comp AND `Mass` | 0.53 |

*Electrical things need copper wiring* is a real rule, it covers 48 of the 55 patched defs,
and the search recovered it unprompted. The tail is overfitting: "turrets get brass" from
four examples, and the tin rule is noise.

**Whole-set reproduction: recall 73%, precision 61%** — 113 of 155 material-assignments
recovered, 71 false positives. Not shippable blind.

**Coverage, which is the prize: 236 modded defs across 44 content mods.** Against 6 (tier A)
or 18 (tier B) for per-def analogue matching. Two orders of magnitude is the difference
between a compat patch and a solution.

### Amount is a separate problem, and it is not proportional

`tools/amount_model.py`. Selection ("which defs get copper") and amount ("how much")
are different questions; the second is the harder one.

**The apparent 1:1 "wire" population does not exist.** Only 2 of 48 copper recipients sit
at 1:1, and both have ≤3 Steel — `PowerConduit` at 1 and `HiddenConduit` at 2. Any
proportional rule with a floor of 1 produces exactly that. `WaterproofConduit`, which is a
conduit, is at 0.20. It is a rounding floor, not a regime, and excluding those two changes
nothing: median r is 0.133 with them and 0.133 without.

**The real structure is that the ratio falls with recipe size.** `WallLamp` 15 Steel → 5
copper (r=0.333), while `Turret_Autocannon` 350 Steel → 10 copper (r=0.029). Turrets at
200, 300 and 350 Steel all receive **exactly 10**. Model comparison, median relative error
and share landing within ±35%:

| model | copper | cast iron |
|---|---|---|
| median ratio × Steel | 46% | 46% |
| median ratio, floor 1 | 48% | 46% |
| median of r<1 only, floor 1 | 48% | 46% |
| best-fit linear k, floor 1 | 50% | 54% |
| constant, ignore size | 62% | 42% |
| **power law** | **69%** | **62%** |

Fits: copper `1.30 × Steel^0.47`, cast iron `2.13 × Steel^0.51`. Two materials, independent
data, both exponents at ~0.5. **The added amount tracks the square root of recipe size.**

Most likely because the author picks round numbers from a short menu — 1, 2, 5, 8, 10, 15,
30 — only loosely coupled to bulk. A turret is mostly barrel and chassis; its wiring harness
does not scale with the barrel. Square root is what that looks like when regressed.

**Consequence, now fixed in `propose.py`:** transfer scaling was linear in shared material
mass. It is now `(target mass / anchor mass) ** 0.5`. The difference is small for close
analogues — a 70-Steel wall cooler against a 90-Steel anchor lands on 4 copper either way,
which is why tier A survived the error — and grows with size divergence: the drone tinkering
bench at 160 Steel against a 100-Steel anchor drops from 17 copper to 13.

This matters far more for **categorical rules than for analogue transfer.** An analogue is
close to its anchor in size by construction, so linear is nearly right. A categorical xpath
rule has to span 1 to 350 Steel in one expression, and there the exponent is the whole
ballgame.

### There is no 80/20 here — ship all eight rules

A first pass ranked rules greedily by *modded defs touched at least once* and concluded
copper alone was 83% of the value. **That metric was wrong and it flattered copper.** Cast
iron went to 26 vanilla defs and nickel to 23; both scored "0 new" only because copper had
already claimed the same defs. They would add *materials* to those defs, which is exactly
the value the metric discarded.

Counted properly, by material-assignment, and with the guard below applied to the false
positives:

| # | material | F1 | assignments | cumulative | vanilla FP |
|---|---|---|---|---|---|
| 1 | `ME_Copper` | 0.83 | 196 | 29% | 4 |
| 2 | `ME_Nickel` | 0.63 | 190 | 57% | 3 |
| 3 | `ME_CastIronIngot` | 0.61 | 154 | 80% | 1 |
| 4 | `ME_Tin` | 0.53 | 47 | 87% | 2 |
| 5 | `ME_Lead` | 0.50 | 32 | 92% | 0 |
| 6 | `ME_Zinc` | 0.58 | 27 | 96% | 0 |
| 7 | `ME_BrassIngot` | 0.53 | 24 | 99% | 0 |
| 8 | `ME_BronzeIngot` | 0.67 | 4 | 100% | 0 |
| | **total** | | **674** across 236 defs | | **10** |

**Copper alone ships 29%, not 83%.** Three rules reach 80%; it takes all eight to finish.

The weak F1 scores were the second half of the mistake. They are computed *without* the
guard, and badly overstate the damage: nickel at "F1 0.63" costs three vanilla false
positives, cast iron at 0.61 costs one. Guarded, the entire eight-rule set costs ten. Given
the asymmetric loss above, all eight are worth shipping.

**Shipped artifact: `patches/MoreMaterials_Universal.xml`** — 24 PatchOperations across
eight materials, generated by `pareto.py --emit 99`, XML-validated, every xpath compiled.

Amounts are size bands rather than a ratio, because xpath cannot compute a square root and
bands match how the author actually picks numbers. Copper's fitted band medians recover his
menu exactly: **≤5 Steel → 2, 5–30 → 5, 30–100 → 10, 100+ → 15.** Bands also bound the
output, so no pathological recipe yields a pathological amount.

Two deliberate choices worth knowing. `contains(@Class, "CompProperties_Power")` rather than
an exact match, so namespaced modded power comps are caught — it picks up
`VanillaQuestsExpandedTheGenerator.CompProperties_PowerGenetron` (18 defs), a real power comp
an exact match would miss. And the guard is `not(costList/*[starts-with(name(), "ME_")])`
rather than `not(costList/ME_Copper)`, which both makes the patch idempotent and respects
the author's existing choices — see below.

### The loss function is asymmetric, and that changes the verdict

Accuracy percentages framed against "the author's exact number" were the wrong yardstick.
The baseline is not a correct price — it is a modded cooler requiring **zero** copper while
the vanilla one requires five. That is not a 20% error, it is a **categorical** one: the
item bypasses the copper economy entirely, which is the whole point of the mod.

Scored on the 48 vanilla defs where the author's amount is ground truth:

| | median relative error | within 2× |
|---|---|---|
| banded rule | **0.25** | **98%** |
| do nothing | 1.00 | 0% |

**The copper requirement itself is imposed correctly 48 out of 48 times**, and exactly one
def receives more than double his amount. Being off on quantity is a rounding difference;
requiring no copper at all is the bug. The banded form also caps the output at 15, so no
pathological recipe can produce a pathological amount — a ratio would have extrapolated.

### The false positives were mostly not exclusions

Inspecting all 10 changed the design. Six are **ship and spacer tech the author did patch**
— he gave them `ME_ElectrumIngot` instead of copper, a deliberate thematic choice. They were
never exclusions; the rule was second-guessing a decision he had already made.

Fixed with one predicate: `not(costList/*[starts-with(name(), "ME_")])` skips any def he
already touched with any of his materials. **False positives drop 10 → 4, modded coverage
stays at 196.**

The remaining four are all benign, and one is a bug fix:

- **megascreen television** — he gave copper to two televisions and missed this one. The
  rule fixes his omission.
- **infinite chemreactor**, **vanometric power cell**, **psychic emanator** — archotech, not
  craftable, so the added cost is never paid.

Which leaves zero harmful false positives on vanilla, from a rule fitted in one pass.

### The actual result: the unit of human review changed

61% precision means over-applying to 71 Core defs the author deliberately left alone. That
needs human correction — but **there are only 11 rules to correct.** A person reads them in
five minutes, keeps `power comp → copper`, deletes `turrets → brass`, and hand-writes the
tail.

That is the same "suggest, never impose" principle as ever, applied at the **rule** level
instead of the item level. Every earlier design in this document asked a human to review
hundreds of per-item proposals. This asks for eleven. That ratio, not the F1, is the finding.

Shape of the deliverable: one or two categorical xpath rules doing the bulk, a hand-written
tail for the rest, shipped as pure XML. No C#, no snapshot, no applier, no mapping format,
and it covers content mods that do not exist yet.

## Is a materials mod a rule? No — measured

`tools/mod_rule.py` applies one mod's patches and groups every changed costList by
the signature of what was added, reporting whether the amounts are constant or
proportional to existing cost. If a materials mod were expressing a formula, you could
fit it once and apply it everywhere, and analogue matching would be unnecessary.

It is not a formula. More Materials, 61 changed costLists:

- **35 distinct added-material signatures** across 61 defs — about 1.7 defs per signature.
- Ratios are not constant within a signature. Coefficient of variation on
  added-per-steel runs 0.26 to 1.13.
- The copper-only group makes the point: conduits get copper **1:1 with steel**
  (`PowerConduit` 1 steel → 1 copper) because wires are copper, while televisions get
  about **0.2:1** (`FlatscreenTelevision` 140 steel → 30 copper). Two different rules
  inside one signature.
- The author's classes are not any machine-readable field. The
  `ME_Copper + ME_Nickel + ME_Tin` group — heating elements — spans `designationCategory`
  values `Power`, `Production` **and** `Temperature`.

So: copper for electrical, cast iron for heavy mechanical, tin and nickel for heating
elements. Coherent thematic judgment, authored by hand, per item. Learnable by a human in
one reading and not expressible as a fitted function over def fields.

**Therefore analogue matching stays** — but against the tiny anchor set, which is what
makes it work.

## Prototype: end-to-end proposals

`tools/propose.py` runs the whole pipeline offline: replay a rebalance mod's
patches, take the defs whose costList gained materials as anchors, fingerprint modded defs
against **only those anchors**, and scale the composition change by the ratio of shared
material mass.

```bash
python3 tools/propose.py mopolita.bame.morematerials --tier a
```

| | tier A | tier B |
|---|---|---|
| proposals | 6 | 18 |
| abstained ambiguous | 0 | 2 |
| anchors that stranded something | 3 | 9 |

Sample output, and note the arithmetic — the wall cooler is 70 steel against the anchor's
90, so it gets 7/9 of the addition:

```
  wall-mounted cooler                [vanillaexpanded.temperature]
      anchor Cooler  (d=0.000)
      now      3 ComponentIndustrial, 70 Steel
      proposed 3 ComponentIndustrial, 70 Steel, 4 ME_Copper, 2 ME_Lithium
```

**Coverage is the weak spot, and the cause is known.** The temperature family alone has 13
stranded modded defs; tier A reaches 4 of them. Two concrete failures, both from gates
that are too brittle:

- `AB_PropaneHeater` has functional stats *identical* to `Heater` and is still rejected,
  because it burns propane rather than electricity, so it lacks `CompProperties_Power` and
  fails `vanilla comps ⊆ modded comps`.
- `VTE_WallHeater` matched **`Cooler`** instead of `Heater` — `Heater`'s `statBases`
  include `Mass: 6` and the wall heater's do not, so exact key-set identity blocks the
  correct anchor and the next-best wrong one wins. It is consequently being offered
  lithium, a cooling material, instead of tin and nickel.

Both are the same flaw: **exact key-set identity and comp-subset are too strict.** A
single missing `Mass` entry or a swapped power source breaks an otherwise perfect match.
The obvious fix is key-set *overlap* with distance on the intersection, plus "shares the
defining comp" instead of full subset — but that is a hypothesis, and the three bugs
below are what happens when hypotheses here go unmeasured. Measure before adopting.

## Experiment: fingerprint distances

`tools/fingerprint_histogram.py` and `tools/gate_ablation.py`. Pure offline
XML parse of the author's real modlist — no game run, no PatchOperations applied.
RimWorld 1.6.4871, Core only, 305 active mods, 3424 def files, 693 vanilla and 4673
modded defs carrying functional `statBases`.

**Finding 1 — lever fields inside `statBases` corrupt everything.** The first run of
this experiment treated `WorkToBuild` as an identity stat and concluded the whole
fingerprint approach was unworkable. That conclusion was an artifact. See "THE RULE THAT
MAKES THIS WORK" above; every number below is post-fix. A second, smaller bug: Core defs
were being resolved against mod-redefined abstract parents (`ods.tavern` shadows the
Core `Bed` and `DoubleBed` `Name`s), leaking mod values into the supposed vanilla
baseline. Core now resolves against a Core-only `Name` index.

**Finding 2 — the distance distribution is sharply bimodal, but the near mode is mostly
the wrong population.** 700 modded defs sit at *exactly* distance 0 from some vanilla
def; the region between 0 and 0.02 holds a single def. A textbook gap. But much of the
zero mode is terrain (soils, sands, flagstones), vanilla bionic templates, and junk
coincidences: `plant meat → agave fruit`, `random bricks → unfinished apparel`,
`black volcanic sand → Ice`. Median 16 vanilla candidates share a given stat key set.
**Exactness alone is nearly worthless; exactness plus structural gates plus uniqueness is
what carries signal.**

**Finding 3 — the flagship case is an exact functional match once levers are excluded.**

| modded | vanilla | functional distance | lever gap |
|---|---|---|---|
| `VTE_WallMountedCooler` | `Cooler` | **0.000** | `WorkToBuild` 1400 vs 1600 |
| `VTE_WallMountedHeater` | `Heater` | **0.000** | `WorkToBuild` 800 vs 1000 |
| `VFES_WallMountedTelevision` | `FlatscreenTelevision` | 0.125 (`Mass` 7 vs 8) | 45000 vs 40000 |
| `VTE_ACUnitWall` | `Cooler` | 0.400 (`MaxHitPoints` 60 vs 100) | none |

The bottom two are not clones. They are real variants with real functional differences,
and no tolerance catches them without also admitting garbage. That is what tier B and
the hand list are for.

**Finding 4 — gate ablation.** Scored on an independent proxy (label-token overlap; the
matcher never reads labels, so name agreement cannot be gamed by the features under
test):

| config | kept | abstained | name-overlap | flagship |
|---|---|---|---|---|
| `d ≤ 0.02` + comps ⊆ | 510 | 0 | 50% | 2/4 |
| structural gates, rank only | 1526 | 0 | 29% | 4/4 |
| + margin ≥ 0.05 | 729 | 797 | 30% | 3/4 |
| + non-empty designationCategory | 123 | 48 | 45% | 3/4 |
| + cap `d ≤ 0.5` (tier B) | 52 | 20 | 62% | 3/4 |
| **functional-exact + gates + unique (tier A)** | **24** | **10** | **74%** | **2/4** |
| **tier A + levers must actually differ** | **10** | **0** | **67%** | **2/4** |

No config dominates: exactness buys precision and loses the real variants; the margin
gate buys precision and sometimes rejects a correct match as ambiguous. Hence two tiers
rather than one tuned threshold.

Hand-checking all 10 of the tightest config: 7 clearly correct (`wall-mounted cooler →
cooler`, `wall-mounted heater → heater`, `wall-mounted vent → vent`, `embrasure → wall`,
`animal gate → fence`, `assembly bench → fabrication bench`, `drone tinkering bench →
fabrication bench`), 2 wrong-sibling-right-family (`wall heater → cooler`,
`fueled smelter → fueled stove`), 1 wrong (`wool loom → brewery`).

**Finding 5 — `statBases` is not where RimWorld keeps function, and assuming otherwise
manufactures false dominance violations.**

The flagship pair looked like a slam-dunk violation: identical functional `statBases`,
identical `thingClass` and `designationCategory`, all of the cooler's comps *plus*
`VEF.Buildings.CompProperties_MountableOnWall`, and cheaper on both levers (70 steel /
1400 work against 90 / 1600). Better and cheaper, before any rebalance mod runs.

It is not. Reading the fields the fingerprint ignores:

| field | `VTE_WallMountedCooler` | `Cooler` |
|---|---|---|
| cooling (`energyPerSecond`) | −21 | −21 |
| power draw | 200 W | 200 W |
| research | AirConditioning | AirConditioning |
| `fillPercent` | 0.75 | 1 |
| `passability` | PassThroughOnly | Impassable |
| `building/isEdifice` | false | *(true)* |
| `building/isAirtight` | — | true |
| `placeWorkers` | `PlaceWorker_OnWall`, `PlaceWorker_Cooler` | `PlaceWorker_Cooler` |

The vanilla cooler **is a wall segment** — airtight, impassable, an edifice. VTE's
**mounts onto a wall you already built** and seals nothing by itself. The discount is
VTE pricing "you supply your own wall." Defensible, deliberate, and invisible to a
`statBases` comparison.

Consequences for the design:

- **Widen the functional fingerprint** beyond `statBases`: comp *property values*
  (`energyPerSecond`, `basePowerConsumption`, storage capacity, joy), `fillPercent`,
  `passability`, `size`, `placeWorkers`, and `building/isEdifice` / `isAirtight`. Cooling
  power — the entire point of a cooler — lives in a comp property, and the first version
  of this fingerprint never looked at it.
- **Dominance must abstain on structural difference.** Any divergence in the fields above
  makes a pair incomparable. Without that rule the scan reports this pair as a violation,
  which is a false positive on the single most-examined item in the project.
- **Transfer is unaffected**, which is the point of principle 2. Ratio transfer preserves
  the 70/90 ratio and therefore preserves VTE's "supply your own wall" discount, without
  ever having to price it.

**Finding 6 — parser coverage is 72%.** The harness scans `Defs/`, `1.6/Defs/` and
`Common/Defs/`, and 1104 of 3978 def files on this modlist live elsewhere — nested
mod-bundle layouts (`1.6/Mods/<name>/Defs/`) and `LoadFolders.xml` remaps. Combat
Extended alone accounts for 455. Every coverage number here is therefore a **floor**, and
`LoadFolders.xml` support is required before any of these counts should be quoted as
final.

**Reproduce:**

```bash
python3 tools/fingerprint_histogram.py   # parse, histogram, dump corpus.json
python3 tools/gate_ablation.py           # gate ablation over that corpus
```

Limitations, all documented in the report output: PatchOperations are not applied
(fine for this question, wrong for real runtime numbers), `LoadFolders.xml` is ignored,
inheritance is an approximation of RimWorld's `XmlInheritance`, and no DLC is installed
so the vanilla side is Core only.

## Rejected alternatives

Kept so the reasoning is not re-derived from scratch.

### Emergent functional clustering (the original design)

Feature-vector every def (thingClass, comps, designationCategory, placeWorkers,
`statBases` key shape, size, roles, research position), Jaccard similarity,
hierarchical agglomerative clustering, linkage cutoff as the bucket knob; then
per-bucket suggestion tiers (anchor-delta / bucket baseline / global economy priors)
across five category engines plus a research-gating engine, with an in-game bucket
browser.

Why rejected:

- **Solves a superset problem.** The task needs *pairs* (this modded item ↔ its
  analogue). Clustering builds *partitions* — global cutoff, feature weights, no ground
  truth, and it fails silently.
- **Clustering is a total function; the problem is partial.** Most modded defs have no
  vanilla analogue and should return nothing. Clustering has no abstain primitive.
- **Stop-word comps dominate the metric.** `CompPowerTrader`, `CompFlickable`,
  `CompBreakdownable` sit on nearly every powered building, so unrelated items share
  most features before any function signal appears. Fixing that means IDF-style
  weighting — another tuned knob.
- **Heterogeneous features aren't one metric.** Sets, scalars, and graph positions
  binarised into one Jaccard space, or a weighted Gower distance with per-class hand
  weights. Either way, not one knob.
- **A single global linkage cutoff assumes uniform density.** Def-space is not uniform;
  sparse regions shatter while dense regions fuse. Single-linkage additionally chains
  across themes, which is what principle 4 was written to prevent.
- **The comp-fragmentation fix reintroduced the banned mechanism** — bridging
  mod-private comp classes with "carefully weighted" text similarity.
- **Sub-anchor tiers need hardcoded domain knowledge.** "Cost-per-effectiveness" is
  undefined for an emergent device type without knowing which stats matter, which is
  exactly the per-category table the "no hardcoded categories" headline disclaimed.
- **Tier 3 fits priors on the population it distrusts**, absorbing the corruption it
  exists to detect.
- **Scale claim was wrong.** "Milliseconds" — a 300-mod list reaches 10–20k ThingDefs
  counting generated defs; a pairwise matrix is hundreds of MB.

The name-vs-structure inversion is the core lesson: the original design used *structure
for retrieval* (poor recall — fragmented comps, mod-private types) and demoted *names to
tie-breakers* (their precision problem). Names retrieve well and verify badly; structure
verifies well and retrieves badly. The current design sidesteps the trade entirely by
having a human do retrieval and structure do verification.

### Raw-XML baseline reconstruction

Re-read unpatched XML from mod folders and diff against live defs. Requires re-running
def inheritance (`ParentName`/abstracts), cross-mod defName override by load order,
version folders and `LoadFolders.xml` — half a loader reimplementation. Replaced by the
shipped vanilla snapshot, which covers where nearly all rebalance patches land.

### PatchOperation hooking for attribution

Harmony-hook patch application at load to record per-mod per-def touches. Genuinely
cheaper than XML reconstruction and gives attribution — but attribution turned out to be
unnecessary once the semantics were fixed to "net movement vs vanilla baseline." Revisit
only if modded `base` defs are supported.

### Basis-transform regression

Fit a rebalance mod's transformation on the price basis (material substitution matrix,
work scaling) across all defs it touched, then apply to untouched defs. Statistically
much stronger than per-anchor propagation, and its fit residuals would self-report when
a mod is bespoke rather than systematic. Rejected for v1 only on scope; it is the
natural upgrade to the transform engine once mappings exist to validate it against.

### Offline LLM-generated analogue map

Precompute analogue pairs over popular mods offline, ship as static data. Good bootstrap
value, but it can be wrong in confident-sounding ways and carries permanent
re-generation and curation cost. Hand-maintained + community mappings cover the same
ground with better provenance.

### Corpus-and-matcher

Hand-label a stratified random sample of a real modlist, tune a gated k-NN matcher
against it. Rigorous, and the labeling exercise would itself have tested the premise
cheaply — but the current design gets the same labels for free, from the user at the
moment of annoyance, in the exact format the applier consumes. If the fingerprint
histogram in open question (1) looks bad, this is the fallback worth reviving.

### Exact-ish stat fingerprinting over the whole of `statBases`

"Match if `statBases` key sets are identical, all values within `statTolerance`
(default 0.02), and vanilla's comps are a subset of the modded def's." Auto-apply on,
tight tolerance as the safety mechanism.

Two lessons, both bought with measurement rather than argument.

**The fatal flaw was including lever fields**, not the tolerance. `WorkToBuild` lives in
`statBases`, so the identity test was penalising exactly the divergence the mod exists to
detect. Excluding levers takes the flagship cooler and heater from "rejected at 12.5% and
20% apart" to "exact match, with the lever gap as the payload".

**The tolerance was still wrong, just less catastrophically.** Even lever-clean, exact
matching misses real variants — a wall AC unit at 60 HP against a cooler's 100 is a
genuine analogue and a genuine non-clone. Hence tier A and tier B rather than one
threshold.

Worth keeping: **absolute closeness proves little in a def space full of copy-pasted
templates — median 16 vanilla defs share any given stat key set — so uniqueness after
structural gating does the real work.**

### Global optimisation

Solve for the minimal set of price edits making the economy self-consistent. Principled
and unreviewable — a user cannot cherry-pick from a global optimum, and reviewability is
the binding product constraint.
