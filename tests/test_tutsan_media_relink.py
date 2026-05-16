from pathlib import Path

from tools.tutsan_media_relink import (
    apply_rename,
    build_audit,
    compare_sample_edits,
    find_region,
    parse_items,
    relink_rpp_text,
    render_markdown_report,
    render_relink_map,
    verify_project_relinked,
    verify_copied_targets,
)


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
    assert items[0].end == 115.0
    assert items[0].overlaps(100.0, 130.0) is True
    assert items[0].overlaps(120.0, 130.0) is False
    assert items[1].source_file == "/Volumes/Project 1/1/Audio/Other.wav"
    assert items[1].is_relative is False


def test_parse_items_supports_unquoted_name_and_file():
    text = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  <TRACK
    <ITEM
      POSITION 10.0
      LENGTH 2.5
      NAME AtutMelo2.wav
      <SOURCE WAVE
        FILE AtutMelo2.wav
      >
    >
  >
>
"""

    items = parse_items(text)

    assert len(items) == 1
    assert items[0].name == "AtutMelo2.wav"
    assert items[0].source_file == "AtutMelo2.wav"
    assert items[0].is_relative is True


def test_parse_items_skips_items_without_file_source():
    text = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  <TRACK
    <ITEM
      POSITION 10.0
      LENGTH 2.5
      NAME "Empty Item"
    >
  >
>
"""

    assert parse_items(text) == []


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


