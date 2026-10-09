"""Minimal YAML emitter + parser, good enough for ExcellentCrates config files.

Design goals:

* Emit exactly the subset Bukkit's ``YamlConfiguration`` (SnakeYAML) reads:
  block mappings, block (indentless) sequences, quoted/plain scalars, ``[]`` /
  ``{}`` for empty collections, ``#`` comments.
* String scalars are written quoted whenever plain style would be ambiguous
  under YAML 1.1 (``yes``/``no``/``on``/``off``/``true``/``false``/``null``/
  numbers), so values like ``Name: no`` stay strings on the plugin side.
* Parse our own output back (round-trip validation) and hand-written Bukkit
  files (import).  Unsupported YAML features raise :class:`YamlError` with a
  line number instead of silently corrupting data.

Comments are attached to nodes on emit and ignored on parse (value round-trip
is what matters — comments never reach the plugin).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional, Union

__all__ = [
    "Node",
    "Scalar",
    "Mapping",
    "Sequence",
    "YamlError",
    "emit",
    "parse",
    "from_plain",
    "to_plain",
    "values_equal",
]


class YamlError(Exception):
    """Raised for unsupported YAML constructs or invalid values."""

    def __init__(self, message: str, line: Optional[int] = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


# --------------------------------------------------------------------------- nodes


@dataclass
class Scalar:
    value: Any  # str | int | float | bool | None
    comment: list[str] = field(default_factory=list)
    inline: Optional[str] = None


@dataclass
class Mapping:
    items: list[tuple[str, "Node"]] = field(default_factory=list)
    comment: list[str] = field(default_factory=list)
    inline: Optional[str] = None

    def set(self, key: str, value: "Node") -> "Mapping":
        for i, (k, _) in enumerate(self.items):
            if k == key:
                self.items[i] = (key, value)
                return self
        self.items.append((key, value))
        return self

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.items:
            if k == key:
                return v
        return default

    def keys(self) -> list[str]:
        return [k for k, _ in self.items]

    def __contains__(self, key: object) -> bool:
        return any(k == key for k, _ in self.items)


@dataclass
class Sequence:
    items: list["Node"] = field(default_factory=list)
    comment: list[str] = field(default_factory=list)
    inline: Optional[str] = None


Node = Union[Scalar, Mapping, Sequence]


# ---------------------------------------------------------------------- conversion


def from_plain(value: Any, comment: Optional[list[str]] = None) -> Node:
    """Build a node tree from plain Python data (dict/list/scalars)."""
    comment = comment or []
    if isinstance(value, dict):
        return Mapping([(str(k), from_plain(v)) for k, v in value.items()], comment=list(comment))
    if isinstance(value, (list, tuple)):
        return Sequence([from_plain(v) for v in value], comment=list(comment))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return Scalar(value, comment=list(comment))
    raise YamlError(f"unsupported value type: {type(value).__name__}")


def to_plain(node: Node) -> Any:
    if isinstance(node, Scalar):
        return node.value
    if isinstance(node, Mapping):
        return {k: to_plain(v) for k, v in node.items}
    if isinstance(node, Sequence):
        return [to_plain(v) for v in node.items]
    raise YamlError(f"unknown node: {node!r}")


def values_equal(a: Node, b: Node) -> bool:
    """Strict structural equality (``True`` never equals ``1``)."""
    return _eq(to_plain(a), to_plain(b))


def _eq(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, dict) and isinstance(b, dict):
        return list(a.keys()) == list(b.keys()) and all(_eq(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_eq(x, y) for x, y in zip(a, b))
    return False


# ------------------------------------------------------------------------- emit

_INDENT = "  "

# Plain-style whitelist: starts with a safe character, then only characters
# that never need quoting.  Everything else (':' '#' '&' leading indicators,
# unicode, ...) is single-quoted.
_PLAIN_OK = re.compile(r"^[A-Za-z_][A-Za-z0-9_./+\- ]*$")

def _float_ok(v: float) -> bool:
    return v == v and v not in (float("inf"), float("-inf"))


def format_scalar(value: Any) -> str:
    """Render a scalar the way Bukkit will read it back with the same type."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not _float_ok(value):
            raise YamlError(f"non-finite float cannot be written: {value!r}")
        return repr(value)
    if isinstance(value, str):
        return format_string(value)
    raise YamlError(f"unsupported scalar type: {type(value).__name__}")


