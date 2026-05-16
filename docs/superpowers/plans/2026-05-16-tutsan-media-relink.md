# Tutsan Media Relink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a safe audit, rename, copy-verification, and REAPER relink workflow for Tutsan-region media that was recorded into `/Volumes/Project 1/11`.

**Architecture:** Create one focused Python CLI for `.RPP` parsing, metadata audit, dry-run reporting, root-folder rename, and post-copy verification. Keep REAPER relink as a separate MCP-driven phase that consumes the CLI mapping and changes only items overlapping region `7 / Tutsan`.

**Tech Stack:** Python 3 standard library, pytest for unit tests, REAPER MCP tools for final relink, filesystem metadata via `pathlib`/`os.stat`.

---

## Files

- Create: `tools/tutsan_media_relink.py`
  - Parses the project file.
  - Finds region `7 / Tutsan`.
  - Aggregates media source usage.
  - Produces compact audit JSON and Markdown reports.
  - Performs guarded root-folder rename only when `--apply-rename` is passed.
  - Verifies that renamed files exist in `/Volumes/Project 1/1/Audio` before REAPER relink.
- Create: `tests/test_tutsan_media_relink.py`
  - Uses temporary fixture directories and synthetic `.RPP` text.
  - Tests region detection, item/source parsing, Tutsan filtering, duplicate detection, rename mapping, and stop conditions.
- Create output at runtime, not committed: `.codex_tmp/tutsan-media-audit.json`
- Create output at runtime, not committed: `.codex_tmp/tutsan-media-audit.md`
- Create output at runtime, not committed: `.codex_tmp/tutsan-relink-map.json`

## Task 1: Parser And Region Detection

**Files:**
- Create: `tools/tutsan_media_relink.py`
- Create: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for region and item parsing**

Add this test file:

```python
from pathlib import Path

from tools.tutsan_media_relink import find_region, parse_items


SYNTHETIC_RPP = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  RECORD_PATH "" ""
  MARKER 7 100.0 Tutsan 1 0 1 B {REGION-GUID} 0 1
  MARKER 7 130.0 "" 1
  <TRACK
    NAME "Vocal"
    <ITEM
      POSITION 110.0
      LENGTH 5.0
      NAME "Aniel Vocal 2-11.wav"
      SOFFS 0
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
    >
    <ITEM
      POSITION 200.0
      LENGTH 3.0
      NAME "Other.wav"
      <SOURCE WAVE
        FILE "/Volumes/Project 1/1/Audio/Other.wav"
      >
    >
  >
>
"""


def test_find_region_uses_matching_start_and_following_end_marker():
    region = find_region(SYNTHETIC_RPP, region_id=7, region_name="Tutsan")
    assert region.start == 100.0
    assert region.end == 130.0
    assert region.name == "Tutsan"


def test_parse_items_extracts_position_length_name_and_file():
    items = parse_items(SYNTHETIC_RPP)
    assert len(items) == 2
    assert items[0].position == 110.0
    assert items[0].length == 5.0
    assert items[0].name == "Aniel Vocal 2-11.wav"
    assert items[0].source_file == "Aniel Vocal 2-11.wav"
    assert items[0].is_relative is True
    assert items[1].source_file == "/Volumes/Project 1/1/Audio/Other.wav"
    assert items[1].is_relative is False
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: import failure because `tools/tutsan_media_relink.py` does not exist yet.

- [ ] **Step 3: Implement minimal parser**

Create `tools/tutsan_media_relink.py` with dataclasses `Region` and `ItemSource`, plus `find_region()` and `parse_items()`. The parser should be text-based and block-oriented. It does not need to understand every `.RPP` feature; it only needs marker lines, item blocks, and source `FILE` lines.

Implementation requirements:

- `find_region(text, region_id, region_name)` finds `MARKER <id> <start> <name> 1 ...` and the following `MARKER <same id> <end> "" 1`.
- `parse_items(text)` returns all `<ITEM ... >` blocks with numeric `POSITION`, numeric `LENGTH`, optional `NAME`, and source `FILE`.
- Quoted and unquoted `NAME` lines must both work.
- Quoted and unquoted `FILE` lines must both work.
- `ItemSource.end` should be `position + length`.
- `ItemSource.overlaps(start, end)` should return `position < end and item_end > start`.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: 2 passing tests.

- [ ] **Step 5: Commit parser**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py
git commit -m "feat: parse Tutsan media sources"
```

## Task 2: Audit Model And Duplicate Detection