def test_build_audit_reports_tutsan_audio_shadow_candidate(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    shadow_rpp = SYNTHETIC_RPP.replace(
        'FILE "Aniel Vocal 2-11.wav"',
        f'FILE "{audio_dir}/Aniel Vocal 2-11.wav"',
    )
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(shadow_rpp)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11.wav", b"old-other-song")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert [c.basename for c in audit.candidates] == ["Aniel Vocal 2-11.wav"]
    assert audit.candidates[0].source_file == str(audio_dir / "Aniel Vocal 2-11.wav")
    assert audit.candidates[0].root_path == project_root / "Aniel Vocal 2-11.wav"
    assert audit.stop_reasons == []


def test_build_audit_keeps_audio_shadow_candidate_after_root_rename(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    shadow_rpp = SYNTHETIC_RPP.replace(
        'FILE "Aniel Vocal 2-11.wav"',
        f'FILE "{audio_dir}/Aniel Vocal 2-11.wav"',
    )
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(shadow_rpp)
    write_file(project_root / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11.wav", b"old-other-song")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert [c.basename for c in audit.candidates] == ["Aniel Vocal 2-11.wav"]
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


def test_build_audit_does_not_report_root_only_candidate_as_duplicate(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert audit.duplicates == {}


def test_build_audit_stops_when_relative_source_escapes_project_root(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    escaping_rpp = SYNTHETIC_RPP.replace(
        'FILE "Aniel Vocal 2-11.wav"',
        'FILE "../Audio/Aniel Vocal 2-11.wav"',
    )
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(escaping_rpp)

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert (
        "relative source escapes project root: ../Audio/Aniel Vocal 2-11.wav"
        in audit.stop_reasons
    )


def test_build_audit_stops_on_ambiguous_relative_basename(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    ambiguous_rpp = SYNTHETIC_RPP.replace(
        "  >\n>\n",
        """    <ITEM
      POSITION 112.0
      LENGTH 1.0
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "takes/Aniel Vocal 2-11.wav"
      >
    >
  >
>
""",
    )
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(ambiguous_rpp)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"root")
    write_file(project_root / "takes" / "Aniel Vocal 2-11.wav", b"nested")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert (
        "ambiguous relative basename: Aniel Vocal 2-11.wav "
        "(Aniel Vocal 2-11.wav, takes/Aniel Vocal 2-11.wav)"
        in audit.stop_reasons
    )


def test_build_audit_stops_when_exact_source_is_used_outside_tutsan(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    mixed_use_rpp = SYNTHETIC_RPP.replace(
        'FILE "/Volumes/Project 1/1/Audio/Other.wav"',
        'FILE "Aniel Vocal 2-11.wav"',
    )
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(mixed_use_rpp)
    write_file(project_root / "Aniel Vocal 2-11.wav", b"root")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert (
        "source used inside and outside Tutsan: Aniel Vocal 2-11.wav "
        "(1/2 items in Tutsan)"
        in audit.stop_reasons
    )


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


def test_compare_sample_edits_reports_preserved_payload_when_file_path_changes():
    before = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  MARKER 7 100.0 Tutsan 1 0 1 B {REGION-GUID} 0 1
  MARKER 7 130.0 "" 1
  <TRACK
    <ITEM
      POSITION 110.0
      LENGTH 5.0
      IGUID {ITEM-GUID}
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
      SAMPLEEDITS 1 1 96000
      <SPLS 0
        SPL 10 0.1
        SPL 11 0.2
      >
    >
  >
>
"""
    after = before.replace(
        'FILE "Aniel Vocal 2-11.wav"',
        'FILE "/Volumes/Project 1/1/Audio/Aniel Vocal 2-11.wav"',
    )

    report = compare_sample_edits(
        before,
        after,
        region_id=7,
        region_name="Tutsan",
    )

    assert report.before_count == 1
    assert report.after_count == 1
    assert report.preserved_count == 1
    assert report.changed_count == 0
    assert report.missing_guids == []
    assert report.path_changed_guids == ["{ITEM-GUID}"]


def test_compare_sample_edits_reports_changed_payload():
    before = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  MARKER 7 100.0 Tutsan 1 0 1 B {REGION-GUID} 0 1
  MARKER 7 130.0 "" 1
  <TRACK
    <ITEM
      POSITION 110.0
      LENGTH 5.0
      IGUID {ITEM-GUID}
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
      SAMPLEEDITS 1 1 96000
      <SPLS 0
        SPL 10 0.1
      >
    >
  >
>
"""
    after = before.replace("SPL 10 0.1", "SPL 10 0.5")

    report = compare_sample_edits(
        before,
        after,
        region_id=7,
        region_name="Tutsan",
    )

    assert report.preserved_count == 0
    assert report.changed_guids == ["{ITEM-GUID}"]


def test_build_audit_stops_when_reference_sample_edit_payload_changed(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    before_path = project_root / "Before.RPP"
    after_path = project_root / "After.RPP"
    before = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  MARKER 7 100.0 Tutsan 1 0 1 B {REGION-GUID} 0 1
  MARKER 7 130.0 "" 1
  <TRACK
    <ITEM
      POSITION 110.0
      LENGTH 5.0
      IGUID {ITEM-GUID}
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
      SAMPLEEDITS 1 1 96000
      <SPLS 0
        SPL 10 0.1
      >
    >
  >
>
"""
    before_path.parent.mkdir(parents=True)
    before_path.write_text(before)
    after_path.write_text(before.replace("SPL 10 0.1", "SPL 10 0.5"))

    audit = build_audit(
        rpp_path=after_path,
        project_root=project_root,
        audio_dir=audio_dir,
        region_id=7,
        region_name="Tutsan",
        sample_edit_reference=before_path,
    )

    assert "sample edit payloads changed: 1" in audit.stop_reasons


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
    assert result == {
        "renamed": [(str(old_path), str(new_path))],
        "skipped_existing": [],
    }
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


def test_apply_rename_skips_already_renamed_candidates(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    new_path = write_file(
        project_root / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan"
    )

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")
    result = apply_rename(audit)

    assert result == {"renamed": [], "skipped_existing": [str(new_path)]}


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


def test_verify_copied_targets_still_works_after_root_rename(tmp_path):
    project_root = tmp_path / "11"
    audio_dir = tmp_path / "1" / "Audio"
    rpp_path = project_root / "Project.RPP"
    rpp_path.parent.mkdir(parents=True)
    rpp_path.write_text(SYNTHETIC_RPP)
    write_file(project_root / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")
    write_file(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")

    audit = build_audit(rpp_path, project_root, audio_dir, 7, "Tutsan")

    assert audit.stop_reasons == []
    assert verify_copied_targets(audit) == []


def test_relink_rpp_text_replaces_only_tutsan_matching_sources(tmp_path):
    audio_dir = tmp_path / "Audio"
    new_path = audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav"
    mapping = {
        "files": [
            {
                "old_source_file": "Aniel Vocal 2-11.wav",
                "new_audio_path": str(new_path),
            }
        ]
    }
    text = """<REAPER_PROJECT 0.1 "7.72/macOS-arm64" 0
  MARKER 7 100.0 Tutsan 1 0 1 B {REGION-GUID} 0 1
  MARKER 7 130.0 "" 1
  <TRACK
    <ITEM
      POSITION 110.0
      LENGTH 5.0
      IGUID {TUTSAN-GUID}
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
      SAMPLEEDITS 1 1 96000
      <SPLS 0
        SPL 10 0.1
      >
    >
    <ITEM
      POSITION 200.0
      LENGTH 5.0
      IGUID {OTHER-GUID}
      NAME "Aniel Vocal 2-11.wav"
      <SOURCE WAVE
        FILE "Aniel Vocal 2-11.wav"
      >
    >
  >
>
"""

    relinked, changed = relink_rpp_text(text, mapping, 7, "Tutsan")

    assert changed == 1
    assert f'FILE "{new_path}"' in relinked
    assert relinked.count('FILE "Aniel Vocal 2-11.wav"') == 1
    assert "SAMPLEEDITS 1 1 96000" in relinked
    assert ">    <ITEM" not in relinked


def test_verify_project_relinked_passes_when_targets_exist(tmp_path):
    audio_dir = tmp_path / "Audio"
    write_file(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav", b"new-tutsan")
    rpp_path = tmp_path / "Project.RPP"
    rpp_path.write_text(
        SYNTHETIC_RPP.replace(
            'FILE "Aniel Vocal 2-11.wav"',
            f'FILE "{audio_dir}/Aniel Vocal 2-11 - R7 Tutsan.wav"',
        )
    )
    mapping = {
        "files": [
            {
                "old_source_file": "Aniel Vocal 2-11.wav",
                "new_audio_path": str(audio_dir / "Aniel Vocal 2-11 - R7 Tutsan.wav"),
            }
        ]
    }

    assert verify_project_relinked(rpp_path, mapping, 7, "Tutsan") == []