def format_string(value: str) -> str:
    if "\n" in value or "\r" in value or "\t" in value:
        raise YamlError("multi-line / tab strings are not supported: %r" % value)
    if value == "":
        return "''"
    if _PLAIN_OK.match(value) and value.strip() == value:
        # Quote anything the parser would resolve to a non-string (YAML 1.1
        # booleans/nulls/numbers) so strings survive the round-trip.
        resolved = _resolve_plain(value, 0)
        if isinstance(resolved, str) and resolved == value:
            return value
    return "'" + value.replace("'", "''") + "'"


def _format_comment_lines(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        line = line.rstrip()
        out.append("# " + line if line else "#")
    return out


def emit(node: Node) -> str:
    """Render a node tree to YAML text (trailing newline included)."""
    out: list[str] = []
    _emit_block(node, 0, out)
    text = "\n".join(out)
    return text + "\n" if text else ""


def _emit_block(node: Node, depth: int, out: list[str]) -> None:
    comment = getattr(node, "comment", None) or []
    if comment:
        out.extend(_format_comment_lines(comment))
    if isinstance(node, Scalar):
        raise YamlError("top-level scalar documents are not supported")
    if isinstance(node, Sequence):
        raise YamlError(
            "sequences must be nested under a key (Bukkit-style documents only)"
        )
    _emit_mapping(node, depth, out)


def _emit_mapping(mapping: Mapping, depth: int, out: list[str]) -> None:
    indent = _INDENT * depth
    for key, value in mapping.items:
        comment = getattr(value, "comment", None) or []
        if comment:
            out.extend(indent + line for line in _format_comment_lines(comment))
        key_text = format_string(key)
        inline = getattr(value, "inline", None)
        suffix = f"  # {inline}" if inline else ""

        if isinstance(value, Scalar):
            out.append(f"{indent}{key_text}: {format_scalar(value.value)}{suffix}")
        elif isinstance(value, Mapping):
            if not value.items:
                out.append(f"{indent}{key_text}: {{}}{suffix}")
            else:
                out.append(f"{indent}{key_text}:{suffix}")
                _emit_mapping(value, depth + 1, out)
        elif isinstance(value, Sequence):
            if not value.items:
                out.append(f"{indent}{key_text}: []{suffix}")
            else:
                out.append(f"{indent}{key_text}:{suffix}")
                _emit_sequence(value, depth, out)
        else:  # pragma: no cover
            raise YamlError(f"unknown node under key {key!r}")


def _emit_sequence(seq: Sequence, depth: int, out: list[str]) -> None:
    # Bukkit/SnakeYAML write indentless sequences: '-' at the parent key indent.
    indent = _INDENT * depth
    for item in seq.items:
        comment = getattr(item, "comment", None) or []
        if comment:
            out.extend(indent + line for line in _format_comment_lines(comment))
        if isinstance(item, Scalar):
            out.append(f"{indent}- {format_scalar(item.value)}")
        elif isinstance(item, Mapping):
            if not item.items:
                out.append(f"{indent}- {{}}")
                continue
            first_key, first_value = item.items[0]
            first_comment = getattr(first_value, "comment", None) or []
            if first_comment:
                out.extend(indent + line for line in _format_comment_lines(first_comment))
            head = f"{indent}- {format_string(first_key)}: "
            if isinstance(first_value, Scalar):
                out.append(head + format_scalar(first_value.value))
            elif isinstance(first_value, Mapping) and not first_value.items:
                out.append(head + "{}")
            elif isinstance(first_value, Sequence) and not first_value.items:
                out.append(head + "[]")
            else:
                out.append(head.rstrip())
                if isinstance(first_value, Mapping):
                    _emit_mapping(first_value, depth + 2, out)
                else:
                    _emit_sequence(first_value, depth + 2, out)
            # remaining keys of the same mapping item
            rest = Mapping(item.items[1:])
            if rest.items:
                _emit_mapping(rest, depth + 1, out)
        else:  # pragma: no cover
            raise YamlError("unknown sequence item")


# ------------------------------------------------------------------------- parse


@dataclass
class _Line:
    no: int  # 1-based
    indent: int
    text: str  # content without indentation, comments stripped


def parse(text: str) -> Node:
    """Parse block-style YAML.  Raises :class:`YamlError` on anything exotic."""
    lines = _logical_lines(text)
    if not lines:
        return Mapping([])
    node, next_idx = _parse_node(lines, 0, lines[0].indent)
    if next_idx != len(lines):
        line = lines[next_idx]
        raise YamlError(f"unexpected content {line.text!r}", line.no)
    return node


def _logical_lines(text: str) -> list[_Line]:
    result: list[_Line] = []
    for no, raw in enumerate(text.split("\n"), start=1):
        raw = raw.rstrip("\r")
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError("tab indentation is not allowed", no)
        stripped = raw.lstrip(" ")
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        indent = len(raw) - len(stripped)
        content = _strip_comment(raw, indent, no).lstrip(" ")
        if not content:
            continue
        result.append(_Line(no, indent, content))
    return result


def _strip_comment(raw: str, indent: int, no: int) -> str:
    """Remove a trailing ``# comment`` (outside quotes) from a line."""
    quote: Optional[str] = None
    i = indent
    while i < len(raw):
        ch = raw[i]
        if quote:
            if quote == "'" and ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    i += 2
                    continue
                quote = None
            elif quote == '"' and ch == '"':
                if i + 1 < len(raw) and raw[i + 1] == "\\":
                    i += 2
                    continue
                quote = None
            elif quote == '"' and ch == "\\":
                i += 2
                continue
        else:
            if ch in "'\"":
                quote = ch
            elif ch == "#" and (i == indent or raw[i - 1] in " \t"):
                return raw[:i].rstrip()
        i += 1
    if quote:
        raise YamlError("unterminated quoted scalar", no)
    return raw.rstrip()


def _parse_node(lines: list[_Line], idx: int, indent: int) -> tuple[Node, int]:
    line = lines[idx]
    if line.indent != indent:
        raise YamlError(f"bad indentation (expected {indent})", line.no)
    if line.text == "-" or line.text.startswith("- "):
        return _parse_sequence(lines, idx, indent)
    return _parse_mapping(lines, idx, indent)


def _parse_sequence(lines: list[_Line], idx: int, indent: int) -> tuple[Sequence, int]:
    items: list[Node] = []
    while idx < len(lines):
        line = lines[idx]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlError("bad indentation inside sequence", line.no)
        if not (line.text == "-" or line.text.startswith("- ")):
            break
        body = line.text[1:].lstrip() if line.text.startswith("- ") else ""
        if not body:
            # value on the following lines
            idx += 1
            if idx < len(lines) and lines[idx].indent > indent:
                node, idx = _parse_node(lines, idx, lines[idx].indent)
            else:
                node = Scalar(None)
            items.append(node)
            continue
        _reject_unsupported(body, line.no)
        if _looks_like_key(body):
            # inline mapping item:  - key: value
            node, idx = _parse_inline_map(lines, idx, indent, body)
            items.append(node)
            continue
        items.append(_parse_scalar_token(body, line.no))
        idx += 1
    return Sequence(items), idx


def _parse_inline_map(lines: list[_Line], idx: int, dash_indent: int, head: str) -> tuple[Mapping, int]:
    """Parse ``- key: value`` plus any following keys indented under it."""
    line = lines[idx]
    key, rest = _split_key(head, line.no)
    mapping = Mapping()
    if rest:
        mapping.items.append((key, _parse_scalar_token(rest, line.no)))
        idx += 1
    else:
        idx += 1
        if idx < len(lines) and lines[idx].indent > dash_indent + 1:
            child_indent = lines[idx].indent
            node, idx = _parse_node(lines, idx, child_indent)
            mapping.items.append((key, node))
    # following keys belong to this mapping item, indented > dash_indent
    body_indent = None
    while idx < len(lines):
        line = lines[idx]
        if line.indent <= dash_indent:
            break
        if body_indent is None:
            body_indent = line.indent
        if line.indent != body_indent:
            raise YamlError("bad indentation inside sequence mapping", line.no)
        if line.text == "-" or line.text.startswith("- "):
            break
        if not _looks_like_key(line.text):
            break
        k, r = _split_key(line.text, line.no)
        if r:
            mapping.items.append((k, _parse_scalar_token(r, line.no)))
            idx += 1
        else:
            idx += 1
            if idx < len(lines) and lines[idx].indent > body_indent:
                node, idx = _parse_node(lines, idx, lines[idx].indent)
                mapping.items.append((k, node))
            else:
                mapping.items.append((k, Scalar(None)))
    return mapping, idx


def _parse_mapping(lines: list[_Line], idx: int, indent: int) -> tuple[Mapping, int]:
    mapping = Mapping()
    seen: set[str] = set()
    while idx < len(lines):
        line = lines[idx]
        if line.indent < indent:
            break
        if line.indent > indent:
            raise YamlError("bad indentation inside mapping", line.no)
        if line.text == "-" or line.text.startswith("- "):
            break
        if not _looks_like_key(line.text):
            raise YamlError(f"expected 'key: value', got {line.text!r}", line.no)
        _reject_unsupported(line.text, line.no)
        key, rest = _split_key(line.text, line.no)
        if key in seen:
            raise YamlError(f"duplicate key {key!r}", line.no)
        seen.add(key)
        idx += 1
        if rest:
            value: Node = _parse_scalar_token(rest, line.no)
        else:
            # nested block or empty value
            if idx < len(lines) and lines[idx].indent > indent:
                value, idx = _parse_node(lines, idx, lines[idx].indent)
            elif (
                idx < len(lines)
                and lines[idx].indent == indent
                and (lines[idx].text == "-" or lines[idx].text.startswith("- "))
            ):
                value, idx = _parse_sequence(lines, idx, indent)
            else:
                value = Scalar(None)
        mapping.items.append((key, value))
    return mapping, idx


def _reject_unsupported(text: str, no: int) -> None:
    if text.startswith(("&", "*", "!")):
        raise YamlError("anchors, aliases and tags are not supported", no)
    if text in ("|", ">", "|-", ">-", "|+", ">+"):
        raise YamlError("block scalars (| and >) are not supported", no)


def _looks_like_key(text: str) -> bool:
    try:
        _split_key(text, 1)
        return True
    except YamlError:
        return False


def _split_key(text: str, no: int) -> tuple[str, str]:
    """Split ``key: rest`` — key may be quoted.  Returns (key, rest)."""
    if not text:
        raise YamlError("empty line", no)
    quote: Optional[str] = None
    i = 0
    if text[0] in "'\"":
        quote = text[0]
        i = 1
        while i < len(text):
            ch = text[i]
            if quote == "'" and ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 2
                    continue
                i += 1
                break
            if quote == '"' and ch == '"':
                i += 1
                break
            if quote == '"' and ch == "\\":
                i += 2
                continue
            i += 1
        else:
            raise YamlError("unterminated quoted key", no)
        if i >= len(text) or text[i] != ":":
            raise YamlError(f"expected ':' after quoted key {text[:i]!r}", no)
        raw_key = text[:i]
        rest = text[i + 1:]
        key = _unquote(raw_key, no)
        if rest and not rest.startswith(" "):
            raise YamlError("missing space after ':'", no)
        return key, rest[1:].strip() if rest else ""
    # plain key: first ": " or trailing ":"
    for j, ch in enumerate(text):
        if ch == ":" and (j + 1 == len(text) or text[j + 1] == " "):
            key = text[:j]
            if not key:
                raise YamlError("empty key", no)
            if any(c in key for c in "[]{},"):
                raise YamlError(f"unsupported key {key!r}", no)
            return key, text[j + 1:].strip()
    raise YamlError(f"expected 'key: value', got {text!r}", no)


def _unquote(text: str, no: int) -> str:
    if len(text) >= 2 and text[0] == "'" and text[-1] == "'":
        return text[1:-1].replace("''", "'")
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        body = text[1:-1]
        out: list[str] = []
        i = 0
        while i < len(body):
            if body[i] == "\\" and i + 1 < len(body):
                esc = body[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, "\\" + esc))
                i += 2
            else:
                out.append(body[i])
                i += 1
        return "".join(out)
    if text.startswith(("[", "{")):
        raise YamlError("unexpected flow content", no)
    return text


