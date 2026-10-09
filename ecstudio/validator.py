"""Plugin-side validation: catch everything ``Crate.collectProblems()`` /
``CrateKey.collectProblems()`` would report — plus the silent failures
(unknown rarity, unknown particle, unknown animation id) that do not crash but
break the user's intent.

Levels:

* ``error``   – the plugin will log a problem, drop data, or the file cannot
  work (missing rewards, bad ids, bad commands).  The app refuses to save.
* ``warning`` – loads fine but probably not what the user meant (unknown ids
  that silently fall back, crate/key not linked, ...).
* ``info``    – useful notes (e.g. "verify this command exists on your server").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .model import (
    CrateConfig,
    KeyConfig,
    PluginDefaults,
    is_var_style,
    var_style,
)

__all__ = ["Problem", "validate_crate", "validate_key", "has_errors", "rarity_snippet"]

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _load_names(filename: str) -> frozenset[str]:
    path = _DATA_DIR / filename
    if not path.exists():  # pragma: no cover - packaging guard
        return frozenset()
    return frozenset(line.strip() for line in path.read_text().splitlines() if line.strip())


MATERIALS = _load_names("materials.txt")  # org.bukkit.Material (spigot 1.21.10)
PARTICLES = _load_names("particles.txt")  # org.bukkit.Particle (spigot 1.21.10)

_POSITION_RE = re.compile(r"^-?\d+,-?\d+,-?\d+,[^\s,]+$")
_COMMAND_FIRST_WORD = re.compile(r"^[A-Za-z0-9_:]+$")
_LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}


@dataclass
class Problem:
    level: str  # error | warning | info
    path: str  # config path, e.g. Rewards.List.bit_helmet.Weight
    message: str
    hint: str = ""

    def __str__(self) -> str:
        base = f"[{self.level.upper()}] {self.path}: {self.message}"
        return f"{base}\n    {self.hint}" if self.hint else base


def has_errors(problems: list[Problem]) -> bool:
    return any(p.level == "error" for p in problems)


def rarity_snippet(rarity_id: str) -> str:
    return (
        "Rewards:\n"
        "  Rarities:\n"
        f"    {rarity_id}:\n"
        f"      Name: {rarity_id.replace('_', ' ').title()}\n"
        "      Weight: 10.0"
    )


# --------------------------------------------------------------------- helpers


def _check_id(problems: list[Problem], path: str, value: str, what: str) -> None:
    if not value:
        problems.append(Problem("error", path, f"{what} is empty."))
    elif not is_var_style(value):
        fixed = var_style(value)
        hint = f"Did you mean '{fixed}'?" if fixed else "Use lowercase letters, digits, '_' and '-'."
        problems.append(
            Problem(
                "error",
                path,
                f"{what} '{value}' is invalid — the plugin derives the id from the file name (Strings.varStyle).",
                hint,
            )
        )


def _check_text(problems: list[Problem], path: str, value: str, what: str, required: bool) -> None:
    if "\n" in value or "\r" in value or "\t" in value:
        problems.append(Problem("error", path, f"{what} must be a single line."))
    if required and not value.strip():
        problems.append(Problem("error", path, f"{what} is required."))


def _check_command(problems: list[Problem], path: str, command: str) -> None:
    if not command.strip():
        problems.append(Problem("error", path, "Empty command."))
        return
    if command.lstrip().startswith("/"):
        problems.append(
            Problem("error", path, f"Command '{command}' must not start with '/'.",
                    "The plugin runs it without a slash; '/give' would never match a registered command.")
        )
        return
    first = command.split()[0]
    if not _COMMAND_FIRST_WORD.match(first):
        problems.append(Problem("error", path, f"Command '{command}' has an invalid command name."))
        return
    problems.append(
        Problem(
            "info",
            path,
            f"Command '{first}' must exist on the target server "
            "(only syntax can be checked offline).",
        )
    )


def _check_item(problems: list[Problem], path: str, item, what: str) -> None:
    if item.is_vanilla():
        if not item.material:
            problems.append(Problem("error", path, f"{what}: no material selected."))
        elif MATERIALS and item.material not in MATERIALS:
            problems.append(
                Problem(
                    "error",
                    path,
                    f"{what}: material '{item.material}' does not exist in Bukkit (1.21.10).",
                    "Pick a material from the list.",
                )
            )
        elif item.material == "AIR":
            problems.append(Problem("error", path, f"{what}: AIR is not a valid item."))
        if item.amount < 1:
            problems.append(Problem("error", path, f"{what}: amount must be at least 1."))
    else:
        if not item.provider.strip():
            problems.append(Problem("error", path, f"{what}: no item provider given."))
        if not item.custom_id.strip():
            problems.append(
                Problem("error", path, f"{what}: no item id given for provider '{item.provider}'.")
            )
        if item.amount < 1:
            problems.append(Problem("error", path, f"{what}: amount must be at least 1."))
    for label, text in [("name", item.name), *[(f"lore line {i + 1}", line) for i, line in enumerate(item.lore)]]:
        if "\n" in text or "\r" in text or "\t" in text:
            problems.append(Problem("error", path, f"{what}: {label} must be a single line."))


# ------------------------------------------------------------------- key checks


def validate_key(key: KeyConfig) -> list[Problem]:
    problems: list[Problem] = []
    _check_id(problems, "id (keys/<id>.yml)", key.id, "Key id")
    _check_text(problems, "Name", key.name, "Key name", required=True)
    _check_item(problems, "ItemData", key.item, "Key item")
    if key.virtual:
        problems.append(
            Problem("info", "Virtual", "Virtual key: no physical item is given to players.")
        )
    return problems


# ----------------------------------------------------------------- crate checks


def validate_crate(crate: CrateConfig, key: KeyConfig | None = None) -> list[Problem]:
    problems: list[Problem] = []
    _check_id(problems, "id (crates/<id>.yml)", crate.id, "Crate id")
    _check_text(problems, "Name", crate.name, "Crate name", required=True)
    for i, line in enumerate(crate.description):
        _check_text(problems, f"Description[{i}]", line, f"Description line {i + 1}", required=False)
    _check_item(problems, "ItemProvider", crate.item, "Crate item")

    # ---- rewards -----------------------------------------------------------
    if not crate.rewards:
        problems.append(
            Problem("error", "Rewards.List", "A crate needs at least one reward.",
                    "Without rewards the crate opens and gives nothing.")
        )
    seen_ids: set[str] = set()
    for reward in crate.rewards:
        base = f"Rewards.List.{reward.id}"
        if not is_var_style(reward.id):
            _check_id(problems, base, reward.id, "Reward id")
        if reward.id in seen_ids:
            problems.append(Problem("error", base, "Duplicate reward id."))
        seen_ids.add(reward.id)

        if reward.type not in PluginDefaults.REWARD_TYPES:
            problems.append(Problem("error", f"{base}.Type", f"Type must be ITEM or COMMAND, got '{reward.type}'."))
        if not reward.rarity:
            problems.append(
                Problem("error", f"{base}.Rarity", "Rarity is required.",
                        "The plugin logs an error and falls back to the most common rarity.")
            )
        elif reward.rarity not in PluginDefaults.DEFAULT_RARITIES:
            problems.append(
                Problem(
                    "warning",
                    f"{base}.Rarity",
                    f"Rarity '{reward.rarity}' is not one of the built-in rarities (common, rare, mythic).",
                    "It must exist in config.yml:\n" + rarity_snippet(reward.rarity),
                )
            )
        if reward.weight <= 0:
            problems.append(
                Problem("error", f"{base}.Weight", "Weight must be greater than 0.",
                        "0 or negative weight means the reward can never roll "
                        "(and a rarity whose weights sum to 0 breaks the roll math).")
            )

        if reward.type == "ITEM":
            if not reward.items:
                problems.append(
                    Problem("error", f"{base}.ItemsData", "Item reward needs at least one item.",
                            "The plugin reports INSPECTIONS_REWARD_NO_ITEMS.")
                )
            for i, item in enumerate(reward.items):
                _check_item(problems, f"{base}.ItemsData.{i}", item, f"Reward item {i + 1}")
        else:
            if not reward.commands:
                problems.append(
                    Problem("error", f"{base}.Commands", "Command reward needs at least one command.",
                            "The plugin reports INSPECTIONS_REWARD_NO_COMMANDS.")
                )
            for i, command in enumerate(reward.commands):
                _check_command(problems, f"{base}.Commands[{i}]", command)
            if reward.preview is None:
                problems.append(
                    Problem("info", f"{base}.PreviewData",
                            "No preview item set — a paper icon with the reward name is generated.")
                )
            _check_text(problems, f"{base}.Name", reward.name, "Reward name", required=False)

        limits = reward.limits
        if limits.cooldown_type not in PluginDefaults.COOLDOWN_MODES:
            problems.append(
                Problem("error", f"{base}.Limits.CooldownType",
                        f"CooldownType must be DAILY or CUSTOM, got '{limits.cooldown_type}'.")
            )
        for field_name in ("global_amount", "player_amount"):
            if getattr(limits, field_name) < -1:
                problems.append(
                    Problem("warning", f"{base}.Limits.{field_name}",
                            "Use -1 for unlimited (values below -1 are meaningless).")
                )
        for field_name in ("global_cooldown", "player_cooldown"):
            if getattr(limits, field_name) < 0:
                problems.append(
                    Problem("warning", f"{base}.Limits.{field_name}", "Cooldown must be 0 or more seconds.")
                )
        if limits.enabled and limits.global_amount == -1 and limits.player_amount == -1 \
                and limits.global_cooldown == 0 and limits.player_cooldown == 0:
            problems.append(
                Problem("info", f"{base}.Limits.Enabled",
                        "Limits are enabled but nothing is limited — set an amount or cooldown.")
            )

    # ---- costs / key link --------------------------------------------------
    for cost in crate.costs:
        base = f"CostOptions.{cost.id}"
        _check_id(problems, base, cost.id, "Cost option id")
        if cost.enabled and not cost.entries:
            problems.append(
                Problem("warning", f"{base}.Entries",
                        "Cost has no entries — it charges nothing (free opening).")
            )
        if cost.icon is not None:
            _check_item(problems, f"{base}.Icon", cost.icon, "Cost icon")
        for i, entry in enumerate(cost.entries):
            epath = f"{base}.Entries.{i}"
            if entry.type == "key":
                if not entry.key_id:
                    problems.append(Problem("error", f"{epath}.Key", "Key entry needs a key id."))
                else:
                    _check_id(problems, f"{epath}.Key", entry.key_id, "Key id")
                    if key is not None and entry.key_id != key.id:
                        problems.append(
                            Problem(
                                "warning",
                                f"{epath}.Key",
                                f"Crate opens with key '{entry.key_id}' but you are saving key '{key.id}'.",
                                "The crate only accepts the key file it references "
                                f"(keys/{entry.key_id}.yml).",
                            )
                        )
                if entry.amount < 1:
                    problems.append(Problem("error", f"{epath}.Amount", "Key amount must be at least 1."))
            elif entry.type == "currency":
                if not entry.currency:
                    problems.append(Problem("error", f"{epath}.Currency", "Currency entry needs a currency id.")
                    )
                if entry.amount <= 0:
                    problems.append(Problem("error", f"{epath}.Amount", "Currency amount must be greater than 0."))
            else:
                problems.append(
                    Problem("error", f"{epath}.Type",
                            f"Unknown cost type '{entry.type}' (expected 'key' or 'currency').")
                )

    if key is not None and not any(
        entry.type == "key" for cost in crate.costs for entry in cost.entries
    ):
        problems.append(
            Problem(
                "warning",
                "CostOptions",
                f"This crate has no key cost, so key '{key.id}' will not open it.",
                "Add a cost option with Type: key (the crate → key link).",
            )
        )

    # ---- menus / animation -------------------------------------------------
    if crate.preview_enabled and crate.preview_id != PluginDefaults.PREVIEW_DEFAULT:
        problems.append(
            Problem("warning", "Preview.Id",
                    f"Preview menu '{crate.preview_id}' must exist in the plugin's menus folder.",
                    f"'{PluginDefaults.PREVIEW_DEFAULT}' always exists; the plugin reports "
                    "INSPECTIONS_CRATE_PREVIEW otherwise.")
        )
    if crate.animation_enabled:
        if crate.animation_id == "default":
            problems.append(
                Problem("error", "Animation.Id",
                        "'default' is not a valid opening animation — the plugin reports "
                        "INSPECTIONS_CRATE_OPENING.",
                        f"Built-in ids: {', '.join(PluginDefaults.OPENING_IDS)}.")
            )
        elif crate.animation_id not in PluginDefaults.OPENING_IDS:
            problems.append(
                Problem("warning", "Animation.Id",
                        f"Opening animation '{crate.animation_id}' must exist in the plugin's "
                        "openings folder, or the plugin reports INSPECTIONS_CRATE_OPENING.",
                        f"Built-in ids: {', '.join(PluginDefaults.OPENING_IDS)}.")
            )

    # ---- cooldowns / limits ------------------------------------------------
    if crate.cooldown_enabled and crate.cooldown_value < -1:
        problems.append(
            Problem("warning", "OpeningCooldown.Value",
                    "Cooldown must be -1 (once per player), 0 (off) or positive seconds.")
        )
    if crate.opening_limit_amount < 1:
        problems.append(
            Problem("error", "OpeningLimits.Amount", "Amount must be at least 1.",
                    "The plugin clamps anything below 1 to 1.")
        )

    # ---- world / hologram / effect ----------------------------------------
    for i, pos in enumerate(crate.positions):
        if not _POSITION_RE.match(pos):
            problems.append(
                Problem("error", f"Block.Positions[{i}]",
                        f"'{pos}' is not a valid position.",
                        "Format: x,y,z,world (e.g. 14,2,1,world). A bad position can "
                        "break loading of the whole crate.")
            )
    if not crate.positions:
        problems.append(
            Problem("info", "Block.Positions",
                    "No linked blocks: the crate has no physical location (no hologram/effect).")
        )
    if crate.hologram_enabled and crate.hologram_template != PluginDefaults.HOLOGRAM_TEMPLATE_DEFAULT:
        problems.append(
            Problem("warning", "Block.Hologram.Template",
                    f"Hologram template '{crate.hologram_template}' must exist in config.yml "
                    "(Crate.Holograms.TemplateList), or the plugin reports "
                    "INSPECTIONS_CRATE_HOLOGRAM.",
                    f"'{PluginDefaults.HOLOGRAM_TEMPLATE_DEFAULT}' always exists.")
        )
    if crate.effect_model not in PluginDefaults.EFFECT_MODELS:
        problems.append(
            Problem("warning", "Block.Effect.Model",
                    f"Effect model '{crate.effect_model}' is not registered — it silently does nothing.",
                    "Models: " + ", ".join(PluginDefaults.EFFECT_MODELS) + ".")
        )
    if crate.effect_enabled and crate.effect_model == "none":
        problems.append(
            Problem("info", "Block.Effect", "Effect is enabled but the model is 'none' (no visual effect).")
        )
    particle_name = crate.particle.name.strip().upper()
    if not particle_name or particle_name == "NULL":
        problems.append(
            Problem("warning", "Block.Effect.Particle.Name",
                    "No particle set — the plugin falls back to CLOUD.")
        )
    elif PARTICLES and particle_name not in PARTICLES:
        problems.append(
            Problem("warning", "Block.Effect.Particle.Name",
                    f"Particle '{crate.particle.name}' does not exist on this server version — "
                    "the plugin silently falls back to CLOUD.",
                    "Particle names were renamed in 1.21.3 (REDSTONE → DUST, "
                    "VILLAGER_HAPPY → HAPPY_VILLAGER, SPELL → EFFECT).")
        )
    elif particle_name in PluginDefaults.UNSUPPORTED_PARTICLES:
        problems.append(
            Problem("warning", "Block.Effect.Particle.Name",
                    f"Particle '{particle_name}' is not supported by crate effects "
                    "(CrateUtils.isSupportedParticle) — it falls back to CLOUD.")
        )
    if particle_name in ("DUST", "DUST_COLOR_TRANSITION") and not crate.particle.color:
        problems.append(
            Problem("error", "Block.Effect.Particle.Color",
                    f"{crate.particle.name} requires a color (Red,Green,Blue).",
                    "Example: 255,128,0")
        )
    if crate.particle.material and not (MATERIALS and crate.particle.material in MATERIALS):
        problems.append(
            Problem("error", "Block.Effect.Particle.Material",
                    f"Particle material '{crate.particle.material}' does not exist.")
        )

    # ---- post-open commands ------------------------------------------------
    for i, command in enumerate(crate.post_open_commands):
        _check_command(problems, f"Post-Open.Commands[{i}]", command)

    # ---- milestones --------------------------------------------------------
    for i, milestone in enumerate(crate.milestones):
        base = f"Milestones.List.{i}"
        if crate.reward_by_id(milestone.reward_id) is None:
            problems.append(
                Problem("error", f"{base}.Reward_Id",
                        f"Milestone references unknown reward '{milestone.reward_id}'.",
                        "Use an id from Rewards.List.")
            )
        if milestone.openings < 1:
            problems.append(Problem("error", f"{base}.Openings", "Openings must be at least 1."))

    return sorted(problems, key=lambda p: (_LEVEL_ORDER.get(p.level, 9), p.path))
