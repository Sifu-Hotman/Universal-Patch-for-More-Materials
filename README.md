# Universal Rebalancer

**Status: placeholder — design-doc stage, no code, no build commitment.** This README
captures the full design as discussed 2026-08-17; an agent picking this up cold
should read it as the spec-so-far plus open questions, not as a finished design.

## Objective — the patch-lattice problem

Rebalance mods patch vanilla defs; functionally-analogous modded items keep their
vanilla-era stats. Example: a materials/rebalance mod tweaks the vanilla cooler's
cost and numbers; the "over-wall cooler" from another mod still matches vanilla
PRE-balance stats and is now silently mispriced. N rebalance mods × M content mods =
a patch matrix nobody maintains.

**Universal Rebalancer**: an in-game mod that scans the *patched* def database,
buckets items into emergent functional groups across the user's entire modlist,
detects imbalance, and proposes concrete patches the user reviews, tweaks, and
applies — per item, in an in-game UI, applied on restart.

"Universal" = content-library agnostic. No hardcoded category tables. Expansion-scale
content with zero vanilla analogue (Rimatomics, Dubs plumbing) must bucket among
itself and still get sane treatment.

## Core principles (settled with the owner — binding)

1. **Re-price, never re-design.** Only price-side/gating-side levers: costList, work,
   market value, research prerequisites. NEVER functional stats (fire rate, cooling
   power, DPS, grow time…). Function is design intent; cost and gating are economy
   positioning. (This is also what makes weapons/apparel safe to include alongside
   Combat Extended — CE owns combat stats, we never touch them.)
2. **Every finding prescribes a concrete, editable patch.** Not flag-only. Example
   output: "100 steel + 100 wood → 150 steel + 100 wood + 50 copper + 20 zinc —
   tweak and/or apply." The suggestion tier is a PROVENANCE LABEL on the numbers
   (anchor-delta / bucket baseline / global economy prior), with confidence degrading
   down that stack and the UI stating which tier produced each number.
3. **Suggest, never impose.** User cherry-picks items per bucket, edits numbers,
   applies. Restart applies the patch set.
4. **Buckets form on FUNCTION, not theme.** "Elegant hot tub" and "steel pipe" are
   both plumbing-themed and must NEVER share a bucket; they are "recreation device"
   and "small infrastructure component". Function-shaped features dominate; label
   tokens and mod-of-origin are tie-breakers only, never bridgers across
   dissimilarity. Bucket names are emergent descriptions of clusters, not inputs.
   EXCEPTION: the research engine (below) inverts this — gate placement is where
   theme legitimately matters.

## Architecture

Pipeline: **scan → bucket → suggest → review → apply**, with pluggable per-domain
"category engines" (feature extractors + suggestion models) over a shared core.

**Engine order matters:** the materials engine runs FIRST — materials are the leaf
nodes the whole economy is denominated in; category engines then reprice against
corrected material values.

### Scan
`DefDatabase` post-load = final patched truth. Key advantage of being in-game rather
than a CLI: **StatWorker evaluation** (`GetStatValueAbstract`) captures C#/StatPart
rebalances that raw-XML diffing can never see. Baseline for delta detection: re-read
raw unpatched XML from mod folders on disk (readable at runtime; skip
PatchOperations) and diff vs live defs → what each rebalance actually did, per stat,
as ratios/transformations. Limitation to document: rebalances implemented purely as
Harmony/StatPart code have no def-field footprint and evaporate from XML diffing;
StatWorker evaluation partially recovers them at the value level.

### Bucketing (emergent, classical — no ML infrastructure)
Feature space: thingClass, comp set, designationCategory, placeWorkers, statBases
KEY-shape, size, power/joy/linkable roles, research-tree position; label tokens
demoted per principle 4. Jaccard similarity + hierarchical agglomerative clustering;
the linkage-distance cutoff IS the bucket-boundary knob (refrigerators split from
coolers when the dendrogram says so). A few thousand defs on a 300-mod list =
milliseconds, ~200 lines of C#. Known wrinkle: modded comps are mod-private types,
so comp features fragment across mods (two fridge mods, two comp classes) — bounded
bridging via structural/text similarity, carefully weighted.

### Suggestion tiers (provenance labels)
1. **Anchor-delta** (highest confidence — and the core product): a bucket member was
   rebalanced (baseline diff shows it); propagate the SAME movement to unpatched
   bucket-mates. Must handle recipe TRANSFORMATIONS, not scalar ratios —
   materials-rebalance mods introduce ingredients vanilla never had (90 steel →
   45 steel + 20 copper), so propagation maps the analogue's costList through the
   transformation (new-material shares of total cost mass). This composition-transfer
   math is the interesting core of the tool.
2. **Bucket baseline**: no anchor; compare cost-per-effectiveness within the bucket
   (honest framing at n=4: a ratio table, not "regression"); propose movement toward
   bucket median.
3. **Global economy priors** (lowest confidence): anchorless AND weird buckets still
   sit inside economy-wide relationships — cost-vs-work, value-per-material,
   power-draw-vs-output, research-depth-vs-price — fitted across the whole
   population. Plus tech-tier normalization so Rimatomics-depth gear is judged
   against its tier, not against a wind turbine.