def _parse_scalar_token(text: str, no: int) -> Node:
    _reject_unsupported(text, no)
    text = text.strip()
    if text.startswith(("[", "{")):
        return _parse_flow(text, no)
    if text.startswith(("'", '"')):
        # find matching close quote for full-token check
        value = _unquote_token(text, no)
        return Scalar(value)
    return Scalar(_resolve_plain(text, no))


def _unquote_token(text: str, no: int) -> str:
    quote = text[0]
    i = 1
    buf: list[str] = []
    while i < len(text):
        ch = text[i]
        if quote == "'":
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                rest = text[i:].strip()
                if rest:
                    raise YamlError(f"unexpected content after quoted scalar: {rest!r}", no)
                return "".join(buf)
            buf.append(ch)
            i += 1
        else:
            if ch == "\\" and i + 1 < len(text):
                esc = text[i + 1]
                buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}.get(esc, "\\" + esc))
                i += 2
                continue
            if ch == '"':
                i += 1
                rest = text[i:].strip()
                if rest:
                    raise YamlError(f"unexpected content after quoted scalar: {rest!r}", no)
                return "".join(buf)
            buf.append(ch)
            i += 1
    raise YamlError("unterminated quoted scalar", no)


def _resolve_plain(text: str, no: int) -> Any:
    """YAML 1.1-style resolution (matches what SnakeYAML does for Bukkit)."""
    low = text.lower()
    if text in ("", "~") or low == "null":
        return None
    if low in ("true", "yes", "on", "y"):
        return True
    if low in ("false", "no", "off", "n"):
        return False
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    if re.fullmatch(r"0x[0-9a-fA-F]+", text):
        return int(text, 16)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?", text) or re.fullmatch(
        r"[+-]?\d+[eE][+-]?\d+", text
    ):
        return float(text)
    if low in (".nan",):
        return float("nan")
    if low in (".inf", "+.inf"):
        return float("inf")
    if low == "-.inf":
        return float("-inf")
    return text


