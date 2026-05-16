from pathlib import Path

from tools.tutsan_media_relink import build_audit, find_region, parse_items


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
