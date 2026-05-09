"""Run V2.0-style alignment headlessly for comparison with V3.0.
Same settings: ref=1, target=2, threshold=15ms, mode=100 (precise).
Uses V2 detection (no sub-hop) and V2 matching (simple nearest-neighbor)."""

import wave
import struct
import math

def get_track_name(track_id):
    result = RPR_GetSetMediaTrackInfo_String(track_id, "P_NAME", "", False)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and item != "P_NAME" and item != "":
                if item.startswith("(MediaTrack*)") or item.startswith("0x"): continue
                return item
    return ""

def get_source_filename(source):
    result = RPR_GetMediaSourceFileName(source, "", 512)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and ("/" in item or "\\" in item): return item
    return ""

def read_wav_segment(filepath, offset_sec, length_sec, target_sr=22050):
    def parse_wav_header(f):
        riff = f.read(4)
        if riff not in (b'RIFF', b'RF64'): return None
        f.read(4)
        if f.read(4) != b'WAVE': return None
        fmt_info = None; data_offset = None; data_size = None
        while True:
            chunk_header = f.read(8)
            if len(chunk_header) < 8: break
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
                fmt_info = {'channels': n_channels, 'sr': sr, 'bits': bits, 'is_float': is_float}
            elif chunk_id == b'data':
                data_offset = f.tell(); data_size = chunk_size; break
            else: f.seek(chunk_size, 1)
        if not fmt_info or data_offset is None: return None
        fmt_info['data_offset'] = data_offset; fmt_info['data_size'] = data_size
        return fmt_info
    def read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr):
        sr = fmt_info['sr']; n_ch = fmt_info['channels']; bits = fmt_info['bits']
        is_float = fmt_info['is_float']; bps = bits // 8; frame_size = bps * n_ch
        total_frames = fmt_info['data_size'] // frame_size
        start_frame = int(offset_sec * sr); length_frames = int(length_sec * sr)
        if start_frame >= total_frames: return [], sr
        if start_frame + length_frames > total_frames: length_frames = total_frames - start_frame
        decimate = max(1, sr // target_sr); out_sr = sr / decimate
        f.seek(fmt_info['data_offset'] + start_frame * frame_size)
        chunk_frames = 4096; samples = []; frames_read = 0; frame_counter = 0
        if is_float and bits == 32: sample_fmt = 'f'
        elif is_float and bits == 64: sample_fmt = 'd'
        elif not is_float and bits == 16: sample_fmt = 'h'
        elif not is_float and bits == 32: sample_fmt = 'i'
        elif not is_float and bits == 24: sample_fmt = None
        else: return [], sr
        while frames_read < length_frames:
            read_count = min(chunk_frames, length_frames - frames_read)
            raw = f.read(read_count * frame_size)
            if not raw: break
            actual_frames = len(raw) // frame_size
            if sample_fmt and bits != 24:
                n_vals = actual_frames * n_ch
                try: all_vals = struct.unpack('<' + sample_fmt * n_vals, raw[:actual_frames * frame_size])
                except struct.error: break
                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        idx = i * n_ch; s = 0.0
                        for ch in range(n_ch): s += all_vals[idx + ch]
                        s /= n_ch
                        if sample_fmt == 'h': s /= 32768.0
                        elif sample_fmt == 'i': s /= 2147483648.0
                        samples.append(s)
                    frame_counter += 1
            else:
                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        s = 0.0
                        for ch in range(n_ch):
                            idx = (i * n_ch + ch) * 3
                            if idx + 3 <= len(raw):
                                b = raw[idx:idx + 3]; val = b[0] | (b[1] << 8) | (b[2] << 16)
                                if val >= 0x800000: val -= 0x1000000
                                s += val / 8388608.0
                        samples.append(s / n_ch)
                    frame_counter += 1
            frames_read += actual_frames
        return samples, out_sr
    try:
        with wave.open(filepath, 'rb') as wf:
            sr = wf.getframerate(); sampwidth = wf.getsampwidth()
            n_ch = wf.getnchannels(); n_total = wf.getnframes()
            start_frame = int(offset_sec * sr); length_frames = int(length_sec * sr)
            if start_frame >= n_total: return [], sr
            if start_frame + length_frames > n_total: length_frames = n_total - start_frame
            decimate = max(1, sr // target_sr); out_sr = sr / decimate
            wf.setpos(start_frame); samples = []; chunk_frames = 4096
            frames_read = 0; frame_counter = 0
            while frames_read < length_frames:
                read_count = min(chunk_frames, length_frames - frames_read)
                raw = wf.readframes(read_count); actual = len(raw) // (sampwidth * n_ch)
                if actual == 0: break
                if sampwidth == 2:
                    vals = struct.unpack('<' + 'h' * (actual * n_ch), raw[:actual * sampwidth * n_ch])
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
                                idx = (i * n_ch + ch) * 3; b = raw[idx:idx + 3]
                                val = b[0] | (b[1] << 8) | (b[2] << 16)
                                if val >= 0x800000: val -= 0x1000000
                                s += val / 8388608.0
                            samples.append(s / n_ch)
                        frame_counter += 1
                elif sampwidth == 4:
                    vals = struct.unpack('<' + 'i' * (actual * n_ch), raw[:actual * sampwidth * n_ch])
                    for i in range(actual):
                        if frame_counter % decimate == 0:
                            s = sum(vals[i * n_ch + ch] for ch in range(n_ch))
                            samples.append(s / n_ch / 2147483648.0)
                        frame_counter += 1
                frames_read += actual
            if samples: return samples, out_sr
    except Exception: pass
    try:
        with open(filepath, 'rb') as f:
            fmt_info = parse_wav_header(f)
            if not fmt_info: return [], 0
            return read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr)
    except Exception: return [], 0

def get_active_comp_items(track_id):
    n_items = RPR_GetTrackNumMediaItems(track_id)
    if n_items == 0: return []
    all_items = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
        active_take = RPR_GetActiveTake(item_id)
        if not active_take: continue
        source = RPR_GetMediaItemTake_Source(active_take)
        if not source: continue
        filename = get_source_filename(source)
        offset = RPR_GetMediaItemTakeInfo_Value(active_take, "D_STARTOFFS")
        vol = RPR_GetMediaItemTakeInfo_Value(active_take, "D_VOL")
        all_items.append({'item_id': item_id, 'position': pos, 'length': length,
                          'file': filename, 'offset': offset, 'volume': vol, 'index': i})
    lengths = sorted([item['length'] for item in all_items])
    max_len = max(lengths); min_len = min(lengths)
    if max_len < min_len * 3: return all_items
    median_len = lengths[len(lengths) // 2]
    position_groups = {}
    for item in all_items:
        pos_key = round(item['position'], 1)
        if pos_key not in position_groups: position_groups[pos_key] = []
        position_groups[pos_key].append(item)
    full_take_threshold = median_len * 2; comp_items = []
    for pos_key, group in position_groups.items():
        if len(group) > 3 and all(item['length'] > full_take_threshold for item in group): continue
        else: comp_items.extend(group)
    comp_items.sort(key=lambda x: x['position'])
    return comp_items

def detect_onsets_v2(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """V2: hop=256, NO sub-hop refinement."""
    all_onsets = []
    for item in comp_items:
        if not item['file']: continue
        samples, sr = read_wav_segment(item['file'], item['offset'], item['length'])
        if len(samples) < 512 or sr == 0: continue
        hop = 256; frame_size = 512
        n_frames = (len(samples) - frame_size) // hop
        if n_frames < 3: continue
        energy = []
        for i in range(n_frames):
            start = i * hop; frame = samples[start:start + frame_size]
            e = sum(s * s for s in frame); energy.append(e)
        onset_strength = []
        for i in range(1, len(energy)):
            diff = energy[i] - energy[i - 1]; onset_strength.append(max(diff, 0.0))
        if len(onset_strength) < 3: continue
        n = len(onset_strength); mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)
        if std_str == 0: continue
        threshold = mean_str + threshold_factor * std_str
        min_dist_frames = int(min_onset_gap * sr / hop)
        peaks = []
        for idx in range(1, len(onset_strength) - 1):
            if onset_strength[idx] > threshold:
                if (onset_strength[idx] > onset_strength[idx - 1] and
                        onset_strength[idx] >= onset_strength[idx + 1]):
                    if not peaks or (idx - peaks[-1]) >= min_dist_frames:
                        peaks.append(idx)
        for peak in peaks:
            coarse_sample = (peak + 1) * hop
            abs_time = item['position'] + coarse_sample / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
    all_onsets.sort()
    return all_onsets

def match_onsets_v2(ref_onsets, target_onsets, max_match_window=0.055):
    """V2: Simple nearest-neighbor matching."""
    matches = []
    for t_onset in target_onsets:
        best_ref = None; best_diff = float('inf')
        for r_onset in ref_onsets:
            diff = abs(t_onset - r_onset)
            if diff < best_diff: best_diff = diff; best_ref = r_onset
        if best_ref is not None and best_diff <= max_match_window:
            min_diff = t_onset - best_ref
            matches.append({'target_time': t_onset, 'ref_time': best_ref,
                            'diff_sec': min_diff, 'diff_ms': min_diff * 1000})
    return matches

def group_adjustments(adjustments, mode=0):
    if not adjustments: return []
    min_gap = 0.30 * (1.0 - mode / 100.0)
    if min_gap < 0.001: return list(adjustments)
    groups = []; current_group = [adjustments[0]]
    for adj in adjustments[1:]:
        if adj['target_time'] - current_group[-1]['target_time'] < min_gap:
            current_group.append(adj)
        else: groups.append(current_group); current_group = [adj]
    groups.append(current_group)
    result = []
    for group in groups:
        best = max(group, key=lambda x: abs(x['diff_ms'])); result.append(best)
    return result

def create_aligned_track(target_track_idx, comp_items):
    RPR_InsertTrackAtIndex(target_track_idx + 1, True)
    RPR_TrackList_AdjustWindows(False)
    new_track_idx = target_track_idx + 1
    new_track_id = RPR_GetTrack(0, new_track_idx)
    target_track_id = RPR_GetTrack(0, target_track_idx)
    target_name = get_track_name(target_track_id)
    RPR_GetSetMediaTrackInfo_String(new_track_id, "P_NAME", target_name + " (Aligned V2)", True)
    for ci in comp_items:
        src_item = ci['item_id']
        pos = RPR_GetMediaItemInfo_Value(src_item, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(src_item, "D_LENGTH")
        new_item = RPR_AddMediaItemToTrack(new_track_id)
        RPR_SetMediaItemInfo_Value(new_item, "D_POSITION", pos)
        RPR_SetMediaItemInfo_Value(new_item, "D_LENGTH", length)
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
        active_take_idx = RPR_GetMediaItemInfo_Value(src_item, "I_CURTAKE")
        RPR_SetMediaItemInfo_Value(new_item, "I_CURTAKE", active_take_idx)
    return new_track_idx, new_track_id

def apply_adjustments(track_id, adjustments):
    n_items = RPR_GetTrackNumMediaItems(track_id)
    comp_tracking = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
        comp_tracking.append({'id': item_id, 'pos': pos, 'length': length})
    adjustments.sort(key=lambda x: x['target_time'], reverse=True)
    successful = 0; moved_items = []
    for adj in adjustments:
        onset_time = adj['target_time']; shift = -adj['diff_sec']
        split_time = onset_time - 0.005
        found = None
        for ci in comp_tracking:
            if ci['pos'] <= split_time < ci['pos'] + ci['length']:
                found = ci; break
        if not found: continue
        if split_time <= found['pos'] + 0.005 or split_time >= found['pos'] + found['length'] - 0.005:
            new_pos = found['pos'] + shift
            RPR_SetMediaItemInfo_Value(found['id'], "D_POSITION", new_pos)
            moved_items.append({'id': found['id'], 'shift': shift})
            found['pos'] = new_pos; successful += 1
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
    take = RPR_GetActiveTake(item_id)
    if not take: return 0
    source = RPR_GetMediaItemTake_Source(take)
    if not source: return 0
    result = RPR_GetMediaSourceLength(source, False)
    if isinstance(result, tuple):
        for val in result:
            if isinstance(val, float) and val > 0: return val
    elif isinstance(result, float): return result
    return 0

def fill_gaps_and_crossfade(track_id, moved_item_ids, crossfade_ms=5):
    crossfade_sec = crossfade_ms / 1000.0
    n_items = RPR_GetTrackNumMediaItems(track_id)
    if n_items < 2: return 0
    items = []
    for i in range(n_items):
        item_id = RPR_GetTrackMediaItem(track_id, i)
        pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
        length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
        items.append({'id': item_id, 'pos': pos, 'length': length})
    items.sort(key=lambda x: x['pos'])
    gaps_filled = 0
    for i in range(len(items) - 1):
        curr = items[i]; nxt = items[i + 1]
        curr_end = curr['pos'] + curr['length']; gap = nxt['pos'] - curr_end
        if gap <= 0.0001: continue
        curr_was_moved = curr['id'] in moved_item_ids
        nxt_was_moved = nxt['id'] in moved_item_ids
        if nxt_was_moved and not curr_was_moved:
            extend = gap + crossfade_sec
            take = RPR_GetActiveTake(nxt['id'])
            if take:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
                if start_offs >= extend:
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", nxt['pos'] - extend)
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", start_offs - extend)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", nxt['length'] + extend)
                    nxt['pos'] -= extend; nxt['length'] += extend; gaps_filled += 1
        elif curr_was_moved and not nxt_was_moved:
            extend = gap + crossfade_sec; src_len = get_source_length(curr['id'])
            take = RPR_GetActiveTake(curr['id'])
            if take and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                if available >= extend:
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", curr['length'] + extend)
                    curr['length'] += extend; gaps_filled += 1
        else:
            half_gap = gap / 2.0
            src_len = get_source_length(curr['id']); take_curr = RPR_GetActiveTake(curr['id'])
            if take_curr and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_curr, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                ext = half_gap + crossfade_sec / 2.0
                if available >= ext:
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", curr['length'] + ext)
                    curr['length'] += ext
            take_nxt = RPR_GetActiveTake(nxt['id'])
            if take_nxt:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS")
                ext = half_gap + crossfade_sec / 2.0
                if start_offs >= ext:
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", nxt['pos'] - ext)
                    RPR_SetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS", start_offs - ext)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", nxt['length'] + ext)
                    nxt['pos'] -= ext; nxt['length'] += ext
            gaps_filled += 1
    return gaps_filled

# ---- Main ----
mode = 100
ref_track_id = RPR_GetTrack(0, 0)
target_track_id = RPR_GetTrack(0, 1)

ref_comp = get_active_comp_items(ref_track_id)
target_comp = get_active_comp_items(target_track_id)

onset_threshold = 4.0 - 2.0 * (mode / 100.0)
onset_min_gap = 0.05 - 0.025 * (mode / 100.0)
match_window = 0.045 + 0.025 * (mode / 100.0)

ref_onsets = detect_onsets_v2(ref_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)
target_onsets = detect_onsets_v2(target_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)

RPR_ShowConsoleMsg("\n=== V2-style Headless (Precise) ===\n")
RPR_ShowConsoleMsg("  Ref onsets: {}, Target onsets: {}\n".format(len(ref_onsets), len(target_onsets)))

matches = match_onsets_v2(ref_onsets, target_onsets, max_match_window=match_window)
significant = [m for m in matches if abs(m['diff_ms']) > 15]
grouped = group_adjustments(significant, mode=mode)

RPR_ShowConsoleMsg("  Matches: {}, Significant: {}, Grouped: {}\n".format(len(matches), len(significant), len(grouped)))
for adj in sorted(grouped, key=lambda x: x['target_time']):
    direction = "early" if adj['diff_ms'] > 0 else "late"
    RPR_ShowConsoleMsg("    {:.3f}s: {:.1f}ms {}\n".format(adj['target_time'], abs(adj['diff_ms']), direction))

RPR_Undo_BeginBlock()
new_track_idx, new_track_id = create_aligned_track(1, target_comp)
successful, moved_items = apply_adjustments(new_track_id, grouped)
moved_ids = set(m['id'] for m in moved_items)
gaps_filled = fill_gaps_and_crossfade(new_track_id, moved_ids, crossfade_ms=5)
RPR_UpdateArrange()
RPR_Undo_EndBlock("V2 Headless Test (Precise)", -1)

RPR_ShowConsoleMsg("  Applied: {}/{}, Gaps: {}\n=== DONE ===\n".format(successful, len(grouped), gaps_filled))
