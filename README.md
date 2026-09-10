# Universal Patch for More Materials

[![Latest Release](https://img.shields.io/github/v/release/eebette/CombatExtended-SimpleSidearms-Compatibility-Loadouts?label=Latest%20Release)](https://github.com/eebette/CombatExtended-SimpleSidearms-Compatibility-Loadouts/releases)
<!-- Steam Workshop badge goes here at publish -->

![Universal Patch for More Materials](Media/Badge_UPMM.png)

A RimWorld mod that dynamically extends [More Materials][mm] to cover modded recipes. Copper, tin, nickel and five other
metals are dynamically added to non-vanilla recipes using \*math\*.

This is a set of rules that is applied based on item/furniture/building attributes and precedent set my the author of
More Materials. This is not a static set of manual overrides with finite mod coverage (though there are some
mod-specific overrides. PRs welcome.).

[mm]: https://steamcommunity.com/sharedfiles/filedetails/?id=3055040889

## How it works

Rather than a compatibility list naming each content mod, this derives the *rule* More Materials was following and
applies it categorically.

For example, for copper that rule is simply:

> anything with `CompProperties_Power` needs copper, scaled to how much steel it uses

which matches the More Materials author's choices on 41 of 48 copper recipes.

## Load order

> RimWorld → this mod.

## My other mods

### The CE + Simple Sidearms suite

Two optional modules sit on top of this patch and require it. This patch only fixes core incompatibilities; enhancements
in these instead.

<table>
<tr><th width="300">Module</th><th width="540">What it does</th></tr>
<tr><td width="300"><a href="https://github.com/eebette/CombatExtended-SimpleSidearms-Compatibility-Patch"><img src="Media/Badge_Patch.png" width="300" alt="CE + Simple Sidearms Compatibility Patch"></a></td><td width="540">Core compatibility patch for Combat Extended and Simple Sidearms.</td></tr>
<tr><td width="300"><a href="https://github.com/eebette/CombatExtended-SimpleSidearms-Compatibility-Loadouts"><img src="Media/Badge_Loadouts.png" width="300" alt="CE + Simple Sidearms Loadouts Module"></a></td><td width="540">Syncs loadouts between Combat Extended and Simple Sidearms.</td></tr>
<tr><td width="300"><a href="https://github.com/eebette/CombatExtended-SimpleSidearms-Compatibility-Tactics"><img src="Media/Badge_Tactics.png" width="300" alt="Compatibility Module - Tactics"></a></td><td width="540">Sensible tweaks to nonsense pawn behavior when CE + SS run together.</td></tr>
</table>

### Standalone

<table>
<tr><th width="300">Mod</th><th width="540">What it does</th></tr>
<tr><td width="300"><a href="https://github.com/eebette/Better-Attack-Orders-for-Simple-Sidearms"><img src="Media/Badge_BAO.png" width="300" alt="Better Attack Orders for Simple Sidearms"></a></td><td width="540">Adds sidearm attack orders to the right-click target menu.</td></tr>
<tr><td width="300"><a href="https://github.com/eebette/Pawns-Optimize-Weapon-Quality"><img src="Media/Badge_POWQ.png" width="300" alt="Pawns Optimize Weapon Quality"></a></td><td width="540">Pawns will upgrade their held guns when a higher-quality copy is available.</td></tr>
</table>

## FAQ

**CE compatible?**

Yes.

**Can I add or remove it mid-save?**

Yep.

**Does it change balance?**

Makes the game harder by making recipes more expensive.

**AI?**

This mod was engineered with the help of an AI Coding Assistant (Claude Code, Fable 5, Max effort). The amount of
researching and deep-diving the compatibility interfaces of mods that it patches would have been insurmountable without
it.

Development followed a standard process driven and scrutinized by me (the real human person writing this):
explore, design, build, test, fix, review, scrutinize, test again over many rounds.

I have manually reviewed and verified all code in this mod.

I ask that if you have unconstructive feedback regarding the usage of AI while developing this mod, that it remains
outside of this community space. Thank you.

## Regenerating

Needed when More Materials updates, or to point the tooling at a different materials mod. Not needed to "get coverage
for your mods" - see the repo layout above.

The generator is not specific to More Materials; it takes any mod's packageId, replays that mod's `PatchOperation`s
against your installed modlist, derives per-material rules from what it changed, and emits both files. The *output* is
specific - every operation hardcodes an `ME_`
material name.

```bash
python3 tools/pareto.py mopolita.bame.morematerials --emit 99
```

Requires `lxml` and a local RimWorld install. It reads the game and Workshop folders directly; no game launch needed.

## Credit

All balance decisions here are [Mopolita's][mm], inferred from their own patches and extended to content they could not
have covered. Bugs in the extension are mine.

## License

[MIT](LICENSE) - code, build files, and docs.

The badge artwork is not: `About/Preview.png` and the `Media/Badge_*.png` set remix the rifle glyph from Combat
Extended's own compatibility badge, so they stay under CE's CC BY-NC-SA 4.0 (attribution, non-commercial, share-alike).
Details in [NOTICE](NOTICE).
