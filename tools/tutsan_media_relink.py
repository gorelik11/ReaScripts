from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
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
class SampleEditItem:
    guid: str
    name: str | None
    position: float
    length: float
    source_files: tuple[str, ...]
    payload_hash: str
    payload_length: int
    sampleedit_count: int
    spl_count: int


@dataclass(frozen=True)
class SampleEditComparison:
    before_count: int
    after_count: int
    preserved_count: int
    changed_count: int
    missing_guids: list[str]
    new_guids: list[str]
    changed_guids: list[str]
    path_changed_guids: list[str]


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
    sample_edit_comparison: SampleEditComparison | None = None


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
    items: list[ItemSource] = []
    for block in _item_blocks(text):
        item = _parse_item_block(block)
        if item is not None:
            items.append(item)
    return items


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
    sample_edit_reference: Path | None = None,
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

        if not tutsan_items:
            if is_relative:
                non_tutsan_relative_sources.append(source_file)
            continue

        if not is_relative and not _is_audio_shadow_source(
            source_file, project_root, audio_dir
        ):
            continue

        basename = Path(source_file).name
        root_path = project_root / (source_file if is_relative else basename)
        if is_relative and not _is_relative_path_inside_root(project_root, root_path):
            stop_reasons.append(f"relative source escapes project root: {source_file}")
        renamed_basename = target_name(basename)
        audio_original_path = audio_dir / basename
        root_renamed_path = project_root / renamed_basename
        audio_target_path = audio_dir / renamed_basename
        metadata = stat_file(root_path)
        candidate = Candidate(
            source_file=source_file,
            basename=basename,
            root_path=root_path,
            audio_target_path=audio_target_path,
            renamed_basename=renamed_basename,
            root_renamed_path=root_renamed_path,
            item_count=len(source_items),
            tutsan_item_count=len(tutsan_items),
            metadata=metadata,
        )
        candidates.append(candidate)

        already_renamed = not metadata.exists and root_renamed_path.exists()
        if not metadata.exists and not already_renamed:
            stop_reasons.append(f"missing source: {source_file}")
        if is_relative and len(tutsan_items) != len(source_items):
            stop_reasons.append(
                f"source used inside and outside Tutsan: {source_file} "
                f"({len(tutsan_items)}/{len(source_items)} items in Tutsan)"
            )
        if root_renamed_path.exists() and not already_renamed:
            stop_reasons.append(f"target exists in project root: {renamed_basename}")
        if audio_target_path.exists() and not already_renamed:
            stop_reasons.append(f"target exists in audio dir: {renamed_basename}")

        basename_sources = relative_sources_by_basename.get(basename, [])
        if len(basename_sources) > 1:
            joined = ", ".join(sorted(basename_sources))
            stop_reasons.append(f"ambiguous relative basename: {basename} ({joined})")

        root_meta = metadata
        audio_meta = stat_file(audio_original_path)
        if root_meta.exists and audio_meta.exists:
            duplicates.setdefault(
                basename,
                DuplicateInfo(
                    basename=basename,
                    root_path=root_path,
                    audio_path=audio_original_path,
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

    sample_edit_comparison = None
    if sample_edit_reference is not None:
        reference_text = sample_edit_reference.read_text(
            encoding="utf-8", errors="replace"
        )
        sample_edit_comparison = compare_sample_edits(
            reference_text,
            text,
            region_id=region_id,
            region_name=region_name,
        )
        stop_reasons.extend(_sample_edit_stop_reasons(sample_edit_comparison))

    return Audit(
        region=region,
        candidates=candidates,
        duplicates=duplicates,
        non_tutsan_relative_sources=non_tutsan_relative_sources,
        stop_reasons=stop_reasons,
        sample_edit_comparison=sample_edit_comparison,
    )


def compare_sample_edits(
    before_text: str,
    after_text: str,
    region_id: int,
    region_name: str,
) -> SampleEditComparison:
    before = sample_edit_items_by_guid(before_text, region_id, region_name)
    after = sample_edit_items_by_guid(after_text, region_id, region_name)
    before_guids = set(before)
    after_guids = set(after)
    shared_guids = sorted(before_guids & after_guids)
    changed_guids = [
        guid
        for guid in shared_guids
        if before[guid].payload_hash != after[guid].payload_hash
        or before[guid].payload_length != after[guid].payload_length
    ]
    path_changed_guids = [
        guid
        for guid in shared_guids
        if before[guid].source_files != after[guid].source_files
    ]

    return SampleEditComparison(
        before_count=len(before),
        after_count=len(after),
        preserved_count=len(shared_guids) - len(changed_guids),
        changed_count=len(changed_guids),
        missing_guids=sorted(before_guids - after_guids),
        new_guids=sorted(after_guids - before_guids),
        changed_guids=changed_guids,
        path_changed_guids=path_changed_guids,
    )


def sample_edit_items_by_guid(
    text: str,
    region_id: int,
    region_name: str,
) -> dict[str, SampleEditItem]:
    region = find_region(text, region_id=region_id, region_name=region_name)
    items: dict[str, SampleEditItem] = {}
    for lines in _item_blocks(text):
        position = _required_float(lines, "POSITION")
        length = _required_float(lines, "LENGTH")
        if not (position < region.end and position + length > region.start):
            continue

        payload = _sample_edit_payload(lines)
        if not payload:
            continue

        guid = _required_value(lines, "IGUID")
        payload_text = "\n".join(payload)
        items[guid] = SampleEditItem(
            guid=guid,
            name=_optional_value(lines, "NAME"),
            position=position,
            length=length,
            source_files=tuple(_all_values(lines, "FILE")),
            payload_hash=hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
            payload_length=len(payload_text),
            sampleedit_count=sum(
                1 for line in payload if line.strip().startswith("SAMPLEEDITS ")
            ),
            spl_count=sum(1 for line in payload if re.match(r"^\s*SPL\s+", line)),
        )
    return items


def apply_rename(audit: Audit) -> dict[str, object]:
    if audit.stop_reasons:
        raise RuntimeError("stop reasons present; refusing rename")

    renamed: list[tuple[str, str]] = []
    skipped_existing: list[str] = []
    for candidate in audit.candidates:
        if not candidate.root_path.exists() and candidate.root_renamed_path.exists():
            skipped_existing.append(str(candidate.root_renamed_path))
            continue
        if candidate.root_renamed_path.exists():
            raise RuntimeError(f"rename target exists: {candidate.root_renamed_path}")
        if not candidate.root_path.exists():
            raise RuntimeError(f"rename source missing: {candidate.root_path}")

        candidate.root_path.rename(candidate.root_renamed_path)
        renamed.append((str(candidate.root_path), str(candidate.root_renamed_path)))

    return {"renamed": renamed, "skipped_existing": skipped_existing}


def verify_copied_targets(audit: Audit) -> list[str]:
    missing: list[str] = []
    for candidate in audit.candidates:
        if not candidate.audio_target_path.exists():
            missing.append(f"missing copied target: {candidate.renamed_basename}")
    return missing


def relink_rpp_text(
    text: str,
    mapping: dict[str, object],
    region_id: int,
    region_name: str,
) -> tuple[str, int]:
    region = find_region(text, region_id=region_id, region_name=region_name)
    replacements = _mapping_replacements(mapping)
    output: list[str] = []
    cursor = 0
    changed = 0

    for start, end, lines in _item_block_spans(text):
        output.append(text[cursor:start])
        position = _required_float(lines, "POSITION")
        length = _required_float(lines, "LENGTH")
        if position < region.end and position + length > region.start:
            new_lines, item_changed = _replace_item_file_lines(lines, replacements)
            changed += item_changed
            replacement_text = "\n".join(new_lines)
            if text[start:end].endswith("\n"):
                replacement_text += "\n"
            output.append(replacement_text)
        else:
            output.append(text[start:end])
        cursor = end

    output.append(text[cursor:])
    return "".join(output), changed


def verify_project_relinked(
    rpp_path: Path,
    mapping: dict[str, object],
    region_id: int,
    region_name: str,
) -> list[str]:
    text = rpp_path.read_text(encoding="utf-8", errors="replace")
    region = find_region(text, region_id=region_id, region_name=region_name)
    replacements = _mapping_replacements(mapping)
    errors: list[str] = []

    for new_path in replacements.values():
        if not Path(new_path).exists():
            errors.append(f"missing relinked target: {new_path}")

    for lines in _item_blocks(text):
        position = _required_float(lines, "POSITION")
        length = _required_float(lines, "LENGTH")
        if not (position < region.end and position + length > region.start):
            continue
        for source in _all_values(lines, "FILE"):
            basename = Path(source).name
            if basename in replacements:
                errors.append(f"old source remains in Tutsan: {source}")
            elif target_name(basename) in replacements:
                errors.append(f"old source remains in Tutsan: {source}")
            if basename.endswith(" - R7 Tutsan.wav") and not Path(source).exists():
                errors.append(f"relinked target missing on disk: {source}")

    return errors


def _is_relative_path_inside_root(project_root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(project_root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _is_audio_shadow_source(
    source_file: str,
    project_root: Path,
    audio_dir: Path,
) -> bool:
    source_path = Path(source_file)
    try:
        source_path.resolve(strict=False).relative_to(audio_dir.resolve(strict=False))
    except ValueError:
        return False
    return (project_root / source_path.name).exists() or (
        project_root / target_name(source_path.name)
    ).exists()


def render_markdown_report(audit: Audit) -> str:
    lines = [
        "# Tutsan Media Relink Audit",
        "",
        "## Region",
        "",
        f"- Name: {audit.region.name}",
        f"- Start: {audit.region.start}",
        f"- End: {audit.region.end}",
        "",
        "## Stop Reasons",
        "",
    ]
    if audit.stop_reasons:
        lines.extend(f"- {reason}" for reason in audit.stop_reasons)
    else:
        lines.append("- None")

    lines.extend(["", "## Tutsan Candidates", ""])
    if audit.candidates:
        lines.append(
            "| Source | Renamed | Root path | Audio target | Items | Tutsan items | Size |"
        )
        lines.append("| --- | --- | --- | --- | ---: | ---: | ---: |")
        for candidate in audit.candidates:
            size = "" if candidate.metadata.size is None else str(candidate.metadata.size)
            lines.append(
                "| "
                + " | ".join(
                    [
                        candidate.source_file,
                        candidate.renamed_basename,
                        str(candidate.root_path),
                        str(candidate.audio_target_path),
                        str(candidate.item_count),
                        str(candidate.tutsan_item_count),
                        size,
                    ]
                )
                + " |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Basename Duplicates", ""])
    if audit.duplicates:
        lines.append("| Basename | Root size | Audio size | Root path | Audio path |")
        lines.append("| --- | ---: | ---: | --- | --- |")
        for duplicate in audit.duplicates.values():
            lines.append(
                "| "
                + " | ".join(
                    [
                        duplicate.basename,
                        _fmt_optional(duplicate.root_size),
                        _fmt_optional(duplicate.audio_size),
                        str(duplicate.root_path),
                        str(duplicate.audio_path),
                    ]
                )
                + " |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Non-Tutsan Relative Sources", ""])
    if audit.non_tutsan_relative_sources:
        for source in sorted(audit.non_tutsan_relative_sources):
            lines.append(f"- {source}")
    else:
        lines.append("- None")

    lines.extend(["", "## Sample Edit Preservation", ""])
    if audit.sample_edit_comparison is None:
        lines.append("- Not checked")
    else:
        comparison = audit.sample_edit_comparison
        lines.extend(
            [
                f"- Before items: {comparison.before_count}",
                f"- After items: {comparison.after_count}",
                f"- Preserved payloads: {comparison.preserved_count}",
                f"- Changed payloads: {comparison.changed_count}",
                f"- Missing GUIDs: {len(comparison.missing_guids)}",
                f"- New GUIDs: {len(comparison.new_guids)}",
                f"- Path-changed preserved items: {len(comparison.path_changed_guids)}",
            ]
        )

    return "\n".join(lines) + "\n"


def render_relink_map(audit: Audit) -> dict[str, object]:
    return {
        "region": {
            "name": audit.region.name,
            "start": audit.region.start,
            "end": audit.region.end,
        },
        "files": [
            {
                "old_source_file": candidate.source_file,
                "old_root_path": str(candidate.root_path),
                "new_basename": candidate.renamed_basename,
                "renamed_root_path": str(candidate.root_renamed_path),
                "new_audio_path": str(candidate.audio_target_path),
                "item_count": candidate.item_count,
                "tutsan_item_count": candidate.tutsan_item_count,
            }
            for candidate in audit.candidates
        ],
    }


def audit_to_dict(audit: Audit) -> dict[str, object]:
    return {
        "region": {
            "name": audit.region.name,
            "start": audit.region.start,
            "end": audit.region.end,
        },
        "stop_reasons": audit.stop_reasons,
        "candidates": [
            {
                "source_file": candidate.source_file,
                "basename": candidate.basename,
                "root_path": str(candidate.root_path),
                "audio_target_path": str(candidate.audio_target_path),
                "renamed_basename": candidate.renamed_basename,
                "root_renamed_path": str(candidate.root_renamed_path),
                "item_count": candidate.item_count,
                "tutsan_item_count": candidate.tutsan_item_count,
                "metadata": _file_meta_to_dict(candidate.metadata),
            }
            for candidate in audit.candidates
        ],
        "duplicates": {
            basename: {
                "basename": duplicate.basename,
                "root_path": str(duplicate.root_path),
                "audio_path": str(duplicate.audio_path),
                "root_exists": duplicate.root_exists,
                "audio_exists": duplicate.audio_exists,
                "root_size": duplicate.root_size,
                "audio_size": duplicate.audio_size,
                "root_created": duplicate.root_created,
                "audio_created": duplicate.audio_created,
                "root_modified": duplicate.root_modified,
                "audio_modified": duplicate.audio_modified,
            }
            for basename, duplicate in audit.duplicates.items()
        },
        "non_tutsan_relative_sources": audit.non_tutsan_relative_sources,
        "sample_edit_comparison": (
            None
            if audit.sample_edit_comparison is None
            else _sample_edit_comparison_to_dict(audit.sample_edit_comparison)
        ),
    }


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_reports(audit: Audit, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "tutsan-media-audit.json", audit_to_dict(audit))
    (out_dir / "tutsan-media-audit.md").write_text(
        render_markdown_report(audit), encoding="utf-8"
    )
    write_json(out_dir / "tutsan-relink-map.json", render_relink_map(audit))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Tutsan media relink safety.")
    parser.add_argument("--rpp", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--audio-dir", required=True, type=Path)
    parser.add_argument("--region-id", default=7, type=int)
    parser.add_argument("--region-name", default="Tutsan")
    parser.add_argument("--out-dir", default=Path(".codex_tmp"), type=Path)
    parser.add_argument("--sample-edit-reference", type=Path)
    parser.add_argument("--apply-rename", action="store_true")
    parser.add_argument("--verify-copy", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    audit = build_audit(
        rpp_path=args.rpp,
        project_root=args.project_root,
        audio_dir=args.audio_dir,
        region_id=args.region_id,
        region_name=args.region_name,
        sample_edit_reference=args.sample_edit_reference,
    )

    action_result: dict[str, object] | None = None
    copy_errors: list[str] = []

    if args.apply_rename:
        action_result = apply_rename(audit)
    if args.verify_copy:
        copy_errors = verify_copied_targets(audit)
        audit.stop_reasons[:] = [
            reason
            for reason in audit.stop_reasons
            if reason.startswith("sample edit ")
        ]
        audit.stop_reasons.extend(copy_errors)

    write_reports(audit, args.out_dir)
    if action_result is not None:
        write_json(args.out_dir / "tutsan-rename-result.json", action_result)
    return 2 if audit.stop_reasons else 0


def _file_meta_to_dict(meta: FileMeta) -> dict[str, object]:
    return {
        "path": str(meta.path),
        "exists": meta.exists,
        "size": meta.size,
        "created": meta.created,
        "modified": meta.modified,
    }


def _sample_edit_comparison_to_dict(
    comparison: SampleEditComparison,
) -> dict[str, object]:
    return {
        "before_count": comparison.before_count,
        "after_count": comparison.after_count,
        "preserved_count": comparison.preserved_count,
        "changed_count": comparison.changed_count,
        "missing_guids": comparison.missing_guids,
        "new_guids": comparison.new_guids,
        "changed_guids": comparison.changed_guids,
        "path_changed_guids": comparison.path_changed_guids,
    }


def _sample_edit_stop_reasons(
    comparison: SampleEditComparison,
) -> list[str]:
    reasons: list[str] = []
    if comparison.missing_guids:
        reasons.append(f"sample edit items missing: {len(comparison.missing_guids)}")
    if comparison.changed_guids:
        reasons.append(f"sample edit payloads changed: {len(comparison.changed_guids)}")
    return reasons


def _fmt_optional(value: object) -> str:
    return "" if value is None else str(value)


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


def _item_block_spans(text: str) -> list[tuple[int, int, list[str]]]:
    spans: list[tuple[int, int, list[str]]] = []
    lines = text.splitlines(keepends=True)
    current: list[str] | None = None
    start_offset = 0
    offset = 0
    depth = 0

    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if current is None:
            if stripped.startswith("<ITEM"):
                current = [line]
                start_offset = offset
                depth = 1
            offset += len(raw_line)
            continue

        current.append(line)
        if stripped.startswith("<"):
            depth += 1
        elif stripped == ">":
            depth -= 1
            if depth == 0:
                spans.append((start_offset, offset + len(raw_line), current))
                current = None
        offset += len(raw_line)

    return spans


def _parse_item_block(lines: list[str]) -> ItemSource | None:
    position = _required_float(lines, "POSITION")
    length = _required_float(lines, "LENGTH")
    name = _optional_value(lines, "NAME")
    source_file = _optional_value(lines, "FILE")
    if source_file is None:
        return None

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


def _all_values(lines: list[str], key: str) -> list[str]:
    values: list[str] = []
    prefix = f"{key} "
    for line in lines:
        stripped = line.strip()
        if stripped == key:
            values.append("")
        elif stripped.startswith(prefix):
            values.append(_parse_value(stripped[len(prefix) :]))
    return values


def _sample_edit_payload(lines: list[str]) -> list[str]:
    payload: list[str] = []
    collecting = False
    sample_depth = 0

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("SAMPLEEDITS "):
            collecting = True
            sample_depth = 0
            payload.append(line)
            continue

        if not collecting:
            continue

        if stripped.startswith("<SPLS"):
            sample_depth += 1
            payload.append(line)
            continue

        if stripped == ">" and sample_depth > 0:
            sample_depth -= 1
            payload.append(line)
            if sample_depth == 0:
                collecting = False
            continue

        payload.append(line)

    return payload


def _mapping_replacements(mapping: dict[str, object]) -> dict[str, str]:
    replacements: dict[str, str] = {}
    for entry in mapping.get("files", []):
        if not isinstance(entry, dict):
            continue
        old_source = str(entry["old_source_file"])
        new_audio_path = str(entry["new_audio_path"])
        replacements[Path(old_source).name] = new_audio_path
    return replacements


def _replace_item_file_lines(
    lines: list[str],
    replacements: dict[str, str],
) -> tuple[list[str], int]:
    changed = 0
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("FILE "):
            new_lines.append(line)
            continue

        source = _parse_value(stripped[len("FILE ") :])
        replacement = replacements.get(Path(source).name)
        if replacement is None:
            new_lines.append(line)
            continue

        indent = line[: len(line) - len(line.lstrip())]
        new_lines.append(f'{indent}FILE "{replacement}"')
        changed += 1
    return new_lines, changed


def _parse_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw.startswith('"'):
        parts = shlex.split(raw)
        return parts[0] if parts else ""
    return raw


if __name__ == "__main__":
    raise SystemExit(main())
