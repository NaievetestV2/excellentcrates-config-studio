# AGENTS.md — ExcellentCrates Config Studio

## Project goal

Build a **cross-platform desktop app (Linux / Windows / macOS)** that generates two
YAML files the [ExcellentCrates](https://github.com/nulli0n/ExcellentCrates-spigot) Spigot
plugin can read directly:

1. `crates/<id>.yml`  → goes into the plugin's `crates/` directory
2. `keys/<id>.yml`    → goes into the plugin's `keys/` directory

The app replaces the in-game `/crates editor` GUI. The user fills a guided UI, the app
emits valid, structured, commented YAML. Crate and key are **linked** (the crate's
`CostOptions` entry references the key id).

Repo reference clone: `/tmp/opencode/ExcellentCrates-spigot` (clone again if missing:
`git clone https://github.com/nulli0n/ExcellentCrates-spigot.git`).

## Core principles

1. **Correctness over features.** Generated YAML must parse and must match exactly what
   `Crate.load()` / `CrateKey.load()` read. No guessed keys. Every key written must be
   traced to a line in the plugin source (cite `file:line` when in doubt).
2. **Never write a key the plugin does not read, and never omit a key the plugin needs.**
   Unknown keys are harmless-ish, missing/typo'd keys silently fall back to defaults and
   break the user's intent — treat that as a bug.
3. **Required vs Optional separation in the UI.**
   - *Required for a working public server*: id, name, item, at least one reward,
     reward rarity reference, key (if key-gated), and the crate→key link.
   - *Optional*: holograms, particles/effects, pushback, cooldowns, limits, milestones,
     previews, animations, post-open commands, block positions, permissions.
   - Optional fields still get written with safe plugin defaults when the user leaves
     them alone, so the file round-trips cleanly through the in-game editor.
4. **Sorted by relevancy.** Top of the file = most important (Name, Item, Rewards,
   Costs). Deep/advanced options last. Mirror the order the in-game editor shows.
5. **Include comments ("config articles")** in the output explaining each section,
   valid values, and warnings — comments are ignored by Bukkit YAML so they are safe.
6. **Round-trip validation before write**: parse the emitted YAML back, diff against
   the in-memory model, refuse to write on any mismatch. Also verify the id/file-name
   rules (the plugin derives the id from the file name via `Strings.varStyle`).
7. **No network, no server access needed.** Pure offline generator. Never store secrets.
8. **Do not modify the plugin repo.** It is read-only reference material.
9. **Zero-dependency runtime preferred** (Python 3 + Tkinter stdlib) so the app runs on
   any OS; optional PyInstaller spec for a single-file binary. If a YAML library is
   used, it must be pinned and vendored or documented as a dependency.
10. **Test everything you write**: unit tests for the YAML emitter/parser, golden-file
    tests comparing generated output against fixtures derived from the plugin source.

## Config schema (source of truth)

Read these files before touching the generator:

| Concern | File |
|---|---|
| Crate file load/save | `src/main/java/su/nightexpress/excellentcrates/crate/impl/Crate.java` (`load()` ~L123, `writeSettings()` ~L273) |
| Crate creation defaults | `crate/CrateManager.java#createCrate()` (~L359) |
| Key file load/save | `key/CrateKey.java` (`load()` ~L50, `write()` ~L78) |
| Key creation defaults | `key/KeyManager.java#createKey()` (~L99) |
| Rewards | `crate/reward/RewardFactory.java`, `crate/reward/AbstractReward.java`, `crate/reward/impl/{ItemReward,CommandReward}.java` |
| Costs (key + economy) | `crate/cost/Cost.java`, `crate/cost/entry/impl/*.java`, `crate/cost/type/impl/*.java` |
| Rarities | `crate/impl/Rarity.java` (global `config.yml` → `Rewards.Rarities.<id>`) |
| Milestones | `crate/impl/Milestone.java` |
| Block positions | `util/pos/WorldPos.java` (serialize/deserialize string format) |
| Item (crate/key) | `util/ItemHelper.java` + nightcore `AdaptedItem` (`ItemProvider` for crates, `ItemData` for keys) |
| Particles | nightcore `UniParticle.read/write` (`Block.Effect.Particle`) |
| Hologram templates | `hologram/HologramTemplate.java` + `config/Config.java` (`Crate.Holograms.TemplateList`) |
| Openings/preview ids | `opening/OpeningManager.java` providers, `menu/PreviewMenu.java` (`default` id) |
| Effects | `crate/effect/EffectId.java` (ids: `none`, `helix`, ...) |
| Config dirs | `config/Config.java` → `DIR_CRATES`, `DIR_KEYS` |
| In-game editor UI order | `editor/crate/CrateOptionsMenu.java`, `editor/key/KeyOptionsMenu.java`, `dialog/**` |
| Field docs / defaults | wiki: https://nightexpressdev.com/excellentcrates/ |

Nightcore (dependency for `FileConfig`, `AdaptedItem`, `UniParticle`) may need its own
clone for serialization details: `https://github.com/nulli0n/NightCore`.

### Known schema facts (verified)

- Crate id = file name without `.yml`, must satisfy `Strings.varStyle` (lowercase
  `[a-z0-9_-]` style). Same rule for keys.
- Crates: `_dataver: 600` must be present (else the plugin rewrites + backs up).
- Crates use `ItemProvider`; keys use `ItemData`. Legacy `Item` is auto-migrated — do
  not emit `Item`.
- Crate cost options live under `CostOptions.<costId>` (legacy `Key`/`Opening.Cost`
  are migrated away — never emit them).
- Rewards live under `Rewards.List.<rewardId>`; milestones under `Milestones.List.<n>`.
- `Animation.Enabled/Id` = opening GUI (legacy name `Animation`), `Preview.Enabled/Id`
  = preview GUI. Ids default to `default`.
- `OpeningCooldown.Enabled/Value`, `OpeningLimits.Amount` (min 1),
  `Permission_Required` (bool), `ItemStackable` (bool).
- Block section: `Block.Positions` (list of `WorldPos` strings),
  `Block.Pushback.Enabled`, `Block.Hologram.{Enabled,Template,Y_Offset}`,
  `Block.Effect.{Enabled,Model,Particle}`.
- `Post-Open.Commands` — list of commands, validated with `CrateUtils.isValidCommand`.
- Keys: only `Name`, `Virtual` (bool), `ItemData`, `ItemStackable`.

## Tasks

- [x] Clone ExcellentCrates repo for reference.
- [x] Finish schema extraction: rewards, costs, milestones, rarity, WorldPos string
      format, `AdaptedItem`/`ItemProvider` map format, `UniParticle` map format.
- [x] Extract in-game editor option ordering + defaults from menus/dialogs source
      (traced into `docs/schema.md`; wiki is documented as a URL but was not
      reachable offline — source lines are authoritative).
- [x] Write a schema spec document (`docs/schema.md`) listing every key: path, type,
      required/optional, default, notes.
- [x] Implement YAML emitter + minimal parser with comment support and round-trip tests.
- [x] Implement data model: `CrateConfig`, `KeyConfig`, `Reward`, `Cost`, `Milestone`.
- [x] Implement generator: model → ordered, commented YAML for both files.
- [x] Implement validator (plugin-side rules: id format, ≥1 reward, weights > 0,
      rarity ids exist, key id referenced by crate cost, command syntax, item material).
- [x] Implement SNBT item serialization (`ecstudio/snbt.py`): vanilla `Data.Value`
      build/parse, legacy `&`/`&#RRGGBB` ↔ text components, raw-NBT preservation
      on import.
- [x] Implement file import (`ecstudio/loader.py`): plugin YAML → model, unknown
      top-level keys preserved, legacy keys rejected with a migration hint.
- [x] Build the Tkinter UI: pages sorted by relevancy (Basics → Rewards → Costs →
      World → Advanced), Required vs Optional separation, live YAML preview,
      validation panel (double-click jumps to the offending reward/cost), save to
      `crates/` + `keys/`, import dialogs.
- [x] Golden-file tests: plugin-written fixture round-trips through
      load → generate with only intended diffs (safe defaults added, unread
      `Name` dropped on ITEM rewards, `REDSTONE` → `DUST`).
- [x] Package: PyInstaller spec (`ecstudio.spec`) + run instructions for Linux,
      Windows, macOS.
- [x] README with usage + where to drop the two files.
- [x] Test suite: `python3 -m unittest discover -s tests` (82 tests: yamlkit,
      snbt, generator, validator, loader, GUI smoke).
- [x] In-game verification: sample crate+key generated by the app were loaded by a
      real Paper 1.21.10 + ExcellentCrates 6.6.1 + nightcore 2.11.0 server — logs
      show `Loaded 1 crate keys.` / `Loaded 1 crates.` with **zero problems**
      printed by `collectProblems()` on both enable and `crates reload`, and the
      plugin left the generated files byte-identical (no rewrite/backup).

## Definition of done

The app produces two files that, dropped into `plugins/ExcellentCrates/crates/` and
`.../keys/`, load with **zero problems reported** by `Crate.collectProblems()` /
`CrateKey.collectProblems()` and behave correctly in-game (crate opens with the key,
rewards roll by rarity/weight).