Dissonance detection is symmetric: "functionally near-identical but 3× apart in
cost" AND "near-identical cost, wildly apart in capability" both surface.
Confidence must be EXPLAINABLE prose ("grouped: shares CompTempControl + same
category; suggested ×2 cost: RebalanceMod halved vanilla cooler"), and structurally
self-flagging: a different placeWorker/size on an otherwise-twin item = qualitative
advantage the algorithm cannot price → confidence down, human judgment requested.

### Category engines (v-scope: all five discussed)
- **Materials** (runs first): balance relation is value-per-acquisition-effort —
  growDays/yield/fertility for plants, mining time/yield/commonality for minables —
  fitted against the vanilla material tier curve (wood → steel → plasteel →
  uranium). Driving example: modded tree, vanilla-equal value, 40× grow time.
  Lever: marketValue (price-side); growth stats are design-side and stay the
  human's tweak. Cascade note: RimWorld derives crafted-item value from ingredients
  via StatWorker where not explicit — material corrections auto-propagate; the
  engine must NOT double-correct derived values.
- **Buildables**: the original cooler case.
- **Creatures/animals**: arguably the strongest case — `combatPower` vs actual
  health × DPS × speed misalignment is detectable against a vanilla-fit curve, and
  miscalibrated modded combatPower silently corrupts the raid-point economy (this is
  CE autopatcher's raison d'être).
- **Craftables** (weapons/apparel): price-side only; CE owns combat stats.
- **Food/drugs/plants**: consumable economy.

### Research engine (separate engine — theming INVERTS here)
Anchor gated behind research, analogue ungated → propose gating (symmetric:
over-gated modded items get flagged too). Gate PLACEMENT hierarchy:
1. Source mod has its own research tree → place at the anchor-equivalent tier within
   it (plumbing pipe goes behind plumbing research, NOT vanilla electricity).
2. No native tree, anchor's project thematically compatible → reuse it (over-wall
   cooler behind vanilla Air Conditioning is right).
3. Neither → generate a NEW ResearchProjectDef at anchor-tier cost. Heaviest
   ownership in the whole tool (def generation, tab placement, prerequisite wiring).
Lever principle extension: re-price and RE-GATE, never re-design function.

### Review UI + apply
In-game bucket browser: per-bucket item list, per-item proposal rendered as an
editable before→after diff (recipe, work, value, research), cherry-pick, tweak
numbers inline, apply-on-restart. Persistence: decisions keyed by defName + a
per-def stat-hash — hash mismatch = upstream mod updated since the decision →
re-review flag. Double-patch standdown: if the baseline diff shows an item WAS
later patched natively (rebalance mod shipped its own compat), stand down and flag.
Apply mechanism: runtime def mutation at load from persisted decisions before caches
warm ("restart to apply" convention), NOT generated PatchOperation XML — but
**exportable decision files** are a first-class feature, see below.

### The sleeper feature
Exported decision files = community-curated analogue maps as a byproduct of normal
use. Every user's confirmed buckets + numbers is exactly the curation data a pure
algorithm fatally lacks. Shareable/importable decision sets could matter more than
the algorithm.

## Precedents (none do bucketing+suggestion; the composition is novel)
- CE experimental autopatcher — algorithmic per-category stat generation for
  unpatched weapons/animals; closest existing thing.
- Mod Medicine Patch — dynamic detection+scaling of modded medicines (single
  hardcoded bucket).
- RIMMSqol — runtime def editing with persistence (the manual version of this idea);
  proves runtime mutation + persist + restart-apply is viable.
- Cherry Picker — runtime DefDatabase surgery at scale.

## Technical notes
- Plain RimWorld mod: Harmony + vanilla. CE NOT required. RimWorld 1.6.
- No ML runtime: Jaccard + agglomerative clustering in C#.
- Effort honesty: real project; the review UI is the single biggest chunk, larger
  than entire small mods.

## Open questions (unsettled — decide before building)
1. **v1 subset.** Full five-engine scope is large. Candidate v1: buildables +
   anchor-delta tier only (the original cooler story end-to-end: scan, bucket,
   propagate, review, apply) — proves the pipeline before generalizing. Not yet
   agreed with the owner.
2. Clustering validation: how to tune feature weights / linkage cutoff, and how to
   present bucket quality to the user (merge/split controls in UI?).
3. Confidence formula: how the explainable-prose provenance maps to a
   score/ordering, if at all.
4. Save-compat of applied patches mid-colony (costList changes are refund-safe-ish;
   research regating a built item's tech — what happens to existing built copies?).
5. Performance envelope: full rescan cadence (every load? modlist-hash change only?).
6. New-ResearchProjectDef generation details (tab, coordinates, icon).
7. Materials-cascade double-correct guard: exact rule for "derived vs explicit"
   market values.
8. Distribution: Workshop mod vs GitHub-only during experimental phase.
9. packageId `eebette.UniversalRebalancer`; display name settled as
   "Universal Rebalancer".
