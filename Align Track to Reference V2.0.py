"""
Align Track to Reference V2.0
Aligns a target track's timing to a reference track by splitting and moving items.
Works with any time signature, any tempo, grid-free material.
No external dependencies (no NumPy, no soundfile).

V2.0 changes:
  - Gap filling after split/move with 5ms crossfade overlap
  - Mode slider (0=Smart/Musical to 100=Precise/Tight)
  - Time selection support (only process within time selection)
  - Selected items support (only process selected items on target track)

Usage:
  1. Run from REAPER (Actions > ReaScript)
  2. Optionally set a time selection or select items on the target track
  3. Enter reference track number, target track number, threshold, and mode
  4. Script creates a new track with aligned version of target
"""

import wave
import struct
import math

# When running inside REAPER, RPR_ functions are available globally
# No need to import reapy


def get_track_name(track_id):
    """Get track name, handling variable return tuple size."""
    result = RPR_GetSetMediaTrackInfo_String(track_id, "P_NAME", "", False)
    if isinstance(result, tuple):
        # Filter out known non-name strings and pointers
        for item in result:
            if isinstance(item, str) and item != "P_NAME" and item != "":
                # Skip items that look like memory pointers
                if item.startswith("(MediaTrack*)") or item.startswith("0x"):
                    continue
                return item
    return ""


def get_source_filename(source):
    """Get source filename, handling variable return tuple size."""
    result = RPR_GetMediaSourceFileName(source, "", 512)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and ("/" in item or "\\" in item):
                return item
    return ""


def get_user_input():
    """Ask user for track numbers, threshold, and mode via REAPER dialog."""
    result = RPR_GetUserInputs(
        "Align Track to Reference V2.0",
        4,
        "Reference track #,Target track #,Threshold (ms),Mode (0=Smart 100=Precise)",
        "1,2,15,0",
        512
    )
    if isinstance(result, tuple):
        retval = result[0]
        retvals_csv = None
        for i in range(len(result) - 1, -1, -1):
            if isinstance(result[i], str) and "," in result[i]:
                retvals_csv = result[i]
                break
        if retvals_csv is None:
            for i in range(len(result) - 1, -1, -1):
                if isinstance(result[i], str):
                    retvals_csv = result[i]
                    break
        if retvals_csv is None:
            return None
    else:
        return None
    if not retval:
        return None
    parts = retvals_csv.split(",")
    if len(parts) != 4:
        return None
    try:
        ref_num = int(parts[0].strip())
        target_num = int(parts[1].strip())
        threshold_ms = float(parts[2].strip())
        mode = int(parts[3].strip())
        mode = max(0, min(100, mode))
    except ValueError:
        RPR_ShowMessageBox("Invalid input. Please enter numbers.", "Error", 0)
        return None
    return ref_num, target_num, threshold_ms, mode


def get_time_selection():
    """Get time selection range if any. Returns (start, end) or None."""
    result = RPR_GetSet_LoopTimeRange(False, False, 0, 0, False)
    if isinstance(result, tuple):
        # Find start and end times - they're float values in the tuple
        floats = [x for x in result if isinstance(x, float)]
        if len(floats) >= 2:
            start = floats[0]
            end = floats[1]
            if end > start + 0.001:
                return (start, end)
    return None


def get_selected_item_ids(track_id):
    """Get list of selected item IDs on a track."""
    n_items = RPR_GetTrackNumMediaItems(track_id)
    selected = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        if RPR_IsMediaItemSelected(item_id):
            selected.append(item_id)
    return selected


