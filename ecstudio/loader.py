"""Load existing ExcellentCrates YAML into the data model (import / edit).

Known keys are mapped to :mod:`ecstudio.model` fields; item SNBT strings are
kept verbatim (``ItemSpec.raw_value``) so files we did not fully understand
round-trip byte-for-byte until the user actually edits an item.

Anything we cannot map raises :class:`LoadError` (or is reported as a warning)
instead of silently dropping data.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import yamlkit as y
from .model import (
    CostEntry,
    CostOption,
    CrateConfig,
    KeyConfig,
    Limits,
    Milestone,
    ParticleSpec,
    Reward,
)
from .snbt import ItemSpec, extract_item, parse_snbt, SnbtError

__all__ = ["LoadError", "LoadResult", "load_crate", "load_key"]


class LoadError(Exception):
    """Unsupported / broken input file."""


class LoadResult:
    def __init__(self, config: Any, warnings: Optional[list[str]] = None):
        self.config = config
        self.warnings = warnings or []


# --------------------------------------------------------------------- helpers


def _get_map(node: y.Node, key: str) -> y.Mapping:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if value is None:
        return y.Mapping()
    if not isinstance(value, y.Mapping):
        raise LoadError(f"'{key}' must be a mapping")
    return value


def _get_seq(node: y.Node, key: str) -> list[Any]:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if value is None:
        return []
    if not isinstance(value, y.Sequence):
        raise LoadError(f"'{key}' must be a list")
    return [item.value if isinstance(item, y.Scalar) else None for item in value.items]


def _str(node: y.Node, key: str, default: str = "") -> str:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if isinstance(value, y.Scalar) and isinstance(value.value, str):
        return value.value
    if isinstance(value, y.Scalar) and value.value is None:
        return default
    if value is None:
        return default
    raise LoadError(f"'{key}' must be a string")


def _bool(node: y.Node, key: str, default: bool = False) -> bool:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if isinstance(value, y.Scalar) and isinstance(value.value, bool):
        return value.value
    if value is None:
        return default
    raise LoadError(f"'{key}' must be true/false")


def _int(node: y.Node, key: str, default: int = 0) -> int:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if isinstance(value, y.Scalar) and isinstance(value.value, bool):
        raise LoadError(f"'{key}' must be a number")
    if isinstance(value, y.Scalar) and isinstance(value.value, (int, float)):
        return int(value.value)
    if value is None:
        return default
    raise LoadError(f"'{key}' must be a number")


def _float(node: y.Node, key: str, default: float = 0.0) -> float:
    value = node.get(key) if isinstance(node, y.Mapping) else None
    if isinstance(value, y.Scalar) and isinstance(value.value, bool):
        raise LoadError(f"'{key}' must be a number")
    if isinstance(value, y.Scalar) and isinstance(value.value, (int, float)):
        return float(value.value)
    if value is None:
        return default
    raise LoadError(f"'{key}' must be a number")


def _sorted_numeric(mapping: y.Mapping) -> list[tuple[str, y.Node]]:
    items = list(mapping.items)

    def key_fn(pair: tuple[str, y.Node]) -> tuple[int, Any]:
        try:
            return (0, int(pair[0]))
        except (ValueError, TypeError):
            return (1, pair[0])

    return sorted(items, key=key_fn)


def _load_item(node: y.Node, path: str) -> ItemSpec:
    if not isinstance(node, y.Mapping):
        raise LoadError(f"{path}: item must be a mapping (Provider/Data)")
    provider = _str(node, "Provider", "vanilla")
    data = node.get("Data")
    if data is None or not isinstance(data, y.Mapping):
        raise LoadError(f"{path}: missing 'Data'")
    if provider == "vanilla":
        value = _str(data, "Value", "")
        if not value:
            raise LoadError(f"{path}: vanilla item has no Data.Value SNBT")
        spec = extract_item(value)
        if spec is None:
            raise LoadError(
                f"{path}: cannot parse item SNBT — the file may use a newer "
                "format than this tool understands"
            )
        spec.raw_value = value
        version = data.get("DataVersion")
        if isinstance(version, y.Scalar) and isinstance(version.value, int) \
                and not isinstance(version.value, bool):
            spec.raw_data_version = version.value
        return spec
    return ItemSpec(
        provider=provider,
        custom_id=_str(data, "ID", ""),
        amount=max(1, _int(data, "Amount", 1)),
    )


def _load_limits(node: y.Node) -> Limits:
    limits = Limits()
    if not isinstance(node, y.Mapping):
        return limits
    limits.enabled = _bool(node, "Enabled", False)
    limits.cooldown_type = _str(node, "CooldownType", "DAILY")
    limits.global_amount = _int(node, "GlobalAmount", -1)
    limits.player_amount = _int(node, "PlayerAmount", -1)
    limits.global_cooldown = _int(node, "GlobalCooldown", 0)
    limits.player_cooldown = _int(node, "PlayerCooldown", 0)
    return limits


_PARTICLE_RENAMES = {
    "REDSTONE": "DUST",
    "VILLAGER_HAPPY": "HAPPY_VILLAGER",
    "SPELL": "EFFECT",
}


def _load_particle(node: y.Node) -> ParticleSpec:
    particle = ParticleSpec()
    if not isinstance(node, y.Mapping):
        return particle
    name = _str(node, "Name", "")
    name = name if name and name.lower() != "null" else "CLOUD"
    name = _PARTICLE_RENAMES.get(name.upper(), name)
    particle.name = name
    particle.material = _str(node, "Material", "")
    particle.color = _str(node, "Color", "")
    particle.size = _float(node, "Size", 1.0)
    particle.power = _float(node, "Power", 1.0)
    return particle


# ------------------------------------------------------------------------ crate


_TOP_LEVEL_KNOWN = {
    "_dataver", "Name", "Description", "ItemProvider", "ItemStackable",
    "Permission_Required", "Preview", "Animation", "OpeningCooldown",
    "OpeningLimits", "CostOptions", "Block", "Post-Open", "Rewards",
    "Milestones",
}
_TOP_LEVEL_LEGACY = {
    "Item", "Key", "Key.Ids", "Opening", "Preview_Config", "Animation_Config",
}


def load_crate(text: str) -> LoadResult:
    try:
        root = y.parse(text)
    except y.YamlError as exc:
        raise LoadError(str(exc)) from exc
    if not isinstance(root, y.Mapping):
        raise LoadError("crate file must be a YAML mapping")

    warnings: list[str] = []
    legacy = sorted(set(root.keys()) & _TOP_LEVEL_LEGACY)
    if legacy:
        raise LoadError(
            "legacy keys present (" + ", ".join(legacy) + ") — load and save the "
            "file once in-game so the plugin migrates it, then import again"
        )

    crate = CrateConfig()
    crate.name = _str(root, "Name", crate.name)
    crate.description = [v for v in _get_seq(root, "Description") if isinstance(v, str)]
    if "ItemProvider" in root:
        crate.item = _load_item(root.get("ItemProvider"), "ItemProvider")
    crate.item_stackable = _bool(root, "ItemStackable", True)
    crate.permission_required = _bool(root, "Permission_Required", False)

    preview = _get_map(root, "Preview")
    crate.preview_enabled = _bool(preview, "Enabled", False)
    crate.preview_id = _str(preview, "Id", "default")

    animation = _get_map(root, "Animation")
    crate.animation_enabled = _bool(animation, "Enabled", False)
    crate.animation_id = _str(animation, "Id", "default")

    cooldown = _get_map(root, "OpeningCooldown")
    crate.cooldown_enabled = _bool(cooldown, "Enabled", False)
    crate.cooldown_value = _int(cooldown, "Value", 0)
    crate.opening_limit_amount = _int(
        _get_map(root, "OpeningLimits"), "Amount", 1
    )

    # costs
    costs = _get_map(root, "CostOptions")
    for cost_id, cost_node in costs.items:
        if not isinstance(cost_node, y.Mapping):
            raise LoadError(f"CostOptions.{cost_id}: must be a mapping")
        cost = CostOption(id=cost_id)
        cost.enabled = _bool(cost_node, "Enabled", True)
        cost.name = _str(cost_node, "Name", "")
        if "Icon" in cost_node:
            cost.icon = _load_item(cost_node.get("Icon"), f"CostOptions.{cost_id}.Icon")
        entries = _get_map(cost_node, "Entries")
        for entry_key, entry_node in _sorted_numeric(entries):
            if not isinstance(entry_node, y.Mapping):
                raise LoadError(f"CostOptions.{cost_id}.Entries.{entry_key}: must be a mapping")
            entry_type = _str(entry_node, "Type", "")
            entry = CostEntry(type=entry_type, amount=_float(entry_node, "Amount", 1))
            if entry_type == "key":
                entry.key_id = _str(entry_node, "Key", "")
            elif entry_type == "currency":
                entry.currency = _str(entry_node, "Currency", "")
            cost.entries.append(entry)
        crate.costs.append(cost)

    # block
    block = _get_map(root, "Block")
    crate.positions = [v for v in _get_seq(block, "Positions") if isinstance(v, str)]
    crate.pushback_enabled = _bool(_get_map(block, "Pushback"), "Enabled", False)
    hologram = _get_map(block, "Hologram")
    crate.hologram_enabled = _bool(hologram, "Enabled", False)
    crate.hologram_template = _str(hologram, "Template", "default")
    crate.hologram_y_offset = _float(hologram, "Y_Offset", 0.0)
    effect = _get_map(block, "Effect")
    if "Enabled" in effect:
        crate.effect_enabled = _bool(effect, "Enabled", True)
    else:
        crate.effect_enabled = _str(effect, "Model", "none").lower() != "none"
    crate.effect_model = _str(effect, "Model", "none")
    if "Particle" in effect:
        crate.particle = _load_particle(effect.get("Particle"))

    crate.post_open_commands = [
        v for v in _get_seq(_get_map(root, "Post-Open"), "Commands") if isinstance(v, str)
    ]

    # rewards
    rewards = _get_map(_get_map(root, "Rewards"), "List")
    for reward_id, reward_node in rewards.items:
        if not isinstance(reward_node, y.Mapping):
            raise LoadError(f"Rewards.List.{reward_id}: must be a mapping")
        reward = Reward(id=reward_id)
        reward.type = _str(reward_node, "Type", "ITEM").upper()
        reward.rarity = _str(reward_node, "Rarity", "common")
        reward.weight = _float(reward_node, "Weight", -1.0)
        reward.broadcast = _bool(reward_node, "Broadcast", False)
        reward.required_permissions = [
            v for v in _get_seq(reward_node, "Required_Permissions") if isinstance(v, str)
        ]
        reward.ignored_permissions = [
            v for v in _get_seq(reward_node, "Ignored_For_Permissions") if isinstance(v, str)
        ]
        reward.limits = _load_limits(reward_node.get("Limits"))
        if "PreviewData" in reward_node:
            reward.preview = _load_item(
                reward_node.get("PreviewData"), f"Rewards.List.{reward_id}.PreviewData"
            )
        if reward.type == "COMMAND":
            reward.name = _str(reward_node, "Name", "")
            reward.description = [
                v for v in _get_seq(reward_node, "Description") if isinstance(v, str)
            ]
            reward.commands = [
                v for v in _get_seq(reward_node, "Commands") if isinstance(v, str)
            ]
        else:
            reward.custom_preview = _bool(reward_node, "Custom_Preview", False)
            reward.placeholder_apply = _bool(reward_node, "Placeholder_Apply", False)
            items = _get_map(reward_node, "ItemsData")
            for item_key, item_node in _sorted_numeric(items):
                reward.items.append(
                    _load_item(item_node, f"Rewards.List.{reward_id}.ItemsData.{item_key}")
                )
        crate.rewards.append(reward)

    # milestones
    milestones = _get_map(_get_map(root, "Milestones"), "List")
    crate.milestones_repeatable = _bool(_get_map(root, "Milestones"), "Repeatable", False)
    for mkey, mnode in _sorted_numeric(milestones):
        if not isinstance(mnode, y.Mapping):
            raise LoadError(f"Milestones.List.{mkey}: must be a mapping")
        crate.milestones.append(
            Milestone(
                reward_id=_str(mnode, "Reward_Id", ""),
                openings=_int(mnode, "Openings", 0),
            )
        )

    # preserve unknown top-level keys instead of dropping them
    unknown = [k for k in root.keys() if k not in _TOP_LEVEL_KNOWN]
    for key in unknown:
        crate.extra[key] = root.get(key)
        warnings.append(
            f"Unknown top-level key '{key}' is preserved as-is; nested unknown "
            "keys inside known sections are dropped on save."
        )

    # nested unknown-key audit (informational)
    for section in ("Block", "Preview", "Animation", "OpeningCooldown", "OpeningLimits"):
        node = root.get(section)
        if isinstance(node, y.Mapping):
            for key in node.keys():
                if key not in _SECTION_KNOWN.get(section, set()):
                    warnings.append(f"Unknown key '{section}.{key}' will be dropped on save.")

    return LoadResult(crate, warnings)


_SECTION_KNOWN = {
    "Block": {"Positions", "Pushback", "Hologram", "Effect"},
    "Preview": {"Enabled", "Id"},
    "Animation": {"Enabled", "Id"},
    "OpeningCooldown": {"Enabled", "Value"},
    "OpeningLimits": {"Amount"},
}


# -------------------------------------------------------------------------- key


def load_key(text: str) -> LoadResult:
    try:
        root = y.parse(text)
    except y.YamlError as exc:
        raise LoadError(str(exc)) from exc
    if not isinstance(root, y.Mapping):
        raise LoadError("key file must be a YAML mapping")
    if "Item" in root:
        raise LoadError(
            "legacy key 'Item' present — load and save the file once in-game so "
            "the plugin migrates it to ItemData, then import again"
        )

    warnings: list[str] = []
    key = KeyConfig()
    key.name = _str(root, "Name", key.name)
    key.virtual = _bool(root, "Virtual", False)
    if "ItemData" in root:
        key.item = _load_item(root.get("ItemData"), "ItemData")
    key.item_stackable = _bool(root, "ItemStackable", True)

    known = {"Name", "Virtual", "ItemData", "ItemStackable"}
    for k in root.keys():
        if k not in known:
            key.extra[k] = root.get(k)
            warnings.append(f"Unknown key '{k}' is preserved as-is on save.")
    return LoadResult(key, warnings)