def _parse_flow(text: str, no: int) -> Node:
    pos = 0

    def skip_ws() -> None:
        nonlocal pos
        while pos < len(text) and text[pos] == " ":
            pos += 1

    def parse_value() -> Any:
        nonlocal pos
        skip_ws()
        if pos >= len(text):
            raise YamlError("unexpected end of flow value", no)
        ch = text[pos]
        if ch == "[":
            pos += 1
            out = []
            skip_ws()
            if pos < len(text) and text[pos] == "]":
                pos += 1
                return Sequence([_as_node(v) for v in out])
            while True:
                out.append(parse_value())
                skip_ws()
                if pos >= len(text):
                    raise YamlError("unterminated flow sequence", no)
                if text[pos] == ",":
                    pos += 1
                    continue
                if text[pos] == "]":
                    pos += 1
                    return Sequence([_as_node(v) for v in out])
                raise YamlError("malformed flow sequence", no)
        if ch == "{":
            pos += 1
            pairs: list[tuple[str, Any]] = []
            skip_ws()
            if pos < len(text) and text[pos] == "}":
                pos += 1
                return Mapping([(k, Scalar(v)) for k, v in pairs])
            while True:
                skip_ws()
                key = parse_value()
                if not isinstance(key, str):
                    raise YamlError("flow mapping keys must be strings", no)
                skip_ws()
                if pos >= len(text) or text[pos] != ":":
                    raise YamlError("expected ':' in flow mapping", no)
                pos += 1
                value = parse_value()
                pairs.append((key, value))
                skip_ws()
                if pos >= len(text):
                    raise YamlError("unterminated flow mapping", no)
                if text[pos] == ",":
                    pos += 1
                    continue
                if text[pos] == "}":
                    pos += 1
                    return Mapping([(k, _as_node(v)) for k, v in pairs])
                raise YamlError("malformed flow mapping", no)
        if ch in "'\"":
            quote = ch
            pos += 1
            buf: list[str] = []
            while pos < len(text):
                c = text[pos]
                if quote == "'":
                    if c == "'":
                        if pos + 1 < len(text) and text[pos + 1] == "'":
                            buf.append("'")
                            pos += 2
                            continue
                        pos += 1
                        return "".join(buf)
                    buf.append(c)
                    pos += 1
                else:
                    if c == "\\" and pos + 1 < len(text):
                        buf.append(text[pos + 1])
                        pos += 2
                        continue
                    if c == '"':
                        pos += 1
                        return "".join(buf)
                    buf.append(c)
                    pos += 1
            raise YamlError("unterminated flow string", no)
        # plain scalar until , ] } or :
        start = pos
        while pos < len(text) and text[pos] not in ",]}:":
            pos += 1
        raw = text[start:pos].strip()
        return _resolve_plain(raw, no)

    value = parse_value()
    skip_ws()
    if pos != len(text):
        raise YamlError(f"unexpected content in flow value: {text[pos:]!r}", no)
    return _as_node(value)


def _as_node(value: Any) -> Node:
    if isinstance(value, (Scalar, Mapping, Sequence)):
        return value
    if isinstance(value, list):
        return Sequence([_as_node(v) for v in value])
    if isinstance(value, dict):
        return Mapping([(k, _as_node(v)) for k, v in value.items])
    return Scalar(value)