def read_wav_segment(filepath, offset_sec, length_sec, target_sr=22050):
    """Read a segment of a WAV file and return mono samples as floats.
    Supports PCM (16/24/32-bit) and float (32/64-bit) WAV files.
    Decimates to target_sr for speed - fine for onset detection.
    Uses only Python stdlib."""

    def parse_wav_header(f):
        """Parse WAV header, return format info and data chunk location."""
        riff = f.read(4)
        if riff not in (b'RIFF', b'RF64'):
            return None
        f.read(4)  # file size
        if f.read(4) != b'WAVE':
            return None

        fmt_info = None
        data_offset = None
        data_size = None
        fmt_data = None

        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8:
                break
            chunk_id = chunk_header[:4]
            chunk_size = struct.unpack('<I', chunk_header[4:8])[0]

            if chunk_id == b'fmt ':
                fmt_data = f.read(chunk_size)
                audio_format = struct.unpack('<H', fmt_data[0:2])[0]
                n_channels = struct.unpack('<H', fmt_data[2:4])[0]
                sr = struct.unpack('<I', fmt_data[4:8])[0]
                bits = struct.unpack('<H', fmt_data[14:16])[0]

                is_float = (audio_format == 3)
                if audio_format == 65534 and len(fmt_data) >= 26:
                    sub_format = struct.unpack('<H', fmt_data[24:26])[0]
                    is_float = (sub_format == 3)

                fmt_info = {
                    'channels': n_channels, 'sr': sr, 'bits': bits,
                    'is_float': is_float
                }
            elif chunk_id == b'data':
                data_offset = f.tell()
                data_size = chunk_size
                break
            else:
                f.seek(chunk_size, 1)

        if not fmt_info or data_offset is None:
            return None
        fmt_info['data_offset'] = data_offset
        fmt_info['data_size'] = data_size
        return fmt_info

    def read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr):
        """Read audio with decimation for speed."""
        sr = fmt_info['sr']
        n_ch = fmt_info['channels']
        bits = fmt_info['bits']
        is_float = fmt_info['is_float']
        bps = bits // 8
        frame_size = bps * n_ch
        total_frames = fmt_info['data_size'] // frame_size

        start_frame = int(offset_sec * sr)
        length_frames = int(length_sec * sr)
        if start_frame >= total_frames:
            return [], sr
        if start_frame + length_frames > total_frames:
            length_frames = total_frames - start_frame

        # Decimation factor
        decimate = max(1, sr // target_sr)
        out_sr = sr / decimate

        f.seek(fmt_info['data_offset'] + start_frame * frame_size)

        # Read in chunks to avoid massive memory usage
        chunk_frames = 4096
        samples = []
        frames_read = 0
        frame_counter = 0

        # Determine unpack format for one frame
        if is_float and bits == 32:
            sample_fmt = 'f'
        elif is_float and bits == 64:
            sample_fmt = 'd'
        elif not is_float and bits == 16:
            sample_fmt = 'h'
        elif not is_float and bits == 32:
            sample_fmt = 'i'
        elif not is_float and bits == 24:
            sample_fmt = None  # handled specially
        else:
            return [], sr

        while frames_read < length_frames:
            read_count = min(chunk_frames, length_frames - frames_read)
            raw = f.read(read_count * frame_size)
            if not raw:
                break

            actual_frames = len(raw) // frame_size

            if sample_fmt and bits != 24:
                n_vals = actual_frames * n_ch
                try:
                    all_vals = struct.unpack('<' + sample_fmt * n_vals,
                                            raw[:actual_frames * frame_size])
                except struct.error:
                    break

                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        idx = i * n_ch
                        s = 0.0
                        for ch in range(n_ch):
                            s += all_vals[idx + ch]
                        s /= n_ch
                        # Normalize int formats
                        if sample_fmt == 'h':
                            s /= 32768.0
                        elif sample_fmt == 'i':
                            s /= 2147483648.0
                        samples.append(s)
                    frame_counter += 1
            else:
                # 24-bit
                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        s = 0.0
                        for ch in range(n_ch):
                            idx = (i * n_ch + ch) * 3
                            if idx + 3 <= len(raw):
                                b = raw[idx:idx + 3]
                                val = b[0] | (b[1] << 8) | (b[2] << 16)
                                if val >= 0x800000:
                                    val -= 0x1000000
                                s += val / 8388608.0
                        samples.append(s / n_ch)
                    frame_counter += 1

            frames_read += actual_frames

        return samples, out_sr

    # Try wave module first (PCM only)
    try:
        with wave.open(filepath, 'rb') as wf:
            sr = wf.getframerate()
            sampwidth = wf.getsampwidth()
            n_ch = wf.getnchannels()
            n_total = wf.getnframes()

            start_frame = int(offset_sec * sr)
            length_frames = int(length_sec * sr)
            if start_frame >= n_total:
                return [], sr
            if start_frame + length_frames > n_total:
                length_frames = n_total - start_frame

            decimate = max(1, sr // target_sr)
            out_sr = sr / decimate

            wf.setpos(start_frame)

            samples = []
            chunk_frames = 4096
            frames_read = 0
            frame_counter = 0

            while frames_read < length_frames:
                read_count = min(chunk_frames, length_frames - frames_read)
                raw = wf.readframes(read_count)
                actual = len(raw) // (sampwidth * n_ch)

                if actual == 0:
                    break

                if sampwidth == 2:
                    vals = struct.unpack('<' + 'h' * (actual * n_ch),
                                        raw[:actual * sampwidth * n_ch])
                    for i in range(actual):
                        if frame_counter % decimate == 0:
                            s = sum(vals[i * n_ch + ch] for ch in range(n_ch))
                            samples.append(s / n_ch / 32768.0)
                        frame_counter += 1
                elif sampwidth == 3:
                    for i in range(actual):
                        if frame_counter % decimate == 0:
                            s = 0.0
                            for ch in range(n_ch):
                                idx = (i * n_ch + ch) * 3
                                b = raw[idx:idx + 3]
                                val = b[0] | (b[1] << 8) | (b[2] << 16)
                                if val >= 0x800000:
                                    val -= 0x1000000
                                s += val / 8388608.0
                            samples.append(s / n_ch)
                        frame_counter += 1
                elif sampwidth == 4:
                    vals = struct.unpack('<' + 'i' * (actual * n_ch),
                                        raw[:actual * sampwidth * n_ch])
                    for i in range(actual):
                        if frame_counter % decimate == 0:
                            s = sum(vals[i * n_ch + ch] for ch in range(n_ch))
                            samples.append(s / n_ch / 2147483648.0)
                        frame_counter += 1

                frames_read += actual

            if samples:
                return samples, out_sr
    except Exception:
        pass

    # Fallback: raw parse for float WAVs
    try:
        with open(filepath, 'rb') as f:
            fmt_info = parse_wav_header(f)
            if not fmt_info:
                return [], 0
            return read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr)
    except Exception:
        return [], 0


def get_active_comp_items(track_id, time_range=None, selected_ids=None):
    """Get only the active comp items (not stacked full takes).

    Args:
        track_id: REAPER track ID
        time_range: Optional (start, end) tuple to filter by time range
        selected_ids: Optional list of selected item IDs to filter by
    """
    n_items = RPR_GetTrackNumMediaItems(track_id)
    if n_items == 0:
        return []

    all_items = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)

        # Filter by selected items if provided
        if selected_ids is not None:
            if item_id not in selected_ids:
                continue

        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")

        # Filter by time range if provided
        if time_range is not None:
            item_end = pos + length
            # Skip items completely outside the time range
            if item_end <= time_range[0] or pos >= time_range[1]:
                continue

        active_take = RPR_GetActiveTake(item_id)
        if not active_take:
            continue
        source = RPR_GetMediaItemTake_Source(active_take)
        if not source:
            continue

        filename = get_source_filename(source)
        offset = RPR_GetMediaItemTakeInfo_Value(active_take, "D_STARTOFFS")
        vol = RPR_GetMediaItemTakeInfo_Value(active_take, "D_VOL")

        all_items.append({
            'item_id': item_id,
            'position': pos,
            'length': length,
            'file': filename,
            'offset': offset,
            'volume': vol,
            'index': i
        })

    if not all_items:
        return []

    # Separate comp items from full stacked takes
    lengths = sorted([item['length'] for item in all_items])
    max_len = max(lengths)
    min_len = min(lengths)

    # If all items are similar length, return all
    if max_len < min_len * 3:
        return all_items

    median_len = lengths[len(lengths) // 2]

    # Group by position to detect stacked takes
    position_groups = {}
    for item in all_items:
        pos_key = round(item['position'], 1)
        if pos_key not in position_groups:
            position_groups[pos_key] = []
        position_groups[pos_key].append(item)

    full_take_threshold = median_len * 2
    comp_items = []

    for pos_key, group in position_groups.items():
        if len(group) > 3 and all(item['length'] > full_take_threshold for item in group):
            continue  # Skip stacked full takes
        else:
            comp_items.extend(group)

    comp_items.sort(key=lambda x: x['position'])
    return comp_items


def detect_onsets(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """Detect transient onsets from audio. Pure Python, no NumPy.

    Args:
        comp_items: List of items to analyze
        threshold_factor: Higher = fewer onsets detected (conservative).
            Lower = more onsets detected (sensitive).
        min_onset_gap: Minimum gap between onsets in seconds.
    """
    all_onsets = []

    for item in comp_items:
        if not item['file']:
            continue

        samples, sr = read_wav_segment(item['file'], item['offset'], item['length'])
        if len(samples) < 512 or sr == 0:
            continue

        hop = 256
        frame_size = 512
        n_frames = (len(samples) - frame_size) // hop
        if n_frames < 3:
            continue

        # Energy per frame
        energy = []
        for i in range(n_frames):
            start = i * hop
            frame = samples[start:start + frame_size]
            e = sum(s * s for s in frame)
            energy.append(e)

        # Onset strength (positive energy increase)
        onset_strength = []
        for i in range(1, len(energy)):
            diff = energy[i] - energy[i - 1]
            onset_strength.append(max(diff, 0.0))

        if len(onset_strength) < 3:
            continue

        # Calculate mean and std
        n = len(onset_strength)
        mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)

        if std_str == 0:
            continue

        threshold = mean_str + threshold_factor * std_str
        min_dist_frames = int(min_onset_gap * sr / hop)

        # Peak finding
        peaks = []
        for idx in range(1, len(onset_strength) - 1):
            if onset_strength[idx] > threshold:
                if (onset_strength[idx] > onset_strength[idx - 1] and
                        onset_strength[idx] >= onset_strength[idx + 1]):
                    if not peaks or (idx - peaks[-1]) >= min_dist_frames:
                        peaks.append(idx)

        for peak in peaks:
            abs_time = item['position'] + (peak * hop) / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)

    all_onsets.sort()
    return all_onsets


