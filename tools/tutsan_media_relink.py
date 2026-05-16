from __future__ import annotations

from dataclasses import dataclass
import shlex


@dataclass(frozen=True)
class Region:
    start: float
    end: float
    name: str


@dataclass(frozen=True)
class ItemSource:
    position: float
    length: float
    name: str | None
    source_file: str
    is_relative: bool

    @property
    def end(self) -> float:
        return self.position + self.length

    def overlaps(self, start: float, end: float) -> bool:
        return self.position < end and self.end > start


def find_region(text: str, region_id: int, region_name: str) -> Region:
    start: float | None = None

    for line in text.splitlines():
        marker = _parse_marker_line(line)
        if marker is None:
            continue

        marker_id, marker_position, marker_name, marker_kind = marker
        if marker_id != region_id or marker_kind != "1":
            continue

        if start is None:
            if marker_name == region_name:
                start = marker_position
            continue

        if marker_name == "":
            return Region(start=start, end=marker_position, name=region_name)

    raise ValueError(f"region {region_id} / {region_name!r} not found")


def parse_items(text: str) -> list[ItemSource]:
    return [_parse_item_block(block) for block in _item_blocks(text)]


def _parse_marker_line(line: str) -> tuple[int, float, str, str] | None:
    stripped = line.strip()
    if not stripped.startswith("MARKER "):
        return None

    try:
        parts = shlex.split(stripped)
    except ValueError:
        return None

    if len(parts) < 5:
        return None

    try:
        return int(parts[1]), float(parts[2]), parts[3], parts[4]
    except ValueError:
        return None


def _item_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    depth = 0

    for line in text.splitlines():
        stripped = line.strip()
        if current is None:
            if stripped.startswith("<ITEM"):
                current = [line]
                depth = 1
            continue

        current.append(line)
        if stripped.startswith("<"):
            depth += 1
        elif stripped == ">":
            depth -= 1
            if depth == 0:
                blocks.append(current)
                current = None

    return blocks


def _parse_item_block(lines: list[str]) -> ItemSource:
    position = _required_float(lines, "POSITION")
    length = _required_float(lines, "LENGTH")
    name = _optional_value(lines, "NAME")
    source_file = _required_value(lines, "FILE")

    return ItemSource(
        position=position,
        length=length,
        name=name,
        source_file=source_file,
        is_relative=not source_file.startswith("/"),
    )


def _required_float(lines: list[str], key: str) -> float:
    value = _required_value(lines, key)
    return float(value)


def _required_value(lines: list[str], key: str) -> str:
    value = _optional_value(lines, key)
    if value is None:
        raise ValueError(f"missing {key} in item block")
    return value


def _optional_value(lines: list[str], key: str) -> str | None:
    prefix = f"{key} "
    for line in lines:
        stripped = line.strip()
        if stripped == key:
            return ""
        if stripped.startswith(prefix):
            return _parse_value(stripped[len(prefix) :])
    return None


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith('"'):
        parts = shlex.split(raw)
        return parts[0] if parts else ""
    return raw