**Files:**
- Modify: `tools/tutsan_media_relink.py`
- Modify: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for candidate and duplicate detection**

Append tests:

```python
from tools.tutsan_media_relink import build_audit


def write_file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_build_audit_reports_tutsan_relative_candidate_and_duplicate(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11.wav", b"old-other-song")

    audit = build_audit(
        rpp_path=rpp_path,
        project_root=project_root,
        audio_dir=audio_dir,
        region_id=7,
        region_name="Tutsan",
    )

    assert [c.basename for c in audit.candidates] == ["Aniel Vocal 2-11.wav"]
    duplicate = audit.duplicates["Aniel Vocal 2-11.wav"]
    assert duplicate.root_exists is True
    assert duplicate.audio_exists is True
    assert duplicate.root_size == len(b"new-tutsan")
    assert duplicate.audio_size == len(b"old-other-song")
    assert audit.stop_reasons == []


def test_build_audit_stops_when_source_file_is_missing(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)

    audit = build_audit(
        rpp_path=rpp_path,
        project_root=project_root,
        audio_dir=audio_dir,
        region_id=7,
        region_name="Tutsan",
    )

    assert "missing source: Aniel Vocal 2-11.wav" in audit.stop_reasons
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: failure because `build_audit` is not implemented.

- [ ] **Step 3: Implement audit dataclasses and metadata collection**

Add:

- `FileMeta(path, exists, size, created, modified)`
- `DuplicateInfo(basename, root_path, audio_path, root_exists, audio_exists, root_size, audio_size, root_created, audio_created, root_modified, audio_modified)`
- `Candidate(source_file, basename, root_path, audio_target_path, renamed_basename, root_renamed_path, item_count, tutsan_item_count, metadata)`
- `Audit(region, candidates, duplicates, non_tutsan_relative_sources, stop_reasons)`

Implement:

- `stat_file(path)` using `path.exists()`, `path.stat().st_size`, `st_birthtime` when available, and `st_mtime`.
- `target_name(basename)` inserting ` - R7 Tutsan` before the extension.
- `build_audit(...)` that groups sources by exact source string, resolves relative sources against `project_root`, and selects candidates only when at least one using item overlaps the region.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit audit model**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py
git commit -m "feat: audit Tutsan media duplicates"
```

## Task 3: Reports And Dry-Run CLI

**Files:**
- Modify: `tools/tutsan_media_relink.py`
- Modify: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for report rendering**

Append tests:

```python
from tools.tutsan_media_relink import render_markdown_report, render_relink_map


def test_render_markdown_report_includes_candidate_and_stop_reasons(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"existing-target")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    text = render_markdown_report(audit)

    assert "Aniel Vocal 2-11.wav" in text
    assert "Aniel Vocal 2-11 - R7 Tutsan.wav" in text
    assert "target exists in audio dir" in text


def test_render_relink_map_contains_old_relative_and_new_audio_path(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    mapping = render_relink_map(audit)

    assert mapping["region"]["name"] == "Tutsan"
    assert mapping["files"][0]["old_source_file"] == "Aniel Vocal 2-11.wav"
    assert mapping["files"][0]["new_basename"] == "Aniel Vocal 2-11 - R7 Tutsan.wav"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: failure because report functions are missing.

- [ ] **Step 3: Implement report functions and CLI**

Add:

- `render_markdown_report(audit) -> str`
- `render_relink_map(audit) -> dict`
- `write_json(path, data)`
- CLI with arguments:
  - `--rpp`
  - `--project-root`
  - `--audio-dir`
  - `--region-id`, default `7`
  - `--region-name`, default `Tutsan`
  - `--out-dir`, default `.codex_tmp`
  - `--dry-run`, default action

Dry-run command should write:

```text
.codex_tmp/tutsan-media-audit.json
.codex_tmp/tutsan-media-audit.md
.codex_tmp/tutsan-relink-map.json
```

If `audit.stop_reasons` is non-empty, CLI exits `2`. If no stop reasons, exits `0`.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Run real dry-run audit**

Run:

```bash
python3 tools/tutsan_media_relink.py \
  --rpp "/Volumes/Project 1/11/Kolot StudioTorun_052logic click_022.RPP" \
  --project-root "/Volumes/Project 1/11" \
  --audio-dir "/Volumes/Project 1/1/Audio" \
  --out-dir ".codex_tmp" \
  --dry-run
```

Expected:

- Report files are created.
- Exit `0` only if no stop conditions are present.
- Exit `2` if conflicts must be reviewed before rename.

- [ ] **Step 6: Commit report CLI**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py .codex_tmp/.gitkeep
git commit -m "feat: report Tutsan media relink audit"
```