def match_onsets(ref_onsets, target_onsets, max_match_window=0.055):
    """Match target onsets to nearest reference onsets."""
    matches = []

    for t_onset in target_onsets:
        best_idx = -1
        best_diff = float('inf')

        for i, r_onset in enumerate(ref_onsets):
            diff = abs(t_onset - r_onset)
            if diff < best_diff:
                best_diff = diff
                best_idx = i

        if best_idx >= 0 and best_diff < max_match_window:
            min_diff = t_onset - ref_onsets[best_idx]
            matches.append({
                'target_time': t_onset,
                'ref_time': ref_onsets[best_idx],
                'diff_sec': min_diff,
                'diff_ms': min_diff * 1000
            })

    return matches


def group_adjustments(adjustments, mode=0):
    """Group nearby adjustments based on mode.

    mode=0 (Smart): large grouping window (300ms), musical feel.
      Groups onsets within the same beat, picks the strongest correction.
    mode=100 (Precise): no grouping, every onset gets its own adjustment.
    Values in between: linear interpolation of grouping window.
    """
    if not adjustments:
        return []

    # Calculate min_gap from mode
    # At mode=0: 300ms window (groups onsets within same beat at most tempos)
    # At mode=100: 0ms (no grouping)
    min_gap = 0.30 * (1.0 - mode / 100.0)

    # If min_gap is essentially 0 (precise mode), return all adjustments
    if min_gap < 0.001:
        return list(adjustments)

    groups = []
    current_group = [adjustments[0]]

    for adj in adjustments[1:]:
        if adj['target_time'] - current_group[-1]['target_time'] < min_gap:
            current_group.append(adj)
        else:
            groups.append(current_group)
            current_group = [adj]
    groups.append(current_group)

    result = []
    for group in groups:
        best = max(group, key=lambda x: abs(x['diff_ms']))
        result.append(best)
    return result


