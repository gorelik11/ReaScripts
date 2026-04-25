# Reels Auto-Render: Design Spec

## Goal

Automatically create ~50 Instagram reels (~1 min each) from a live concert recording in REAPER. Two source tracks (video + audio) send to a Bus track. Each reel ends with a 3-second fade out on both video and audio.

## Project State

- Track 0: "Elha" (video), 1 item, ~3275s
- Track 1: "Dima Gorelik Trio HD" (audio), 1 item, ~3275s
- Track 2: "Bus" (master receiver, no items)
- 8 song regions on lane 1 with time signatures in names
- Render settings pre-configured: AVFoundation 1080x1920 10240kbps 320-aac

## Compositions

| # | Name | Time Sig | Start (s) | End (s) | Duration | Madmom |
|---|------|----------|-----------|---------|----------|--------|
| 1 | Cafe On the Beach | 7/8 | 0.6 | 306.0 | 5:05 | Yes (beats_per_bar=7) |
| 2 | Italo Disco | 17/8 | 321.2 | 856.8 | 8:56 | No (manual) |
| 3 | Beskid's Air | 4/4 | 855.9 | 992.8 | 2:17 | Yes (beats_per_bar=4) |
| 4 | Shinanim Shinanim | 4/4 | 992.8 | 1566.2 | 9:34 | Yes (beats_per_bar=4) |
| 5 | Trzcina | 4/4 | 1564.8 | 2061.6 | 8:17 | Yes (beats_per_bar=4) |
| 6 | Elhayaar | 12/8 | 2166.6 | 2668.3 | 8:22 | Yes (beats_per_bar=4) |
| 7 | Karapaty | 4/4 | 2669.3 | 3271.7 | 10:02 | Yes (beats_per_bar=4) |
| 8 | El Hayaar Rubato Intro | rubato | 2062.4 | 2166.6 | 1:44 | No (manual) |

## Three Phases

### Phase 1: Tempo Map via madmom (Python)

For 6 compositions (excluding Italo Disco 17/8 and Rubato Intro):

1. Read audio from the audio track's source file using librosa/soundfile with offset/duration matching each region
2. Run `RNNDownBeatProcessor` -> `DBNDownBeatTrackingProcessor(beats_per_bar=[N], fps=100)`
3. Calculate BPM from downbeat-to-downbeat intervals: `bpm = quarter_notes_per_bar * 60 / bar_duration`
   - 7/8: `bpm = 3.5 * 60 / bar_duration` (REAPER BPM is always quarter-note based)
   - 4/4: `bpm = 4 * 60 / bar_duration`
   - 12/8: `bpm = 6 * 60 / bar_duration` (12 eighths = 6 quarter notes per bar; REAPER BPM is always quarter-note based)
4. Set tempo markers in REAPER via reapy, only within region boundaries
5. Set time signature at first tempo marker of each region

### Phase 2: Create Reel Regions (Python via reapy)

For each composition with a tempo map:

1. Walk downbeats from region start
2. Find the downbeat closest to ~57s from current reel start (60s minus 3s fade)
3. Create region: start of segment to downbeat + 3s
4. Region placed on lane 2 (via ReaScript API or chunk editing)
5. Name: `{Composition} - Reel {NN}`
6. Pause for user to visually inspect and adjust regions before rendering

For Rubato Intro (1:44): skip, user creates 1 reel manually.
For Italo Disco (~8:56): skip, user creates ~3 reels manually.

### Phase 3: Sequential Render (Lua script)

For each reel region on lane 2, in order:

1. Set time selection to region boundaries
2. Set fade out (3s) on items of both tracks (video track 0 + audio track 1) at region end
3. Nudge start of next item on both tracks by +0.04s (~1 frame at 25fps) to prevent video flash after fade
4. Render using current render window settings (action 42230 or equivalent)
5. Restore next item positions to original
6. Remove fade outs
7. Output file: `{Composition} - Reel {NN}.mp4` in project directory

## Edge Cases

- Last reel of each composition: no "next item" to nudge (items are continuous, so the end of the region is within the item, not at a split point)
- Regions that overlap between compositions (e.g., Beskid's Air / Shinanim boundary): use region boundaries, not item boundaries
- Short final segments (<30s): include as a reel anyway or merge with previous — user decides during review

## Technical Notes

- Items are NOT pre-split. Fade out is applied to the continuous item within the time selection.
- The "nudge" trick: since items span the entire track, the concern is about video frames rendering past the fade-out region. The approach is to temporarily split the item at region end, then nudge the split point, render, and heal the split.
- Actually: since we render by time selection (not by item), and items are continuous, the video flash issue may manifest differently. The render captures whatever is in the time selection on the Bus track. Need to verify if fade-out on source track items prevents video frames from leaking past the fade in the rendered output. If not, temporary split + nudge is needed.

## Render Settings

Already configured in REAPER render dialog:
- Source: Bus track (track 2) — "Stems (selected tracks)" with Bus selected
- Format: AVFoundation
- Resolution: 1080x1920 (vertical/portrait)
- Video bitrate: 10240 kbps
- Audio: AAC 320 kbps
- Output: project directory
