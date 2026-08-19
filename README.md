# Universal Patch for More Materials

A RimWorld 1.6 patch mod. [More Materials][mm] adds copper, tin, nickel and five other
metals to vanilla recipes — and to no modded ones. This adds them to everything else.

**221 buildings across 43 content mods**, plus any mod released in future, because the
rules are categorical rather than a per-def compatibility list. Verified end to end by
replaying RimWorld's patch pipeline: 651 material requirements added, and **no vanilla def
touched**.

[mm]: https://steamcommunity.com/sharedfiles/filedetails/?id=3055040889

## The problem

More Materials patches 55 vanilla defs. All 55 are vanilla — it makes no attempt at mod
compatibility, and there is nothing wrong with that; hand-patching every content mod is not
reasonable work for one author.

The result in play: your vanilla cooler needs 90 steel, 3 components, 5 copper and 2 lithium.
Vanilla Temperature Expanded's wall-mounted cooler is identical in function and needs 70 steel
and 3 components. No copper, no lithium. It sidesteps the copper economy entirely, which is the
whole point of the mod you installed.

Multiply by 221 buildings.

## How it works

Rather than a compatibility list naming each content mod, this derives the *rule* More
Materials was following and applies it categorically. For copper that rule is simply:

> anything with `CompProperties_Power` needs copper, scaled to how much steel it uses

which matches the author's own choices on 41 of his 48 copper recipes. Eight such rules,
31 `PatchOperation`s, one file. A mod published next year is covered without anyone
touching this.

Rules alone are not quite enough, though. They cannot express a material the author gave to
one def and withheld from a near-identical one: the vanilla cooler got copper and lithium and
no cast iron, while the rules by themselves handed its wall-mounted twin copper and cast iron
and no lithium. So **nine defs that are exact functional twins of something he patched copy
his actual material set instead**, scaled by `(target steel / anchor steel) ^ 0.5`. Those run
first and are excluded from the rules, so the two never overlap.

Amounts come in eight size bands, each read off the curve `amount = k · Steel^p` fitted over
all of the author's own numbers — `p` lands near 0.5 for every material. Bands are dense where
recipes are cheap, because the relationship is sublinear and coarse bands hit small buildings
hardest: an early version gave a 10-steel power shower the same 30 units of metal as a 30-steel
item, +273% on its cost, while a 1500-steel Rimatomics turbine gained 6%.

Measured across the whole modlist: **median cost increase 33%, 90th percentile 63%, worst case
127%.**

## Is approximate good enough?

Yes, and by a wide margin. Scored against the author's own choices, where his amount is
ground truth:

| | median relative error | within 2× |
|---|---|---|
| these rules | **0.25** | **98%** |
| doing nothing | 1.00 | 0% |

The material requirement itself is imposed correctly **48 times out of 48** for copper. Being
somewhat off on quantity is a rounding difference. Requiring *none* of a material lets an item
bypass that economy completely, which is the actual bug.

Per material, ranked by how many modded assignments each rule reaches. The shipped patch
applies 495 of these; the gap is defs whose recipes use no steel, which the size bands
require.

| material | assignments | cumulative | vanilla false positives |
|---|---|---|---|
| `ME_Copper` | 196 | 29% | 4 |
| `ME_Nickel` | 190 | 57% | 3 |
| `ME_CastIronIngot` | 154 | 80% | 1 |
| `ME_Tin` | 47 | 87% | 2 |
| `ME_Lead` | 32 | 92% | 0 |
| `ME_Zinc` | 27 | 96% | 0 |
| `ME_BrassIngot` | 24 | 99% | 0 |
| `ME_BronzeIngot` | 4 | 100% | 0 |
| **total** | **674 reachable** | | **0 applied to vanilla** |

## What it will not do

**It never modifies a vanilla def.** Mopolita made every Core decision deliberately; this
covers only the modded content he could not. Left to themselves the rules would hand the
vanilla heater cast iron he chose to withhold, so every Core def a rule would select is named
and excluded.