def create_aligned_track(target_track_idx, comp_items):
    """Create a new track with only the comp items from target."""
    RPR_InsertTrackAtIndex(target_track_idx + 1, True)
    RPR_TrackList_AdjustWindows(False)

    new_track_idx = target_track_idx + 1
    new_track_id = RPR_GetTrack(0, new_track_idx)

    # Get target track name
    target_track_id = RPR_GetTrack(0, target_track_idx)
    target_name = get_track_name(target_track_id)
    RPR_GetSetMediaTrackInfo_String(new_track_id, "P_NAME", target_name + " (Aligned)", True)

    # Copy only comp items to new track
    for ci in comp_items:
        src_item = ci['item_id']
        pos = RPR_GetMediaItemInfo_Value(src_item, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(src_item, "D_LENGTH")

        new_item = RPR_AddMediaItemToTrack(new_track_id)
        RPR_SetMediaItemInfo_Value(new_item, "D_POSITION", pos)
        RPR_SetMediaItemInfo_Value(new_item, "D_LENGTH", length)

        # Copy all takes
        n_takes = RPR_GetMediaItemNumTakes(src_item)
        for t in range(n_takes):
            src_take = RPR_GetMediaItemTake(src_item, t)
            src_source = RPR_GetMediaItemTake_Source(src_take)
            new_take = RPR_AddTakeToMediaItem(new_item)
            RPR_SetMediaItemTake_Source(new_take, src_source)
            offset = RPR_GetMediaItemTakeInfo_Value(src_take, "D_STARTOFFS")
            RPR_SetMediaItemTakeInfo_Value(new_take, "D_STARTOFFS", offset)
            vol = RPR_GetMediaItemTakeInfo_Value(src_take, "D_VOL")
            RPR_SetMediaItemTakeInfo_Value(new_take, "D_VOL", vol)

        # Set active take
        active_take_idx = RPR_GetMediaItemInfo_Value(src_item, "I_CURTAKE")
        RPR_SetMediaItemInfo_Value(new_item, "I_CURTAKE", active_take_idx)

    return new_track_idx, new_track_id


def apply_adjustments(track_id, adjustments):
    """Split and move items. Works right-to-left.
    Returns list of (item_id, shift) for gap filling."""
    n_items = RPR_GetTrackNumMediaItems(track_id)
    comp_tracking = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
        comp_tracking.append({'id': item_id, 'pos': pos, 'length': length})

    adjustments.sort(key=lambda x: x['target_time'], reverse=True)

    successful = 0
    moved_items = []  # Track which items were moved and by how much

    for adj in adjustments:
        onset_time = adj['target_time']
        shift = -adj['diff_sec']
        split_time = onset_time - 0.005

        # Find containing item
        found = None
        for ci in comp_tracking:
            if ci['pos'] <= split_time < ci['pos'] + ci['length']:
                found = ci
                break

        if not found:
            continue

        if split_time <= found['pos'] + 0.005 or split_time >= found['pos'] + found['length'] - 0.005:
            new_pos = found['pos'] + shift
            RPR_SetMediaItemInfo_Value(found['id'], "D_POSITION", new_pos)
            moved_items.append({'id': found['id'], 'shift': shift})
            found['pos'] = new_pos
            successful += 1
        else:
            new_item_id = RPR_SplitMediaItem(found['id'], split_time)
            if new_item_id:
                new_pos = RPR_GetMediaItemInfo_Value(new_item_id, "D_POSITION")
                new_len = RPR_GetMediaItemInfo_Value(new_item_id, "D_LENGTH")
                adjusted_pos = new_pos + shift
                RPR_SetMediaItemInfo_Value(new_item_id, "D_POSITION", adjusted_pos)
                found['length'] = split_time - found['pos']
                comp_tracking.append({'id': new_item_id, 'pos': adjusted_pos, 'length': new_len})
                moved_items.append({'id': new_item_id, 'shift': shift})
                successful += 1

    return successful, moved_items


def get_source_length(item_id):
    """Get the total length of the source audio file for an item."""
    take = RPR_GetActiveTake(item_id)
    if not take:
        return 0
    source = RPR_GetMediaItemTake_Source(take)
    if not source:
        return 0
    result = RPR_GetMediaSourceLength(source, False)
    if isinstance(result, tuple):
        for val in result:
            if isinstance(val, float) and val > 0:
                return val
    elif isinstance(result, float):
        return result
    return 0


def fill_gaps_and_crossfade(track_id, moved_item_ids, crossfade_ms=5):
    """Fill gaps between consecutive items and create crossfade overlaps.

    After items are moved, gaps appear. This function extends item edges
    to fill those gaps and adds a small overlap for crossfading.

    Args:
        track_id: REAPER track ID
        moved_item_ids: Set of item IDs that were moved
        crossfade_ms: Crossfade overlap in milliseconds (default 5ms)
    """
    crossfade_sec = crossfade_ms / 1000.0

    # Get all items sorted by position
    n_items = RPR_GetTrackNumMediaItems(track_id)
    if n_items < 2:
        return 0

    items = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
        items.append({'id': item_id, 'pos': pos, 'length': length, 'index': i})

    items.sort(key=lambda x: x['pos'])

    gaps_filled = 0

    for i in range(len(items) - 1):
        curr = items[i]
        nxt = items[i + 1]
        curr_end = curr['pos'] + curr['length']
        gap = nxt['pos'] - curr_end

        if gap <= 0.0001:
            continue  # No gap or already overlapping

        # Determine which item was moved
        curr_was_moved = curr['id'] in moved_item_ids
        nxt_was_moved = nxt['id'] in moved_item_ids

        if nxt_was_moved and not curr_was_moved:
            # Next item was moved (likely left) - extend next item's left edge
            # to fill gap + crossfade
            extend = gap + crossfade_sec
            take = RPR_GetActiveTake(nxt['id'])
            if take:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
                # Check we have enough source audio before the current offset
                if start_offs >= extend:
                    new_pos = nxt['pos'] - extend
                    new_offs = start_offs - extend
                    new_len = nxt['length'] + extend
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", new_offs)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos
                    nxt['length'] = new_len
                    gaps_filled += 1
                elif start_offs > 0:
                    # Extend as much as we can
                    new_pos = nxt['pos'] - start_offs
                    new_len = nxt['length'] + start_offs
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", 0)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos
                    nxt['length'] = new_len
                    gaps_filled += 1

        elif curr_was_moved and not nxt_was_moved:
            # Current item was moved (likely right) - extend current item's right edge
            extend = gap + crossfade_sec
            src_len = get_source_length(curr['id'])
            take = RPR_GetActiveTake(curr['id'])
            if take and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                if available >= extend:
                    new_len = curr['length'] + extend
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len
                    gaps_filled += 1
                elif available > 0:
                    new_len = curr['length'] + available
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len
                    gaps_filled += 1

        else:
            # Both moved or neither moved - extend both by half
            half_gap = gap / 2.0

            # Extend current item's right edge
            extend_right = half_gap + crossfade_sec / 2.0
            src_len = get_source_length(curr['id'])
            take_curr = RPR_GetActiveTake(curr['id'])
            if take_curr and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_curr, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                if available >= extend_right:
                    new_len = curr['length'] + extend_right
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len

            # Extend next item's left edge
            extend_left = half_gap + crossfade_sec / 2.0
            take_nxt = RPR_GetActiveTake(nxt['id'])
            if take_nxt:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS")
                if start_offs >= extend_left:
                    new_pos = nxt['pos'] - extend_left
                    new_offs = start_offs - extend_left
                    new_len = nxt['length'] + extend_left
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS", new_offs)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos
                    nxt['length'] = new_len

            gaps_filled += 1

    return gaps_filled


def main():
    user_input = get_user_input()
    if not user_input:
        return

    ref_num, target_num, threshold_ms, mode = user_input
    n_tracks = RPR_CountTracks(0)

    ref_idx = ref_num - 1
    target_idx = target_num - 1

    if ref_idx < 0 or ref_idx >= n_tracks:
        RPR_ShowMessageBox("Reference track {} not found.".format(ref_num), "Error", 0)
        return
    if target_idx < 0 or target_idx >= n_tracks:
        RPR_ShowMessageBox("Target track {} not found.".format(target_num), "Error", 0)
        return

    ref_track_id = RPR_GetTrack(0, ref_idx)
    target_track_id = RPR_GetTrack(0, target_idx)

    ref_name = get_track_name(ref_track_id)
    target_name = get_track_name(target_track_id)

    # Determine mode label
    if mode == 0:
        mode_label = "Smart (Musical)"
    elif mode == 100:
        mode_label = "Precise (Tight)"
    else:
        mode_label = "Blend ({})".format(mode)

    RPR_ShowConsoleMsg("\n=== Align Track to Reference V2.0 ===\n")
    RPR_ShowConsoleMsg("Reference: Track {} ({})\n".format(ref_num, ref_name))
    RPR_ShowConsoleMsg("Target: Track {} ({})\n".format(target_num, target_name))
    RPR_ShowConsoleMsg("Threshold: {}ms\n".format(threshold_ms))
    RPR_ShowConsoleMsg("Mode: {}\n\n".format(mode_label))

    # Determine processing range
    time_range = get_time_selection()
    selected_ids = get_selected_item_ids(target_track_id)

    range_desc = ""
    target_time_range = None
    target_selected_ids = None
    ref_time_range = None

    if time_range:
        target_time_range = time_range
        ref_time_range = time_range
        range_desc = "Time selection: {:.1f}s - {:.1f}s".format(time_range[0], time_range[1])
    elif selected_ids:
        target_selected_ids = selected_ids
        range_desc = "{} selected items on target track".format(len(selected_ids))
    else:
        range_desc = "Entire track"

    RPR_ShowConsoleMsg("Processing: {}\n\n".format(range_desc))

    # Step 1: Get active comp items
    RPR_ShowConsoleMsg("Analyzing tracks...\n")
    ref_comp = get_active_comp_items(ref_track_id, time_range=ref_time_range)
    target_comp = get_active_comp_items(target_track_id, time_range=target_time_range,
                                         selected_ids=target_selected_ids)

    RPR_ShowConsoleMsg("  Reference items: {}\n".format(len(ref_comp)))
    RPR_ShowConsoleMsg("  Target items: {}\n".format(len(target_comp)))

    if not ref_comp or not target_comp:
        RPR_ShowMessageBox("No items found on one or both tracks.", "Error", 0)
        return

    # Step 2: Detect onsets
    # Mode affects onset detection sensitivity:
    #   Smart (0):   threshold_factor=4.0 (conservative, fewer onsets)
    #   Precise (100): threshold_factor=2.0 (sensitive, more onsets)
    # And minimum gap between detected onsets:
    #   Smart: 50ms min gap (skip fast subdivisions)
    #   Precise: 25ms min gap (catch every hit)
    onset_threshold = 4.0 - 2.0 * (mode / 100.0)
    onset_min_gap = 0.05 - 0.025 * (mode / 100.0)

    RPR_ShowConsoleMsg("Detecting onsets (sensitivity: {:.1f})...\n".format(onset_threshold))
    ref_onsets = detect_onsets(ref_comp, threshold_factor=onset_threshold,
                               min_onset_gap=onset_min_gap)
    target_onsets = detect_onsets(target_comp, threshold_factor=onset_threshold,
                                  min_onset_gap=onset_min_gap)

    RPR_ShowConsoleMsg("  Reference onsets: {}\n".format(len(ref_onsets)))
    RPR_ShowConsoleMsg("  Target onsets: {}\n".format(len(target_onsets)))

    if not ref_onsets or not target_onsets:
        RPR_ShowMessageBox("Could not detect onsets. Check audio files.", "Error", 0)
        return

    # Step 3: Match onsets
    # Mode affects match window:
    #   Smart: 45ms (tighter matching, only clear pairs)
    #   Precise: 70ms (wider, catch more pairs)
    match_window = 0.045 + 0.025 * (mode / 100.0)

    RPR_ShowConsoleMsg("Matching onsets (window: {:.0f}ms)...\n".format(match_window * 1000))
    matches = match_onsets(ref_onsets, target_onsets, max_match_window=match_window)
    RPR_ShowConsoleMsg("  Matched pairs: {}\n".format(len(matches)))

    significant = [m for m in matches if abs(m['diff_ms']) > threshold_ms]
    RPR_ShowConsoleMsg("  Above threshold ({}ms): {}\n".format(threshold_ms, len(significant)))

    if not significant:
        RPR_ShowMessageBox(
            "No timing differences above {}ms found.\n"
            "Tracks are already well aligned, or try a lower threshold.".format(threshold_ms),
            "Result", 0
        )
        return

    grouped = group_adjustments(significant, mode=mode)
    RPR_ShowConsoleMsg("  Before grouping: {} significant onsets\n".format(len(significant)))
    RPR_ShowConsoleMsg("  After grouping: {} adjustments (window: {:.0f}ms)\n\n".format(
        len(grouped), 300.0 * (1.0 - mode / 100.0)))

    # Step 4: Create aligned track
    RPR_ShowConsoleMsg("Creating aligned track...\n")
    RPR_Undo_BeginBlock()

    new_track_idx, new_track_id = create_aligned_track(target_idx, target_comp)
    RPR_ShowConsoleMsg("  Created track {}\n".format(new_track_idx + 1))

    # Step 5: Apply adjustments
    RPR_ShowConsoleMsg("Applying adjustments...\n")
    successful, moved_items = apply_adjustments(new_track_id, grouped)
    RPR_ShowConsoleMsg("  Adjustments applied: {}/{}\n".format(successful, len(grouped)))

    # Step 6: Fill gaps and create crossfades
    RPR_ShowConsoleMsg("Filling gaps and creating crossfades...\n")
    moved_ids = set(m['id'] for m in moved_items)
    gaps_filled = fill_gaps_and_crossfade(new_track_id, moved_ids, crossfade_ms=5)
    RPR_ShowConsoleMsg("  Gaps filled: {}\n".format(gaps_filled))

    RPR_UpdateArrange()
    RPR_Undo_EndBlock("Align Track to Reference V2.0", -1)

    # Report
    RPR_ShowConsoleMsg("\n=== DONE ===\n")
    RPR_ShowConsoleMsg("  Mode: {}\n".format(mode_label))
    RPR_ShowConsoleMsg("  Adjustments applied: {}/{}\n".format(successful, len(grouped)))
    RPR_ShowConsoleMsg("  Gaps filled: {}\n".format(gaps_filled))
    RPR_ShowConsoleMsg("  New track: {}\n".format(new_track_idx + 1))

    if significant:
        diffs = [abs(m['diff_ms']) for m in significant]
        avg = sum(diffs) / len(diffs)
        max_d = max(diffs)
        RPR_ShowConsoleMsg("  Avg correction: {:.1f}ms\n".format(avg))
        RPR_ShowConsoleMsg("  Max correction: {:.1f}ms\n".format(max_d))

    RPR_ShowMessageBox(
        "Alignment complete!\n\n"
        "Mode: {}\n"
        "Applied {} adjustments to new track {}.\n"
        "Gaps filled: {}\n"
        "Original track is untouched.".format(mode_label, successful, new_track_idx + 1, gaps_filled),
        "Align Track to Reference V2.0", 0
    )


main()