If `.codex_tmp` is intentionally untracked, omit `.codex_tmp/.gitkeep` from the commit.

## Task 4: Guarded Rename

**Files:**
- Modify: `tools/tutsan_media_relink.py`
- Modify: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for rename apply**

Append tests:

```python
from tools.tutsan_media_relink import apply_rename


def test_apply_rename_renames_only_when_no_stop_reasons(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    old_path = write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    result = apply_rename(audit)

    new_path = project_root / "Aniel Vocal 2-11 - R7 Tutsan.wav"
    assert result == {"renamed": [(str(old_path), str(new_path))]}
    assert not old_path.exists()
    assert new_path.read_bytes() == b"new-tutsan"


def test_apply_rename_refuses_when_stop_reasons_exist(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    try:
        apply_rename(audit)
    except RuntimeError as exc:
        assert "stop reasons present" in str(exc)
    else:
        raise AssertionError("apply_rename should refuse unsafe audit")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: failure because `apply_rename` is missing.

- [ ] **Step 3: Implement guarded rename**

Add `apply_rename(audit)`:

- Raise `RuntimeError("stop reasons present; refusing rename")` if `audit.stop_reasons` is not empty.
- For each candidate, call `Path.rename()` from root original path to root renamed path.
- Never overwrite: check target does not exist immediately before rename.
- Return `{"renamed": [(old, new), ...]}`.

Add CLI flag:

```text
--apply-rename
```

When set:

- Build audit.
- Refuse if stop reasons exist.
- Rename root files.
- Write updated reports after rename.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit guarded rename**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py
git commit -m "feat: safely rename Tutsan root media"
```

## Task 5: Manual Checkpoint And Copy Verification

**Files:**
- Modify: `tools/tutsan_media_relink.py`
- Modify: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for copy verification**

Append tests:

```python
from tools.tutsan_media_relink import verify_copied_targets


def test_verify_copied_targets_passes_when_audio_targets_exist(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    assert verify_copied_targets(audit) == []


def test_verify_copied_targets_reports_missing_audio_target(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    assert verify_copied_targets(audit) == [
        "missing copied target: Aniel Vocal 2-11 - R7 Tutsan.wav"
    ]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: failure because `verify_copied_targets` is missing.

- [ ] **Step 3: Implement copy verification**

Add `verify_copied_targets(audit)`:

- For each candidate, ensure `/Volumes/Project 1/1/Audio/<renamed_basename>` exists.
- Return a list of missing target messages.
- Add CLI flag `--verify-copy` that exits `0` if all targets exist and exits `2` otherwise.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Real checkpoint**

Run dry-run again. If clean, ask the user to approve actual rename:

```bash
python3 tools/tutsan_media_relink.py \
  --rpp "/Volumes/Project 1/11/Kolot StudioTorun_052logic click_022.RPP" \
  --project-root "/Volumes/Project 1/11" \
  --audio-dir "/Volumes/Project 1/1/Audio" \
  --out-dir ".codex_tmp" \
  --dry-run
```

After user approval, run:

```bash
python3 tools/tutsan_media_relink.py \
  --rpp "/Volumes/Project 1/11/Kolot StudioTorun_052logic click_022.RPP" \
  --project-root "/Volumes/Project 1/11" \
  --audio-dir "/Volumes/Project 1/1/Audio" \
  --out-dir ".codex_tmp" \
  --apply-rename
```

Then stop and wait while the user manually copies renamed files to `/Volumes/Project 1/1/Audio`.

After user confirms copy, run:

```bash
python3 tools/tutsan_media_relink.py \
  --rpp "/Volumes/Project 1/11/Kolot StudioTorun_052logic click_022.RPP" \
  --project-root "/Volumes/Project 1/11" \
  --audio-dir "/Volumes/Project 1/1/Audio" \
  --out-dir ".codex_tmp" \
  --verify-copy
```

Expected: exit `0`.

- [ ] **Step 6: Commit copy verification**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py
git commit -m "feat: verify copied Tutsan media"
```

## Task 6: REAPER Relink Via MCP

**Files:**
- Modify: no repository files required unless a helper Lua script is needed.
- Runtime input: `.codex_tmp/tutsan-relink-map.json`

- [ ] **Step 1: Confirm active REAPER project**

Use MCP:

```text
mcp__total_reaper__.get_project_tab_name
mcp__total_reaper__.get_project_path
```

Expected:

- Project tab is the expected `Kolot StudioTorun_052logic click_022` project or the user explicitly confirms the active project.
- Project path is `/Volumes/Project 1/11`.

- [ ] **Step 2: Check unsaved state with user**

If REAPER title says modified or MCP indicates unsaved project state, ask the user to confirm proceeding. Do not relink without confirmation.

- [ ] **Step 3: Use MCP to replace sources only for Tutsan-overlapping items**

Preferred implementation:

- Use a Lua helper executed through REAPER MCP if available.
- The helper reads `.codex_tmp/tutsan-relink-map.json`.
- It enumerates all media items.
- For each item:
  - Get item position and length.
  - Skip unless it overlaps `11813.301324594368` to `12104.358446433422`.
  - Get active take source filename.
  - If basename matches an `old_source_file` in the map, create a new PCM source from `/Volumes/Project 1/1/Audio/<new_basename>` and assign it to the take.
  - Preserve item position, length, start offset, playback rate, fades, item GUID, and take FX.

Fallback implementation:

- If MCP lacks a direct source replacement tool, modify a copied `.RPP` text file by replacing only `FILE "old.wav"` lines inside item blocks that overlap Tutsan, then open/save that project in REAPER after user approval.
- Do not use fallback on the original `.RPP`; only use it on a new versioned copy.

- [ ] **Step 4: Save as new project version**

Save as:

```text
/Volumes/Project 1/11/Kolot StudioTorun_052logic click_023_tutsan_relinked.RPP
```

Expected: original `_022.RPP` remains available.

## Task 7: Verification After Relink

**Files:**
- Modify: `tools/tutsan_media_relink.py`
- Modify: `tests/test_tutsan_media_relink.py`

- [ ] **Step 1: Write failing tests for post-relink project verification**

Append tests:

```python
from tools.tutsan_media_relink import verify_project_relinked


RELINKED_RPP = SYNTHETIC_RPP.replace(
    'FILE "Aniel Vocal 2-11.wav"',
    'FILE "/tmp/audio/Aniel Vocal 2-11 - R7 Tutsan.wav"',
)


def test_verify_project_relinked_passes_when_tutsan_items_use_new_absolute_path(tmp_path):
    audio_dir = tmp_path / "audio"
    write_file(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")
    rpp_path = tmp_path / "Project_relinked.RPP"
    rpp_path.write_text(RELINKED_RPP.replace("/tmp/audio", str(audio_dir)))

    errors = verify_project_relinked(
        rpp_path=rpp_path,
        audio_dir=audio_dir,
        region_id=7,
        region_name="Tutsan",
        suffix=" - R7 Tutsan",
    )

    assert errors == []
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: failure because `verify_project_relinked` is missing.

- [ ] **Step 3: Implement `verify_project_relinked` and CLI flag**

Add:

- `verify_project_relinked(rpp_path, audio_dir, region_id, region_name, suffix)`.
- CLI flag `--verify-relinked-rpp PATH`.

Checks:

- Any Tutsan-overlapping item whose basename contains `R7 Tutsan` must point to an existing file under `audio_dir`.
- No Tutsan candidate source should still point to the old relative filename if it was present in `.codex_tmp/tutsan-relink-map.json`.
- Non-Tutsan items are not treated as errors.

- [ ] **Step 4: Run tests and verify pass**

Run:

```bash
pytest tests/test_tutsan_media_relink.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Verify real saved project**

Run:

```bash
python3 tools/tutsan_media_relink.py \
  --verify-relinked-rpp "/Volumes/Project 1/11/Kolot StudioTorun_052logic click_023_tutsan_relinked.RPP" \
  --audio-dir "/Volumes/Project 1/1/Audio" \
  --region-id 7 \
  --region-name Tutsan \
  --out-dir ".codex_tmp"
```

Expected: exit `0`.

- [ ] **Step 6: Commit final verifier**

Run:

```bash
git add tools/tutsan_media_relink.py tests/test_tutsan_media_relink.py
git commit -m "feat: verify Tutsan relinked project"
```

## Final Manual Checklist

- [ ] User has a full external backup.
- [ ] Dry-run audit reviewed by user.
- [ ] Rename applied only after user approval.
- [ ] User manually copied renamed files into `/Volumes/Project 1/1/Audio`.
- [ ] Copy verification passed.
- [ ] REAPER relink touched only region `7 / Tutsan`.
- [ ] Project saved as `_023_tutsan_relinked.RPP`.
- [ ] Post-relink verification passed.
- [ ] User opened the saved project and confirmed no missing media prompt.
