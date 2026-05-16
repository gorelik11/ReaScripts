from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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


@dataclass(frozen=True)
class FileMeta:
    path: Path
    exists: bool
    size: int | None
    created: float | None
    modified: float | None


@dataclass(frozen=True)
class DuplicateInfo:
    basename: str
    root_path: Path
    audio_path: Path
    root_exists: bool
    audio_exists: bool
    root_size: int | None
    audio_size: int | None
    root_created: float | None
    audio_created: float | None
    root_modified: float | None
    audio_modified: float | None


@dataclass(frozen=True)
class Candidate:
    source_file: str
    basename: str
    root_path: Path
    audio_target_path: Path
    renamed_basename: str
    root_renamed_path: Path
    item_count: int
    tutsan_item_count: int
    metadata: FileMeta


@dataclass(frozen=True)
class Audit:
    region: Region
    candidates: list[Candidate]
    duplicates: dict[str, DuplicateInfo]
    non_tutsan_relative_sources: list[str]
    stop_reasons: list[str]


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


def stat_file(path: Path) -> FileMeta:
    exists = path.exists()
    if not exists:
        return FileMeta(
            path=path,
            exists=False,
            size=None,
            created=None,
            modified=None,
        )

    stat = path.stat()
    return FileMeta(
        path=path,
        exists=True,
        size=stat.st_size,
        created=getattr(stat, "st_birthtime", None),
        modified=stat.st_mtime,
    )


def target_name(basename: str) -> str:
    path = Path(basename)
    return f"{path.stem} - R7 Tutsan{path.suffix}"


def build_audit(
    rpp_path: Path,
    project_root: Path,
    audio_dir: Path,
    region_id: int,
    region_name: str,
) -> Audit:
    text = rpp_path.read_text(encoding="utf-8", errors="replace")
    region = find_region(text, region_id=region_id, region_name=region_name)
    items = parse_items(text)
    grouped = _group_items_by_source(items)
    candidates: list[Candidate] = []
    duplicates: dict[str, DuplicateInfo] = {}
    non_tutsan_relative_sources: list[str] = []
    stop_reasons: list[str] = []
    relative_sources_by_basename: dict[str, list[str]] = {}

    for source_file, source_items in grouped.items():
        if source_items[0].is_relative:
            relative_sources_by_basename.setdefault(Path(source_file).name, []).append(
                source_file
            )

    for source_file, source_items in grouped.items():
        is_relative = source_items[0].is_relative
        tutsan_items = [
            item for item in source_items if item.overlaps(region.start, region.end)
        ]

        if not is_relative:
            continue

        if not tutsan_items:
            non_tutsan_relative_sources.append(source_file)
            continue

        basename = Path(source_file).name
        root_path = project_root / source_file
        if not _is_relative_path_inside_root(project_root, root_path):
            stop_reasons.append(f"relative source escapes project root: {source_file}")
        audio_target_path = audio_dir / basename
        renamed_basename = target_name(basename)
        metadata = stat_file(root_path)
        candidate = Candidate(
            source_file=source_file,
            basename=basename,
            root_path=root_path,
            audio_target_path=audio_target_path,
            renamed_basename=renamed_basename,
            root_renamed_path=project_root / renamed_basename,
            item_count=len(source_items),
            tutsan_item_count=len(tutsan_items),
            metadata=metadata,
        )
        candidates.append(candidate)

        if not metadata.exists:
            stop_reasons.append(f"missing source: {source_file}")

        basename_sources = relative_sources_by_basename.get(basename, [])
        if len(basename_sources) > 1:
            joined = ", ".join(sorted(basename_sources))
            stop_reasons.append(f"ambiguous relative basename: {basename} ({joined})")

        root_meta = metadata
        audio_meta = stat_file(audio_target_path)
        if root_meta.exists and audio_meta.exists:
            duplicates.setdefault(
                basename,
                DuplicateInfo(
                    basename=basename,
                    root_path=root_path,
                    audio_path=audio_target_path,
                    root_exists=root_meta.exists,
                    audio_exists=audio_meta.exists,
                    root_size=root_meta.size,
                    audio_size=audio_meta.size,
                    root_created=root_meta.created,
                    audio_created=audio_meta.created,
                    root_modified=root_meta.modified,
                    audio_modified=audio_meta.modified,
                ),
            )

    return Audit(
        region=region,
        candidates=candidates,
        duplicates=duplicates,
        non_tutsan_relative_sources=non_tutsan_relative_sources,
        stop_reasons=stop_reasons,
    )


def _is_relative_path_inside_root(project_root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(project_root.resolve(strict=False))
    except ValueError:
        return False
    return True


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


def _group_items_by_source(items: list[ItemSource]) -> dict[str, list[ItemSource]]:
    grouped: dict[str, list[ItemSource]] = {}
    for item in items:
        grouped.setdefault(item.source_file, []).append(item)
    return grouped


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
