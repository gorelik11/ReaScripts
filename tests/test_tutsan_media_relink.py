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
