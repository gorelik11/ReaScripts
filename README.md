# ReaScripts

A collection of REAPER ReaScripts for audio production.

## Scripts

### Envelope-based Limiter V1.0

Brick-wall peak limiter via volume automation envelope. Analyzes selected audio item for peaks exceeding a user-defined ceiling and creates precise volume automation to tame them.

- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)
- Infinity ratio — true brick-wall limiting
- Per-window gain reduction for precise automation
- Fully undoable (Ctrl+Z / Cmd+Z)

**Note:** Volume automation is post-FX. To measure results with a plugin, route the track to a bus and place the meter there.

### Envelope-based Limiter (Item) V1.0

Same as Envelope-based Limiter V1.0 but writes to the **item's own take volume envelope** instead of the track volume envelope. Keeps the track envelope clean.

- All the same features as the track version
- Automation lives on the item — moves with it if repositioned
- Take volume envelope is pre-FX, so you can measure directly with plugins on the same track

### RCBit Limiter V1.0

Split-based peak limiter using [JS:RCBitRangeGain](https://github.com/RCJacH/ReaScripts) for bit-accurate gain reduction. Instead of writing automation, it splits the audio item at peak boundaries and applies RCBitRangeGain as Take FX only on peak segments.

- Bit-accurate gain reduction (no floating-point truncation artifacts)
- Preserves transients — no lookahead or envelope shaping
- Each peak window gets its own precisely calculated Bit Ratio
- Non-peak segments remain completely clean with no plugins
- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH. Install via ReaPack: **Extensions > ReaPack > Import repositories** and add `https://github.com/RCJacH/ReaScripts/raw/master/index.xml`

See V3.0 below for the latest version with improved region detection and attack/release handling.

### RCBit Limiter V3.0

Improved split-based peak limiter using [JS:RCBitRangeGain](https://github.com/RCJacH/ReaScripts). Same concept as V1.0 — splits the item at peak boundaries and applies RCBitRangeGain only on peak segments — but with significantly better region detection logic.

- Binary classification: each analysis window is either PEAK or CLEAN
- Attack/release expansion on peak regions with proper adjacent-region shrinking (no cascade merging)
- Minimum region length (20ms) — tiny regions absorbed into neighbors
- Proper Macro/Bit Ratio calculation — gains < 0.15 dB are skipped (no unnecessary FX)
- Fallback to project sample rate when source sample rate is unavailable
- Configurable ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Note:** Works with full items — select the item from its beginning. If the item's start is trimmed, peak detection will be offset. Split items work perfectly.

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH.

### RCBit LUFS Limiter V3.0

Combined LUFS gain staging and peak limiting in a single pass using [JS:RCBitRangeGain](https://github.com/RCJacH/ReaScripts). Measures the item's integrated LUFS via SWS, calculates the gain needed to reach the target, then splits and applies RCBitRangeGain to each segment — boosting quiet parts and limiting peaks that would exceed the ceiling.

See V4.0 below for the latest version with BR quantization for mastering accuracy.

### RCBit LUFS Limiter V4.0

Same concept as V3.0 — LUFS gain staging + peak limiting via splits and RCBitRangeGain — but with mastering-grade accuracy improvements.

- **BR quantization**: Peak regions floor-quantize Bit Ratio to the JSFX step size (default 0.05), ensuring peaks never exceed the ceiling due to rounding. Boost regions round to nearest step.
- SR fallback chain: source → parent source → project SR → 44100
- LUFS guard: handles -inf LUFS (silent/offline items) gracefully
- All V3 features: binary classification, attack/release with shrink-adjacent, tiny region absorption, single RCBit per split
- Configurable target LUFS, peak ceiling (dB), attack (ms), release (ms), and analysis window (ms)
- Default settings optimized for mastering: -9 LUFS, -0.5 dB ceiling, 0ms attack, 70ms release

**Note:** Works with full items — select the item from its beginning. If the item's start is trimmed, peak detection will be offset. Split items work perfectly.

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH and SWS extension.

### RCBit LUFS Limiter V3.0 (Legacy)

- LUFS measurement via SWS `NF_AnalyzeTakeLoudness` (accurate, gated)
- Binary classification: each analysis window is either BOOST or PEAK
- Attack/release expansion on peak regions with proper adjacent-region shrinking
- Minimum region length (20ms) — tiny regions absorbed into neighbors
- Adjacent regions with identical RCBit params are merged to reduce splits
- Single RCBit per split — never doubles up
- Mono items automatically corrected for pan law
- Configurable target LUFS, peak ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Note:** The script works with full items — select the item from its beginning. If the item's start is trimmed (e.g., from lanes usage), peak detection will be offset. Split items work perfectly.

**Requires:** JS:RCBitRangeGain JSFX plugin by RCJacH and SWS extension.

### LUFS Envelope Limiter V1.0

Combined LUFS gain staging + peak limiting via **take volume envelope** — no splits, no FX, pure automation. Same analysis as the RCBit LUFS Limiter but writes continuous gain to the item's take volume envelope instead of splitting and adding JSFX.

- **No quantization**: gain is written as exact linear values (no JSFX step size rounding)
- **No splits**: the item stays as one piece, making it easy to undo or adjust
- **Per-window gain precision**: each 5ms window gets its exact required gain
- Attack/release smoothing: gradual transitions between boost and peak regions
- LUFS measurement via SWS, mono pan-law correction
- SR fallback chain for reliable operation
- Configurable target LUFS, peak ceiling (dB), attack (ms), release (ms), and analysis window (ms)

**Trade-off vs RCBit approach**: The envelope applies pre-FX gain (standard volume automation), while RCBitRangeGain provides bit-accurate gain reduction. For mastering with specific bit-depth requirements, use the RCBit version. For general loudness/peak control, the envelope approach is simpler and more precise.

**Note:** Works with full items — select the item from its beginning.

**Requires:** SWS extension (for LUFS analysis and take envelope access). No JSFX plugins needed.

### Align Track to Reference V1.0

Cross-instrument timing alignment by splitting and moving waveforms. Aligns a target track to a reference track without stretch markers and without quantizing to a grid.

See V2.0 below for the latest version with additional features.

### Align Track to Reference V2.0

Cross-instrument timing alignment by splitting and moving waveforms. Aligns a target track to a reference track without stretch markers and without quantizing to a grid.

The script analyzes transient onsets in both tracks, matches them, and identifies where the timing difference exceeds a user-defined threshold. It then splits and moves only those moments, leaving everything else untouched.

**How it works:**

The threshold (e.g., 15ms) means: "ignore timing differences smaller than this." If the target is 10ms late compared to the reference, it's left alone. If it's 20ms late, it gets corrected. Lower threshold = more corrections, higher = only fix the big ones.

What makes this script feel natural is the grouping logic. When multiple onsets are close together, it picks the one with the biggest timing difference and moves the whole section. That's why sometimes it moves one note, sometimes a whole phrase. It's approximating what a human editor would do: fix the anchor beat, let the surrounding notes follow naturally.

This means the result isn't a rigid lock to the reference. It's more like a tighter conversation between the two instruments. In some moments it feels amazing, more natural than moving every single note to match the reference. The groove breathes, but the important hits land together.

**V2.0 new features:**

- **Mode slider (0-100)** -- controls the balance between musical feel and tight lock:
  - **0 (Smart/Musical):** Conservative onset detection, groups nearby corrections within the same beat, picks the strongest one. Fewer splits, groove breathes. Example: 6 adjustments on a 51-second selection.
  - **100 (Precise/Tight):** Sensitive onset detection, wider matching window, no grouping. Every detected timing difference gets its own split and move. Maximum tightness. Example: 35 adjustments on the same selection.
  - **Values in between** blend smoothly: onset sensitivity, match window, and grouping window all interpolate continuously.
- **Gap filling with crossfade** -- after items are split and moved, gaps are automatically filled by extending item edges with a 5ms overlap for smooth crossfading.
- **Time selection support** -- set a time selection in REAPER to only process that range.
- **Selected items support** -- select specific items on the target track to only process those.
- Priority: time selection > selected items > entire track.

**Features:**
- Works with any time signature, any tempo, or completely free-tempo material
- No stretch markers, no grid quantization
- Splits and moves only where musically necessary
- Supports 16/24/32-bit PCM and 32/64-bit float WAV files
- Pure Python, no external dependencies
- Creates a new track with the aligned version, original untouched
- Single undo point for all changes

**Parameters:**
- **Reference track #** -- the track to align TO (e.g., the Pandero)
- **Target track #** -- the track to be aligned (e.g., the Jarana)
- **Threshold (ms)** -- minimum timing error that triggers a correction
- **Mode (0=Smart 100=Precise)** -- balance between musical feel and tight lock

## Installation

Copy script files directly into your REAPER Scripts folder:
- **macOS:** `~/Library/Application Support/REAPER/Scripts/`
- **Windows:** `%APPDATA%\REAPER\Scripts\`
- **Linux:** `~/.config/REAPER/Scripts/`

Then load via **Actions > Show action list > Load ReaScript**.

**For Python scripts (.py):** Make sure Python is enabled in REAPER Preferences > Plug-ins > ReaScript.

## Usage

### Limiter scripts (Lua)
1. Select an audio item on a track
2. Run the script from the Actions list
3. Adjust parameters in the dialog box
4. Click OK

### Align Track to Reference (Python)
1. Optionally: set a time selection or select items on the target track
2. Run the script from the Actions list
3. Enter reference track number, target track number, threshold, and mode
4. The script creates a new track with the aligned version

All scripts are fully undoable.

## License

MIT