It also skips any def already carrying electrum, lithium or white gold — the three materials
he used that this patch never emits, and therefore proof he handled that def himself. That is
how the ship parts keep their electrum instead of gaining copper.

**How twins are recognised.** Function lives in comp *property values*, not `statBases`. A
heater and a cooler are separated by `CompProperties_TempControl`'s `energyPerSecond`, +21
against −21, while their `statBases` differ only in incidental durability numbers. Matching on
`statBases` pairs VTE's wall heater with the *cooler*; matching on comp properties pairs it
with the heater. Properties only one side declares are ignored, since the vanilla heater sets
`shortCircuitInRain` and VTE's does not, which says nothing about what either device is.

`thingClass` tokens act as a veto rather than a requirement — reject only when both sides
carry meaningful tokens and share none, which is what stops a prosthetics bench pairing with a
nutrient paste dispenser. It is a code identifier, not a display label, and the emitted xpaths
already match comp classes the same way.

**Coverage is deliberately left on the table.** A `statBases` fallback for defs the comps
cannot place was tried and reverted: it recovers `VTE_ACUnit` but pairs `VTE_StandingCooler`
with the *heater*, whose durability stats happen to match while its `energyPerSecond` is the
opposite sign. Trading one wrong answer for another is not progress, and anything without an
anchor is still covered by the categorical rules.

## Exotic content mods

The mods furthest from vanilla are handled by the same rules, and the sublinear amounts keep
them sane:

| def | original cost | added | increase |
|---|---|---|---|
| Zeus Turbine (Rimatomics) | 1522 units | 52 cast iron, 24 copper, 27 nickel | +7% |
| sewage treatment (Dubs) | 408 | 52 cast iron, 24 copper, 27 nickel | +25% |
| genomorpher (Genetics) | 206 | 30 cast iron, 15 copper, 14 nickel | +29% |
| prosthetic workbench (EPOE) | 84 | 21 cast iron, 10 copper, 7 lead, 9 nickel | +56% |
| power shower (Dubs) | 11 | 7 cast iron, 4 copper, 3 nickel | +127% |

Rimatomics gets 26 defs, Dubs 16, Genetics 9, EPOE 3. **147 active mods are untouched
entirely** — anything with no powered, steel-costed buildings simply never matches, which is
the correct outcome rather than a gap.

## Why only More Materials?

Twenty active mods on the test list add new materials. Only **three** retrofit them into
recipes that already existed, and only one does so at scale:

| mod | materials added | retrofits existing recipes |
|---|---|---|
| More Materials | 13 | **55 defs — all vanilla, no mod coverage** |
| Combat Extended | 2 | 109 defs, but ships its own compat patches |
| VFE Insectoid 2 | 1 | 1 def |

The other seventeen — including [More Useful Materials][mum], which adds fifteen — are
self-consistent: their materials feed only their own content, so nothing diverged and there
is nothing to propagate. **Adding materials does not create a gap. Redistributing them into
existing recipes does.**

That is why this patch targets one mod, and why the generator in `tools/` takes a packageId
rather than hardcoding one.

[mum]: https://steamcommunity.com/sharedfiles/filedetails/?id=3734307960

## Requirements

- RimWorld 1.6
- [More Materials][mm] — required, and this must **load after** it

## Repo layout

```
About/      mod metadata
Patches/    the shipped patch
tools/      the generator that produced it (Python, offline)
docs/       derivation.md — full history, rejected designs, measurement bugs
```

## Regenerating

The generator is not specific to More Materials; it takes any mod's packageId, replays that
mod's `PatchOperation`s against your installed modlist, derives per-material rules from what it
changed, and emits XML. The *output* is specific — every operation here hardcodes an `ME_`
material name.

```bash
python3 tools/pareto.py mopolita.bame.morematerials --emit 99
```

Requires `lxml` and a local RimWorld install. It reads the game and Workshop folders directly;
no game launch needed.

## Credit

All balance decisions here are [Mopolita's][mm], inferred from their own patches and extended
to content they could not have covered. Bugs in the extension are mine.
