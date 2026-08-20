# Test plan

Everything here is offline except section 3. `tools/` reimplements RimWorld's
PatchOperation pipeline, so most claims are checkable without launching.

## 1. Artifact integrity

- [ ] both `Patches/*.xml` files parse as XML
- [ ] Every `<xpath>` compiles
- [ ] No `--` anywhere inside the header comment
- [ ] No raw `<` inside any xpath (upper bounds use `not(Steel > n)`)

## 2. Replay, both branches

With More Materials present:

- [ ] ~221 defs change, ~650 material requirements added
- [ ] **zero vanilla defs modified** — the regression that matters most
- [ ] `VTE_WallMountedCooler` gains copper
- [ ] `Cooler` unchanged by us (already carries the author's copper and lithium)
- [ ] `Ship_Reactor` unchanged by us (carries his electrum)

With More Materials absent:

- [ ] zero defs change

Idempotence:

- [ ] applying the patch twice yields the same result as once

## 3. In-game

- [ ] Full modlist loads with no red errors
- [ ] Architect menu: VTE wall-mounted cooler lists copper in its cost
- [ ] A build order for it can be completed with copper in stock
- [ ] More Materials disabled: clean load, no missing-def errors

## 4. Regression sensitivity

All of these have shipped broken and are cheap to re-check:

- [ ] the per-rule material guard is not a single `ME_` prefix guard — a prefix
      guard is self-defeating and collapses ~650 assignments to ~225
- [ ] the vanilla exclusion list is non-empty and current
- [ ] the header comment appears once, not duplicated by an in-place edit
- [ ] no `<!—` or `—>` in the body: the header's em-dash sanitiser must never
      run over the generated operations
- [ ] `VTE_WallHeater` takes the heater's metals, not the cooler's — the
      comp-property fingerprint regressing to statBases shows up here first
