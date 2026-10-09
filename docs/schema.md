# ExcellentCrates schema (source of truth for this tool)

Every key below was traced to the plugin source. `file:line` refers to the reference
clone `ExcellentCrates-spigot` (`src/main/java/su/nightexpress/excellentcrates/...`
unless another path is given). Nightcore paths are relative to
`nightcore-spigot/main/src/main/java/su/nightexpress/nightcore/...`.

Legend:

- **R** = required for a working public server (the app must demand it).
- **O** = optional (written with the plugin's own default when untouched).
- "default" = value the plugin *reads when the key is absent* (`Crate.load`),
  i.e. what we get if we omit the key. We still write it explicitly so the file
  round-trips through the in-game editor unchanged.

---

## 1. Files and ids

| Fact | Source |
|---|---|
| Crate file = `plugins/ExcellentCrates/crates/<id>.yml` | `config/Config.java` → `DIR_CRATES`, `CrateManager.createCrate():359` |
| Key file = `plugins/ExcellentCrates/keys/<id>.yml` | `KeyManager.createKey():99` |
| id = file name without `.yml` | `Crate.java:114`, `CrateKey.java:41` |
| id must satisfy `Strings.varStyle` (lowercase `[a-z0-9_-]`, whitespace→`_`, other chars dropped, empty → rejected) | nightcore `util/Strings.java`, id from `GenericCreationDialog` (`dialog/generic/GenericCreationDialog.java`, `Strings.varStyle(name)`) |
| Key is **lowercased** on load (`getProviderById`, `getKeyById` use `toLowerCase`) | `OpeningManager.java:135`, `KeyManager` |
| Reward ids follow `Strings.varStyle` + count suffix (`CrateUtils.generateRewardID():83`); cost ids are free-form map keys | `CrateUtils.java:83` |
| crate id is embedded in generated file name, so a bad id ⇒ wrong file name ⇒ plugin sees a different id | same as above |

**Never write legacy keys.** The plugin migrates and *deletes* them on load, then
rewrites the file (`saveChanges()` only writes when the file changed). Legacy keys
we must never emit: `Item`, `Item.Tag`, `Item.ItemTag`, `Type/Handler/ItemId/Amount`
(item), `Preview_Config`, `Animation_Config`, `Opening.Cooldown`, `Opening.Cost`,
`Key`, `Key.Ids`, `Key.Required`, reward `Preview`, reward `Win_Limits`,
reward `Type` absent + `Commands` present.
Sources: `Crate.java:123-177`, `CrateKey.java:50-66`, `RewardFactory.java:16-57`,
`ItemHelper.java` (`read`, legacy `Type` branch).

---

## 2. Crate file — top level (`crates/<id>.yml`)

Read in `Crate.load()` (`Crate.java:123`), written by `Crate.writeSettings()`
(`Crate.java:273`), `writeRewards()` (`Crate.java:305`), `writeMilestones()`
(`Crate.java:314`).

| Path | Type | R/O | Default when absent | Notes |
|---|---|---|---|---|
| `_dataver` | int | R | *(absent ⇒ plugin sets `600`, backs up file to `backups/*.backup535`)* | Always write `600`. `Crate.java:124` |
| `Name` | string | R | crate id (`getString("Name", id)`) | `&` color codes, **not** `§` (`FileConfig.set` rewrites `§`→`&`). Read `Crate.java:165`, write `Crate.java:274` |
| `Description` | list[string] | O | `[]` | Lore-style lines under the hologram name. Read `Crate.java:166`, write `Crate.java:275` |
| `ItemProvider` | item (see §4) | R | default crate item (`CrateUtils.getDefaultItem`) | Read `Crate.java:168`, write `Crate.java:276`. **Not** `Item` |
| `ItemStackable` | bool | O | `true` | stacking crates. Read `Crate.java:169`, write `Crate.java:277` |
| `Permission_Required` | bool | O | `false` | when `true` the player needs `excellentcrates.crate.<id>` to open (`Crate.hasPermission():443`, `Crate.getPermission():454` = `Perms.PREFIX_CRATE` + id). Read `Crate.java:180`, written `Crate.java:278` |
| `Preview.Enabled` | bool | O | `false` | preview menu. Read `Crate.java:171`, write `Crate.java:280` |
| `Preview.Id` | string | O | `default` | preview menu id; `default` exists (`menu/PreviewMenu.java`). Read `Crate.java:172`, write `Crate.java:281`. Validated by `Crate.isPreviewValid():426` |
| `Animation.Enabled` | bool | O | `false` | **opening GUI** (legacy key name `Animation`). Read `Crate.java:173`, write `Crate.java:282` |
| `Animation.Id` | string | O | `default` | opening provider id. **`default` does NOT exist** on a fresh server → `INSPECTIONS_CRATE_OPENING` (`Crate.java:341`, `isOpeningValid():430`). Built-ins: `csgo, enclosing, mystery, roulette, storm, simple_roll, selective_1, selective_3` (`OpeningManager.loadDefaults():60-73`). Read `Crate.java:174`, write `Crate.java:283`. Use `simple_roll` by default; or set `Enabled: false` ⇒ dummy opening (instant, no problem, `Crate.java:186` fallback `dummyProvider`) |
| `OpeningCooldown.Enabled` | bool | O | `false` | Read `Crate.java:176`, write `Crate.java:285` |
| `OpeningCooldown.Value` | int (seconds) | O | `0` | `0` = off, `-1` = once per player, `>0` seconds (editor semantics). Read `Crate.java:177`, write `Crate.java:286` |
| `OpeningLimits.Amount` | int ≥ 1 | O | `0` → clamped `max(1, v)` | max openings (per player). Read `Crate.java:178` (`setOpeningLimitAmount` clamps), write `Crate.java:287` |
| `CostOptions.<costId>` | cost (see §5) | O | *(key absent ⇒ free crate)* | Read `Crate.java:217`, write `Crate.java:289-290`. Cost id is the map key, user-defined (`key_main`, `eco_main`, …; legacy migration uses `key_<keyId>` / `eco_<currencyId>`, `Crate.java:193`). Write nothing when there are no costs |
| `Block.Positions` | list[WorldPos string] | O | `[]` | format `x,y,z,world` (`util/pos/WorldPos.java`). Read `Crate.java:222`, write `Crate.java:292`. Empty ⇒ crate is not placed in the world (hologram won't show) |
| `Block.Pushback.Enabled` | bool | O | `false` | knock players back on open. Read `Crate.java:230`, write `Crate.java:293` |
| `Block.Hologram.Enabled` | bool | O | `false` | Read `Crate.java:231`, write `Crate.java:294` |
| `Block.Hologram.Template` | string | O | `default` | hologram template id; `default` exists (`config/Config.Crate.Holograms.TemplateList`). Read `Crate.java:232`, write `Crate.java:295`. Validated `Crate.isHologramTemplateValid():434` |
| `Block.Hologram.Y_Offset` | double | O | `0.0` | Read `Crate.java:233`, write `Crate.java:296` |
| `Block.Effect.Enabled` | bool | O | `!model.equals(none)` | Read `Crate.java:237`, write `Crate.java:297` |
| `Block.Effect.Model` | string | O | `none` | effect id (`crate/effect/EffectId.java`): `none, helix, spiral, sphere, heart, pulsar, beacon, tornado, vortex, simple` (`CratesRegistries.registerDefaultEffects():24-33`). Read `Crate.java:235`, write `Crate.java:298`. Validation is registry lookup |
| `Block.Effect.Particle` | particle (see §6) | O | absent ⇒ plugin falls back to `CLOUD` | nightcore `UniParticle.read` `util/wrapper/UniParticle.java:71`, written `Crate.java:299-301`. `Crate.setEffectParticle` sanitizes unsupported names to `CLOUD` |
| `Post-Open.Commands` | list[string] | O | `[]` | run after every open. Each command **without leading `/`**, validated by `CrateUtils.isValidCommand():98` (first token must be a registered command name on the target server; namespaced `minecraft:tp` allowed). Read `Crate.java:239`, write `Crate.java:302` |
| `Rewards.List.<rewardId>` | reward (see §3) | **R ≥ 1** | *(absent ⇒ crate has no rewards, opening does nothing)* | Read `Crate.java:241`, write `Crate.java:305-312` |
| `Milestones.Repeatable` | bool | O | `false` | only read when global `Milestones.Enabled` in `config.yml` (`Crate.java:248`, `Config.isMilestonesEnabled`). Write `Crate.java:318` |
| `Milestones.List.<n>` | `{Reward_Id, Openings}` | O | *(absent ⇒ no milestones)* | index keys are `0,1,2…` (`Crate.writeMilestones():314-322`). `Milestone.read():26`, `Milestone.write():33` |

Problem checks the plugin runs on load (`Crate.collectProblems():336`):

1. crate item invalid (`Item.isValid()`) — `Crate.java:339`
2. `Preview.Enabled` and preview id not found — `Crate.java:340`
3. `Animation.Enabled` and opening id not found — `Crate.java:341`
4. `Block.Hologram.Enabled` and template id not found — `Crate.java:342`
5. every `Post-Open.Commands` entry must pass `CrateUtils.isValidCommand` — `Crate.java:344`
6. every cost reports entry problems — `Crate.java:349`
7. every reward reports reward problems — `Crate.java:356`

---

## 3. Reward (`Rewards.List.<rewardId>`)

Read: `RewardFactory.read()` (`crate/reward/RewardFactory.java:16`), shared part
`AbstractReward.load()` (`AbstractReward.java:71-76`), written
`AbstractReward.write():82-92` + `ItemReward.writeAdditional():67` /
`CommandReward.writeAdditional():45`.

| Path | Type | R/O | Default | Notes |
|---|---|---|---|---|
| `Type` | `ITEM` \| `COMMAND` | R | `ITEM` (when absent and no `Commands`) | Read `RewardFactory.java:71`; written `AbstractReward.java:83`. Uppercase |
| `Rarity` | rarity id | **R** | *(absent ⇒ `"null"` ⇒ plugin **logs an error**, falls back to most-common rarity)* | `RewardFactory.java:64-70`. Ids must exist in global `config.yml` → `Rewards.Rarities.<id>` (defaults `common`, `rare`, `mythic`). Emit always; warn when not one of the 3 defaults |
| `Weight` | double ≥ 0 | **R** | `-1.0` if absent (`AbstractReward.java:72`, constructor default `10.0`) | relative roll weight within its rarity (`Rarity.getRollChance():44`). Plugin writes `25.0` style floats |
| `Broadcast` | bool | O | `false` | broadcast to server when won. Read `AbstractReward.java:73`, written `AbstractReward.java:87` |
| `PreviewData` | item | R | *(absent ⇒ question-mark head ⇒ `INSPECTIONS_REWARD_PREVIEW` for COMMAND, and for ITEM only when `Custom_Preview`)* | `ItemHelper.readOrPlaceholder():24`, read `AbstractReward.java:71`, written `AbstractReward.java:84` |
| `Ignored_For_Permissions` | list[string] | O | `[]` | permission names (read with `getStringSet`). Read `AbstractReward.java:75`, written `AbstractReward.java:89` |
| `Required_Permissions` | list[string] | O | `[]` | player must have **all** of these to win. Read `AbstractReward.java:76`, written `AbstractReward.java:90` |
| `Limits` | map | O | `{Enabled: false, CooldownType: DAILY, GlobalAmount: -1, PlayerAmount: -1, GlobalCooldown: 0, PlayerCooldown: 0}` | `LimitValues.read():39-50`, write `:53-62`. `-1` = unlimited, `0` = no cooldown, `CooldownType` ∈ `DAILY` (reset at midnight) / `CUSTOM` (seconds). Written always (`AbstractReward.java:88`) |
| `ItemsData.<n>` | map of item (ITEM only) | **R ≥ 1** | *(empty ⇒ `INSPECTIONS_REWARD_NO_ITEMS`)* | keys `0,1,2…` (`ItemReward.java:70-75`). Multiple items = random pick (`ItemReward.loadAdditional():39-61`). Invalid entry ⇒ `plugin.error` log (`ItemReward.java:58`) |
| `Custom_Preview` | bool (ITEM only) | O | `false` | `true` ⇒ `PreviewData` is shown instead of item[0] and must be valid (`ItemReward.java:85`). Read `ItemReward.java:52`, written `ItemReward.java:68` |
| `Placeholder_Apply` | bool (ITEM only) | O | `false` | allow placeholders in item name/lore. Read `ItemReward.java:53`, written `ItemReward.java:69` |
| `Name` | string (COMMAND only) | O | capitalize-underscored id | shown in menus. Read `CommandReward.java:39`, written `:46` |
| `Description` | list[string] (COMMAND only) | O | `[]` | Read `CommandReward.java:40`, written `:47` |
| `Commands` | list[string] (COMMAND only) | **R ≥ 1** | *(empty ⇒ `INSPECTIONS_REWARD_NO_COMMANDS`)* | each without leading `/`; each validated with `CrateUtils.isValidCommand` (`CommandReward.java:56`). Read `CommandReward.java:41`, written `:48` |

Problems (`ItemReward.collectAdditionalProblems():79`, `CommandReward.collectAdditionalProblems():52`):

- ITEM: no items / any item invalid / (`Custom_Preview` and preview invalid).
- COMMAND: preview invalid (needs a real `PreviewData`), no commands, invalid command name.

**Note:** the golden plugin-written file contains `Name:` on ITEM rewards — current
source never reads it (`AbstractReward.load` has no `Name`; `ItemReward.getName():153`
derives from the preview item). Do not emit it (harmless but dead).

---

## 4. Item (`ItemProvider`, `ItemData`, `Icon`, `PreviewData`, `ItemsData.<n>`)

Item shape is `{Provider, Data}`:

| Path | Type | Notes |
|---|---|---|
| `Provider` | string | adapter name: `vanilla` (built-in, weight 0) or a custom adapter (`nexo`, …) |
| `Data.Value` | string (SNBT) | **vanilla only**. Whole ItemStack SNBT: `{count:1,id:"minecraft:tripwire_hook",components:{…}}`. Nightcore `ItemTag.read():24` (`util/ItemTag.java`), no `DataVersion` needed (missing ⇒ `-1` ⇒ `DataFixerUtil.updateItemStack` skips fixing, `utils/.../DataFixerUtil.java:57-64`) |
| `Data.DataVersion` | int | optional; plugin writes the *writing server's* version (golden files: `4556`). Omit for generated files |
| `Data.ID` | string | **custom providers only** — item id in that plugin (`ItemIdData.read`, `integration/item/data/ItemIdData.java:17`) |
| `Data.Amount` | int | **custom providers only** (default `0` if absent — always write `≥ 1`) |

Legacy shapes (never emit, auto-migrated by `ItemHelper.read():30`): `Type: vanilla`
+ `ItemTag`/`Tag`; `Type: custom` + `Handler/ItemId/Amount`.

SNBT components we generate (verified against golden
`armor_crate.yml` `ItemProvider` block):

- display name: `"minecraft:custom_name":{text:"…",italic:0b,color:"#RRGGBB",bold:1b,…}`
  — text components are **NBT compounds** (NbtOps, not JSON strings), booleans
  `0b`/`1b`, golden always writes `italic:0b`.
- lore: `"minecraft:lore":[{text:"…",italic:0b}, …]`
- head skin: `"minecraft:profile":{properties:[{name:"textures",value:"<base64>"}]}`

Default items plugin itself creates: crate = `CrateUtils.getDefaultItem`,
key = `TRIAL_KEY` (`ItemHelper` fallback for missing key `ItemData`,
`CrateKey.java:62`), in-game new key = `TRIPWIRE_HOOK` (`KeyManager.java:107`), cost icon default = `TRIAL_KEY` (legacy migration `Crate.java:196`).

---

## 5. Cost option (`CostOptions.<costId>`)

Read `Cost.read()` (`crate/cost/Cost.java:42`), written `Cost.write():62`.

| Path | Type | R/O | Default | Notes |
|---|---|---|---|---|
| `CostOptions.<id>.Enabled` | bool | O | `true` | `Cost.java:43` |
| `CostOptions.<id>.Name` | string | O | capitalize-underscored id | `Cost.java:44` |
| `CostOptions.<id>.Icon` | item | O | question-mark head (`ItemHelper.readOrPlaceholder():24`) | Read `Cost.java:45`, written `Cost.java:65` |
| `CostOptions.<id>.Entries.<n>` | entry | **R ≥ 1** | *(none ⇒ cost does nothing)* | index keys `0,1,…` (`Cost.write():66-68`, read `Cost.java:47-54`) |

Entry = `{Type, …}` (`AbstractCostEntry.read():20`):

| `Type` | Extra keys | Notes |
|---|---|---|
| `key` | `Key` (key id), `Amount` (int ≥ 1) | `KeyCostEntry.writeAdditional():44-47`. Key id must exist in `keys/` or the entry is invalid (`entry.isValid`) |
| `currency` | `Currency` (currency id), `Amount` (double) | `EcoCostEntry.writeAdditional():41` — key is **`Currency`**, not `CurrencyId`. Currency ids come from the economy plugin (e.g. `vault`); unknown id ⇒ invalid entry |

Linking: crate → key is `CostOptions.<any>.Entries.<n>.Key = <key file id>`.

---

## 6. Particle (`Block.Effect.Particle`)

nightcore `UniParticle.read():71` / `write():117`
(`util/wrapper/UniParticle.java`). Only written when a particle is chosen.

| Path | Type | Notes |
|---|---|---|
| `Name` | string | Bukkit `Particle` enum name, e.g. `CLOUD`, `FLAME`, `DUST`, `HEART`. Invalid/absent ⇒ plugin falls back to `CLOUD`. Unsupported by the effect system: `VIBRATION`, `DUST_COLOR_TRANSITION`, `TRAIL` (`CrateUtils.isSupportedParticle`) |
| `Material` | string | only for block-data particles (`BLOCK`, `FALLING_DUST`, `BLOCK_MARKER`, `BLOCK_CRUMBLE`, `DUST_PILLAR`) |
| `Color` | `r,g,b` | `DUST` (DustOptions), plain `Color` particles, and `Spell`-type (1.21.10+) |
| `Size` | float | `DUST` (default `1.0`) |
| `Power` | float | Spell-type particles (1.21.10+) |
| `Item` | item | `ITEM` particle (serialized via Bukkit `config.setItem`, SNBT item stack) |
| `floatValue` / `intValue` | float / int | particles with `Float`/`Integer` data |

Server-correct enum names for 1.21.8/1.21.10 (verified against
`spigot-api-1.21.10` `org.bukkit.Particle`): `POOF, FLAME, CLOUD, LAVA, SMOKE,
LARGE_SMOKE, EFFECT, HEART, HAPPY_VILLAGER, ANGRY_VILLAGER, ENCHANT, ENCHANTED_HIT,
CRIT, PORTAL, DUST, TOTEM_OF_UNDYING, SPELL, NOTE, …` — note the 1.21.3 renames
(`REDSTONE`→`DUST`, `VILLAGER_HAPPY`→`HAPPY_VILLAGER`, `SPELL`→`EFFECT`).
Old golden files still contain `REDSTONE`; the enum no longer has it, so a stale
name silently degrades to `CLOUD`.

---

## 7. Key file (`keys/<id>.yml`)

Read `CrateKey.load()` (`key/CrateKey.java:50`), written `CrateKey.write():78`,
defaults from `KeyManager.createKey():99`.

| Path | Type | R/O | Default | Notes |
|---|---|---|---|---|
| `Name` | string | R | key id | Read `CrateKey.java:51`, write `:79` |
| `Virtual` | bool | O | `false` | `true` = no physical item (pure counter). Read `CrateKey.java:52`, write `:80` |
| `ItemData` | item | R | `TRIAL_KEY` when absent | Read `CrateKey.java:62`, write `:81`. **Not** `Item` |
| `ItemStackable` | bool | O | `true` | Read `CrateKey.java:63`, write `:82` |

Key problems (`CrateKey.collectProblems():90`): item invalid only.

---

## 8. Rarities (global `plugins/ExcellentCrates/config.yml`)

Not one of our two output files — **warning only**. Plugin reads
`Rewards.Rarities.<id>.{Name, Weight}` (`crate/impl/Rarity.java:28`,
`CrateManager` rarity load). Built-in defaults: `common` (70), `rare` (25),
`mythic` (5). If a crate uses a non-default rarity the user must add it to
`config.yml`; the validator prints a paste-able snippet:

```yaml
Rewards:
  Rarities:
    <id>:
      Name: <Display Name>
      Weight: 10.0
```

---

## 9. Editor relevancy order (used for section ordering)

Crate options menu (`editor/crate/CrateOptionsMenu.java`): Name (10),
Description (11), Item (12), Preview (13), Opening Animation (14), Linked Blocks
(15), Pushback (16), Cost Options (28), Permission (29), Open Limits (30),
Effect (31), Hologram (32), Rewards (33), Milestones (34), Post-Open Commands (40).

Reward menu (`editor/reward/RewardOptionsMenu.java`): content (Items/Commands),
Preview, Rarity & Weight, Display Name, Description, Win Broadcast, Permissions,
Limits.

Cost menu (`editor/cost/CostOptionsMenu.java`): Name, Icon, Vacant Slot (entries).

---

## 10. Golden reference

`/tmp/opencode/armor_crate.yml` — plugin-written crate (issue #305 attachment).
Confirms: `_dataver: 600` at the end (order irrelevant), item `Value` SNBT shape,
`Limits` full map, `ItemsData` keys quoted `'0'`, cost layout
(`CostOptions.key_armor.Entries.'0'.{Type: key, Key, Amount}`), `Effect.Model: HELIX`,
`Effect.Particle.Name: REDSTONE` (stale enum name → would degrade to CLOUD today),
reward `Name:` on ITEM rewards (unread by current source).
