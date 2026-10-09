"""SNBT helpers: item serialization for ExcellentCrates configs.

Nightcore stores items as ``{Provider, Data}`` where vanilla items carry the
whole ItemStack as an SNBT string in ``Data.Value`` (see
``docs/schema.md`` §4).  This module builds those strings from a small item
spec and can parse them back, so imported files round-trip through the app.

Text components follow the shape found in plugin-written files
(``/tmp/opencode/armor_crate.yml``): NBT *compounds* with ``text``,
``italic: 0b``, optional ``color: "#RRGGBB"`` and style flags.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

__all__ = [
    "ItemSpec",
    "item_snbt",
    "write_item_provider",
    "parse_snbt",
    "extract_item",
    "legacy_to_components",
    "components_to_legacy",
    "SnbtError",
]


class SnbtError(Exception):
    pass


# ----------------------------------------------------------------- item spec


@dataclass
class ItemSpec:
    """Editor-facing description of one item (crate/key/reward/cost/preview)."""

    provider: str = "vanilla"  # 'vanilla' or a custom adapter name (nexo, ...)
    material: str = "CHEST"  # vanilla Material name
    amount: int = 1
    name: str = ""  # legacy '&' color codes
    lore: list[str] = field(default_factory=list)
    texture: str = ""  # base64 textures value for player heads
    custom_id: str = ""  # item id for custom providers
    # Verbatim SNBT from an imported file. While set (and vanilla) the emitter
    # writes this string unchanged, preserving NBT the editor does not model
    # (enchantments, custom_data, ...). Editing the item in the GUI clears it.
    raw_value: Optional[str] = None
    # DataVersion sibling of Data.Value, written by the plugin itself; kept on
    # import so plugin-written files round-trip. Absent for fresh items.
    raw_data_version: Optional[int] = None

    def is_vanilla(self) -> bool:
        return self.provider == "vanilla"

    def display_material(self) -> str:
        return self.material if self.is_vanilla() else self.custom_id


# ------------------------------------------------------------------ legacy text

_STANDARD_COLORS = {
    "0": "#000000", "1": "#0000AA", "2": "#00AA00", "3": "#00AAAA",
    "4": "#AA0000", "5": "#AA00AA", "6": "#FFAA00", "7": "#AAAAAA",
    "8": "#555555", "9": "#5555FF", "a": "#55FF55", "b": "#55FFFF",
    "c": "#FF5555", "d": "#FF55FF", "e": "#FFFF55", "f": "#FFFFFF",
}
_STYLE_FLAGS = {
    "l": "bold",
    "o": "italic",
    "n": "underlined",
    "m": "strikethrough",
    "k": "obfuscated",
}


@dataclass
class _Segment:
    text: str
    color: Optional[str] = None
    styles: set[str] = field(default_factory=set)


def legacy_to_components(text: str) -> list[dict[str, Any]]:
    """Convert ``&``/``§`` legacy text into Minecraft text components."""
    return [_segment_to_component(seg) for seg in _split_legacy(text)]


def _split_legacy(text: str) -> list[_Segment]:
    # normalize section signs, then scan
    text = text.replace("§", "&")
    segments: list[_Segment] = []
    current = _Segment("")
    color: Optional[str] = None
    styles: set[str] = set()
    i = 0
    n = len(text)
    pending = ""  # buffered literal characters

    def flush() -> None:
        nonlocal pending
        if pending:
            segments.append(_Segment(pending, color, set(styles)))
            pending = ""

    while i < n:
        ch = text[i]
        if ch != "&" or i + 1 >= n:
            pending += ch
            i += 1
            continue
        code = text[i + 1].lower()
        # hex forms: &#RRGGBB  and  &x&R&R&R&R&R&R
        if code == "#" and i + 7 < n and re.fullmatch(r"[0-9a-fA-F]{6}", text[i + 2 : i + 8]):
            flush()
            color = "#" + text[i + 2 : i + 8].upper()
            styles.clear()
            i += 8
            continue
        if code == "x" and i + 14 < n:
            raw = text[i + 2 : i + 14]
            if re.fullmatch(r"(?:&[0-9a-fA-F]){6}", raw):
                flush()
                color = "#" + raw.replace("&", "").upper()
                styles.clear()
                i += 14
                continue
        if code in _STANDARD_COLORS:
            flush()
            color = _STANDARD_COLORS[code]
            styles.clear()
            i += 2
            continue
        if code == "r":
            flush()
            color = None
            styles.clear()
            i += 2
            continue
        if code in _STYLE_FLAGS:
            flush()
            styles.add(_STYLE_FLAGS[code])
            i += 2
            continue
        # unknown sequence: keep literally (e.g. a lone '&')
        pending += ch
        i += 1
    flush()
    # merge segments that share color/styles (keeps components compact)
    merged: list[_Segment] = []
    for seg in segments:
        if merged and merged[-1].color == seg.color and merged[-1].styles == seg.styles:
            merged[-1].text += seg.text
        else:
            merged.append(_Segment(seg.text, seg.color, set(seg.styles)))
    return merged


def _segment_to_component(seg: _Segment) -> dict[str, Any]:
    comp: dict[str, Any] = {"text": seg.text}
    if seg.color:
        comp["color"] = seg.color
    # custom_name / lore render italic by default — always state it explicitly.
    comp["italic"] = "italic" in seg.styles
    if "bold" in seg.styles:
        comp["bold"] = True
    if "underlined" in seg.styles:
        comp["underlined"] = True
    if "strikethrough" in seg.styles:
        comp["strikethrough"] = True
    if "obfuscated" in seg.styles:
        comp["obfuscated"] = True
    return comp


_STYLE_ORDER = ("bold", "italic", "underlined", "strikethrough", "obfuscated")


def components_to_legacy(components: Any) -> str:
    """Best-effort inverse of :func:`legacy_to_components` (for imports)."""
    out: list[str] = []

    def walk(comp: Any, inherited_color: Optional[str], inherited: set[str]) -> None:
        if not isinstance(comp, dict):
            return
        color = comp.get("color", inherited_color)
        if not isinstance(color, str):
            color = inherited_color
        styles = set(inherited)
        for flag in _STYLE_ORDER:
            state = comp.get(flag)
            if state is True:
                styles.add(flag)
            elif state is False:
                styles.discard(flag)
        text = comp.get("text")
        if isinstance(text, str) and text:
            prefix = ""
            color_changed = color is not None and color != inherited_color
            if color_changed:
                prefix += _color_to_legacy(color)
                # legacy color codes reset styles: restate what is active
                restated = set(styles)
            else:
                restated = styles - inherited
            prefix += "".join(_STYLE_TO_LEGACY[f] for f in _STYLE_ORDER if f in restated)
            out.append(prefix + text)
        extras = comp.get("extra")
        if isinstance(extras, list):
            for extra in extras:
                walk(extra, color, styles)

    if isinstance(components, dict):
        walk(components, None, set())
    elif isinstance(components, list):
        for comp in components:
            walk(comp, None, set())
    return "".join(out)


_STYLE_TO_LEGACY = {
    "bold": "&l",
    "italic": "&o",
    "underlined": "&n",
    "strikethrough": "&m",
    "obfuscated": "&k",
}


_HEX_TO_STANDARD = {v: k for k, v in _STANDARD_COLORS.items()}


def _color_to_legacy(color: str) -> str:
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        upper = color.upper()
        standard = _HEX_TO_STANDARD.get(upper)
        return "&" + standard if standard else "&#" + upper[1:]
    return ""


# ------------------------------------------------------------------- SNBT emit


def snbt(value: Any) -> str:
    """Render a Python value as an SNBT literal."""
    if isinstance(value, bool):
        return "1b" if value else "0b"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) + "f"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = [f"{_snbt_key(k)}:{snbt(v)}" for k, v in value.items()]
        return "{" + ",".join(parts) + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        return "[" + ",".join(snbt(v) for v in value) + "]"
    raise SnbtError(f"unsupported SNBT value: {type(value).__name__}")


_SAFE_KEY = re.compile(r"^[A-Za-z0-9_.+-]+$")


def _snbt_key(key: str) -> str:
    if _SAFE_KEY.match(key):
        return key
    return '"' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'


def item_snbt(spec: ItemSpec) -> str:
    """Whole-ItemStack SNBT string for ``Data.Value``."""
    if not spec.is_vanilla():
        raise SnbtError("only vanilla items have an SNBT Value")
    material = spec.material.lower()
    if not _SAFE_MATERIAL.match(material):
        raise SnbtError(f"invalid material name: {spec.material!r}")
    count = max(1, int(spec.amount))
    data: dict[str, Any] = {}
    components: dict[str, Any] = {}
    if spec.name:
        name_parts = legacy_to_components(spec.name)
        if name_parts:
            components["minecraft:custom_name"] = _join_components(name_parts)
    if spec.lore:
        lore_parts: list[Any] = []
        for line in spec.lore:
            parts = legacy_to_components(line)
            lore_parts.append(_join_components(parts) if parts else {"text": ""})
        components["minecraft:lore"] = lore_parts
    if spec.texture:
        components["minecraft:profile"] = {
            "properties": [{"name": "textures", "value": spec.texture}]
        }
    data["count"] = count
    data["id"] = f"minecraft:{material}"
    if components:
        data["components"] = components
    return snbt(data)


_SAFE_MATERIAL = re.compile(r"^[a-z0-9_.]+$")


def _join_components(parts: list[dict[str, Any]]) -> dict[str, Any]:
    if len(parts) == 1:
        return parts[0]
    base = dict(parts[0])
    base["extra"] = parts[1:]
    return base


def write_item_provider(spec: ItemSpec) -> dict[str, Any]:
    """Build the ``{Provider, Data}`` mapping for a YAML document."""
    if spec.is_vanilla():
        if spec.raw_value:
            data: dict[str, Any] = {"Value": spec.raw_value}
            if spec.raw_data_version is not None:
                data["DataVersion"] = int(spec.raw_data_version)
            return {"Provider": "vanilla", "Data": data}
        return {
            "Provider": "vanilla",
            "Data": {"Value": item_snbt(spec)},
        }
    amount = max(1, int(spec.amount))
    return {
        "Provider": spec.provider,
        "Data": {"ID": spec.custom_id, "Amount": amount},
    }


# ------------------------------------------------------------------- SNBT parse


def parse_snbt(text: str) -> Any:
    """Parse an SNBT literal (compound/list/scalar) into Python values."""
    pos = 0
    src = text

    def err(msg: str) -> SnbtError:
        return SnbtError(f"{msg} (at {pos}: {src[max(0, pos - 10):pos + 10]!r})")

    def skip_ws() -> None:
        nonlocal pos
        while pos < len(src) and src[pos] in " \t\n\r":
            pos += 1

    def parse_value() -> Any:
        nonlocal pos
        skip_ws()
        if pos >= len(src):
            raise err("unexpected end")
        ch = src[pos]
        if ch == "{":
            pos += 1
            result: dict[str, Any] = {}
            skip_ws()
            if pos < len(src) and src[pos] == "}":
                pos += 1
                return result
            while True:
                skip_ws()
                key = parse_key()
                skip_ws()
                if pos >= len(src) or src[pos] != ":":
                    raise err("expected ':'")
                pos += 1
                result[key] = parse_value()
                skip_ws()
                if pos >= len(src):
                    raise err("unterminated compound")
                if src[pos] == ",":
                    pos += 1
                    continue
                if src[pos] == "}":
                    pos += 1
                    return result
                raise err("malformed compound")
        if ch == "[":
            pos += 1
            items: list[Any] = []
            skip_ws()
            if pos < len(src) and src[pos] == "]":
                pos += 1
                return items
            while True:
                items.append(parse_value())
                skip_ws()
                if pos >= len(src):
                    raise err("unterminated list")
                if src[pos] == ",":
                    pos += 1
                    continue
                if src[pos] == "]":
                    pos += 1
                    return items
                raise err("malformed list")
        if ch == '"':
            return parse_quoted()
        return parse_unquoted()

    def parse_key() -> str:
        nonlocal pos
        skip_ws()
        if pos < len(src) and src[pos] == '"':
            return parse_quoted()
        start = pos
        while pos < len(src) and src[pos] not in ":,}":
            pos += 1
        key = src[start:pos].strip()
        if not key:
            raise err("empty key")
        return key

    def parse_quoted() -> str:
        nonlocal pos
        quote = src[pos]
        pos += 1
        buf: list[str] = []
        while pos < len(src):
            ch = src[pos]
            if ch == "\\" and pos + 1 < len(src):
                buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(src[pos + 1], src[pos + 1]))
                pos += 2
                continue
            if ch == quote:
                pos += 1
                return "".join(buf)
            buf.append(ch)
            pos += 1
        raise err("unterminated string")

    def parse_unquoted() -> Any:
        nonlocal pos
        start = pos
        while pos < len(src) and src[pos] not in ",]}":
            pos += 1
        raw = src[start:pos].strip()
        if not raw:
            raise err("empty scalar")
        if raw.endswith("b") and re.fullmatch(r"[+-]?\d+b", raw):
            # NBT bytes: 0/1 are the boolean form used by text components.
            digits = raw[:-1]
            if digits in ("0", "1", "+0", "+1"):
                return digits.endswith("1")
            return int(digits)
        if raw.endswith("f") and re.fullmatch(r"[+-]?(?:\d+\.\d*|\.\d+|\d+)f", raw):
            return float(raw[:-1])
        if raw.endswith("l") and re.fullmatch(r"[+-]?\d+l", raw):
            return int(raw[:-1])
        if re.fullmatch(r"[+-]?\d+", raw):
            return int(raw)
        if re.fullmatch(r"[+-]?\d+\.\d*", raw):
            return float(raw)
        if raw in ("true", "false"):
            return raw == "true"
        return raw  # bare unquoted string

    value = parse_value()
    skip_ws()
    if pos != len(src):
        raise err("trailing content")
    return value


def extract_item(value: str) -> Optional[ItemSpec]:
    """Best-effort import of a ``Data.Value`` SNBT back into an :class:`ItemSpec`."""
    try:
        data = parse_snbt(value)
    except SnbtError:
        return None
    if not isinstance(data, dict):
        return None
    item_id = data.get("id")
    if not isinstance(item_id, str) or ":" not in item_id:
        return None
    material = item_id.split(":", 1)[1].upper()
    count = data.get("count", 1)
    if not isinstance(count, int):
        count = 1
    spec = ItemSpec(material=material, amount=max(1, count))
    components = data.get("components")
    if isinstance(components, dict):
        name = components.get("minecraft:custom_name")
        if name:
            spec.name = components_to_legacy(name)
        lore = components.get("minecraft:lore")
        if isinstance(lore, list):
            spec.lore = [components_to_legacy(line) for line in lore]
        profile = components.get("minecraft:profile")
        if isinstance(profile, dict):
            props = profile.get("properties")
            if isinstance(props, list):
                for prop in props:
                    if isinstance(prop, dict) and prop.get("name") == "textures":
                        value_str = prop.get("value")
                        if isinstance(value_str, str):
                            spec.texture = value_str
    return spec
