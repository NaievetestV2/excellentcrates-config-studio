"""Data model for the two ExcellentCrates config files.

Every field mirrors a key from ``docs/schema.md``.  Defaults are the values the
*plugin* uses when the key is absent (or, where noted, the values the plugin's
own ``createCrate()`` / ``createKey()`` write), so untouched files round-trip
through the in-game editor without changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .snbt import ItemSpec

__all__ = [
    "VAR_ID_RE",
    "PluginDefaults",
    "ParticleSpec",
    "Limits",
    "CostEntry",
    "CostOption",
    "Reward",
    "Milestone",
    "CrateConfig",
    "KeyConfig",
    "is_var_style",
    "var_style",
]


#: id format required by nightcore ``Strings.varStyle`` (lowercase, no spaces).
VAR_ID_RE = re.compile(r"^[a-z0-9_-]+$")


def is_var_style(value: str) -> bool:
    return bool(value) and bool(VAR_ID_RE.match(value))


def var_style(value: str) -> str:
    """Approximate ``Strings.varStyle``: lowercase, whitespace → ``_``, drop rest."""
    out: list[str] = []
    for ch in value.strip().lower():
        if ch.isspace():
            out.append("_")
        elif ch in "abcdefghijklmnopqrstuvwxyz0123456789_-":
            out.append(ch)
    # collapse repeated underscores
    text = re.sub(r"_{2,}", "_", "".join(out))
    return text.strip("_")


class PluginDefaults:
    """Constants the plugin hardcodes (see docs/schema.md)."""

    DATAVER = 600
    #: ``OpeningManager.loadDefaults()`` — providers present on a fresh server.
    OPENING_IDS = (
        "csgo",
        "enclosing",
        "mystery",
        "roulette",
        "storm",
        "simple_roll",
        "selective_1",
        "selective_3",
    )
    OPENING_DEFAULT = "simple_roll"  # our default: valid on every fresh server
    PREVIEW_DEFAULT = "default"
    HOLOGRAM_TEMPLATE_DEFAULT = "default"
    EFFECT_MODELS = (
        "none",
        "helix",
        "spiral",
        "sphere",
        "heart",
        "pulsar",
        "beacon",
        "tornado",
        "vortex",
        "simple",
    )
    #: rarity ids shipped in the plugin's global config.yml
    DEFAULT_RARITIES = {"common": 70.0, "rare": 25.0, "mythic": 5.0}
    #: particles the crate effect system refuses (CrateUtils.isSupportedParticle)
    UNSUPPORTED_PARTICLES = {"VIBRATION", "DUST_COLOR_TRANSITION", "TRAIL"}
    COST_TYPE_KEY = "key"
    COST_TYPE_CURRENCY = "currency"
    REWARD_TYPES = ("ITEM", "COMMAND")
    COOLDOWN_MODES = ("DAILY", "CUSTOM")


def default_crate_item(name: str = "") -> ItemSpec:
    """``CrateManager.createCrate()`` uses ``Material.CHEST`` with the crate name."""
    return ItemSpec(material="CHEST", name=name)


def default_key_item(name: str = "") -> ItemSpec:
    """``KeyManager.createKey()`` uses ``TRIPWIRE_HOOK`` named after the key."""
    return ItemSpec(material="TRIPWIRE_HOOK", name=name)


def default_cost_icon() -> ItemSpec:
    """Legacy key-cost migration uses ``TRIAL_KEY`` (``Crate.java:196``)."""
    return ItemSpec(material="TRIAL_KEY")


# ---------------------------------------------------------------------- particles


@dataclass
class ParticleSpec:
    name: str = "CLOUD"
    material: str = ""  # block-data particles (BLOCK, FALLING_DUST, ...)
    color: str = ""  # "r,g,b" for DUST / color particles
    size: float = 1.0  # DUST
    power: float = 1.0  # Spell-type (1.21.10+)

    def is_default(self) -> bool:
        return self.name == "CLOUD" and not self.material and not self.color


# ------------------------------------------------------------------------- rewards


@dataclass
class Limits:
    enabled: bool = False
    cooldown_type: str = "DAILY"
    global_amount: int = -1
    player_amount: int = -1
    global_cooldown: int = 0
    player_cooldown: int = 0

    def is_unlimited(self) -> bool:
        return (
            not self.enabled
            and self.global_amount == -1
            and self.player_amount == -1
            and self.global_cooldown == 0
            and self.player_cooldown == 0
        )


@dataclass
class CostEntry:
    """One line inside a cost option — ``Type: key`` or ``Type: currency``."""

    type: str = "key"  # 'key' | 'currency'
    key_id: str = ""  # type=key
    currency: str = ""  # type=currency
    amount: float = 1

    def describe(self) -> str:
        if self.type == "key":
            return f"{self.amount:g} x key '{self.key_id}'"
        return f"{self.amount:g} x currency '{self.currency}'"


@dataclass
class CostOption:
    id: str
    enabled: bool = True
    name: str = ""
    icon: ItemSpec = field(default_factory=default_cost_icon)
    entries: list[CostEntry] = field(default_factory=list)


@dataclass
class Reward:
    id: str
    type: str = "ITEM"  # ITEM | COMMAND
    rarity: str = "common"
    weight: float = 10.0
    broadcast: bool = False
    preview: Optional[ItemSpec] = None  # None → generated from content
    required_permissions: list[str] = field(default_factory=list)
    ignored_permissions: list[str] = field(default_factory=list)
    limits: Limits = field(default_factory=Limits)

    # ITEM
    items: list[ItemSpec] = field(default_factory=list)
    custom_preview: bool = False
    placeholder_apply: bool = False

    # COMMAND
    name: str = ""
    description: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)

    def content_summary(self) -> str:
        if self.type == "COMMAND":
            return f"{len(self.commands)} command(s)"
        return f"{len(self.items)} item(s)"


@dataclass
class Milestone:
    reward_id: str
    openings: int = 1


# ---------------------------------------------------------------------------- crate


@dataclass
class CrateConfig:
    id: str = "my_crate"
    name: str = "My Crate"
    description: list[str] = field(default_factory=list)
    item: ItemSpec = field(default_factory=default_crate_item)
    item_stackable: bool = True
    permission_required: bool = False

    preview_enabled: bool = True
    preview_id: str = PluginDefaults.PREVIEW_DEFAULT
    animation_enabled: bool = True
    animation_id: str = PluginDefaults.OPENING_DEFAULT

    cooldown_enabled: bool = False
    cooldown_value: int = 0  # 0 = off, -1 = once per player, >0 seconds
    opening_limit_amount: int = 1

    costs: list[CostOption] = field(default_factory=list)

    positions: list[str] = field(default_factory=list)  # "x,y,z,world"
    pushback_enabled: bool = False
    hologram_enabled: bool = True
    hologram_template: str = PluginDefaults.HOLOGRAM_TEMPLATE_DEFAULT
    hologram_y_offset: float = 0.0
    effect_enabled: bool = True
    effect_model: str = "helix"
    particle: ParticleSpec = field(default_factory=ParticleSpec)

    post_open_commands: list[str] = field(default_factory=list)
    rewards: list[Reward] = field(default_factory=list)
    milestones: list[Milestone] = field(default_factory=list)
    milestones_repeatable: bool = False
    # Unknown top-level keys from an imported file, preserved verbatim.
    extra: dict = field(default_factory=dict)

    def reward_by_id(self, reward_id: str) -> Optional[Reward]:
        for reward in self.rewards:
            if reward.id == reward_id:
                return reward
        return None

    def key_cost(self) -> Optional[CostEntry]:
        """First key-type entry (the crate → key link), if any."""
        for cost in self.costs:
            for entry in cost.entries:
                if entry.type == "key":
                    return entry
        return None


# ---------------------------------------------------------------------------- key


@dataclass
class KeyConfig:
    id: str = "my_key"
    name: str = "My Key"
    virtual: bool = False
    item: ItemSpec = field(default_factory=default_key_item)
    item_stackable: bool = True
    # Unknown keys from an imported file, preserved verbatim.
    extra: dict = field(default_factory=dict)
