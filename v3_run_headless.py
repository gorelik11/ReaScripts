"""Run V3.0 alignment headlessly (no dialog) for automated testing.
Hardcoded: ref=track 1, target=track 2, threshold=15ms, mode=100 (precise)."""

import wave
import struct
import math

# Import all functions from V3.0 by re-defining them here
# (REAPER doesn't support imports between scripts)

def get_track_name(track_id):
    result = RPR_GetSetMediaTrackInfo_String(track_id, "P_NAME", "", False)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and item != "P_NAME" and item != "":
                if item.startswith("(MediaTrack*)") or item.startswith("0x"):
                    continue
                return item
    return ""

def get_source_filename(source):
    result = RPR_GetMediaSourceFileName(source, "", 512)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and ("/" in item or "\\" in item):
                return item
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
    full_take_threshold = median_len * 2
    comp_items = []
    for pos_key, group in position_groups.items():
        if len(group) > 3 and all(item['length'] > full_take_threshold for item in group): continue
        else: comp_items.extend(group)
    comp_items.sort(key=lambda x: x['position'])
    return comp_items


def detect_onsets(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    all_onsets = []; all_strengths = []
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
        peaks = []; peak_strengths = []
        for idx in range(1, len(onset_strength) - 1):
            if onset_strength[idx] > threshold:
                if (onset_strength[idx] > onset_strength[idx - 1] and
                        onset_strength[idx] >= onset_strength[idx + 1]):
                    if not peaks or (idx - peaks[-1]) >= min_dist_frames:
                        peaks.append(idx); peak_strengths.append(onset_strength[idx])
        rms_win = max(8, int(0.001 * sr)); rms_step = max(1, rms_win // 2)
        for pi, peak in enumerate(peaks):
            coarse_sample = (peak + 1) * hop
            window_start = max(0, coarse_sample - hop - hop // 2)
            window_end = min(len(samples), coarse_sample + hop + hop // 2)
            if window_end - window_start < rms_win * 2:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time); all_strengths.append(peak_strengths[pi])
                continue
            local = samples[window_start:window_end]; n_local = len(local)
            local_energy = []
            for i in range(0, n_local - rms_win, rms_step):
                e = sum(local[i + j] ** 2 for j in range(rms_win)); local_energy.append(e)
            if len(local_energy) < 4:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time); all_strengths.append(peak_strengths[pi])
                continue
            max_deriv = -float('inf'); max_deriv_idx = 0
            for i in range(1, len(local_energy)):
                deriv = local_energy[i] - local_energy[i - 1]
                if deriv > max_deriv: max_deriv = deriv; max_deriv_idx = i
            refined_sample = window_start + max_deriv_idx * rms_step
            abs_time = item['position'] + refined_sample / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time); all_strengths.append(peak_strengths[pi])
    if all_onsets:
        paired = sorted(zip(all_onsets, all_strengths))
        all_onsets = [p[0] for p in paired]; all_strengths = [p[1] for p in paired]
    return all_onsets, all_strengths


def match_onsets(ref_onsets, ref_strengths, target_onsets, target_strengths, max_match_window=0.055):
    matches = []; used_ref = set()
    for ti, t_onset in enumerate(target_onsets):
        best_idx = -1; best_score = -float('inf')
        for ri, r_onset in enumerate(ref_onsets):
            if ri in used_ref: continue
            time_diff = abs(t_onset - r_onset)
            if time_diff > max_match_window: continue
            time_score = (1.0 - (time_diff / max_match_window)) ** 0.5
            if ref_strengths[ri] > 0 and target_strengths[ti] > 0:
                ratio = min(ref_strengths[ri], target_strengths[ti]) / max(ref_strengths[ri], target_strengths[ti])
            else: ratio = 0.5
            score = time_score * 0.8 + ratio * 0.2
            if score > best_score: best_score = score; best_idx = ri
        if best_idx >= 0 and best_score > 0.2:
            used_ref.add(best_idx); min_diff = t_onset - ref_onsets[best_idx]
            matches.append({'target_time': t_onset, 'ref_time': ref_onsets[best_idx],
                            'diff_sec': min_diff, 'diff_ms': min_diff * 1000, 'score': best_score})
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
    RPR_GetSetMediaTrackInfo_String(new_track_id, "P_NAME", target_name + " (Aligned V3)", True)
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
        items.append({'id': item_id, 'pos': pos, 'length': length, 'index': i})
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
                    new_pos = nxt['pos'] - extend; new_offs = start_offs - extend
                    new_len = nxt['length'] + extend
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", new_offs)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos; nxt['length'] = new_len; gaps_filled += 1
                elif start_offs > 0:
                    new_pos = nxt['pos'] - start_offs; new_len = nxt['length'] + start_offs
                    RPR_SetMediaItemTakeInfo_Value(take, "D_STARTOFFS", 0)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos; nxt['length'] = new_len; gaps_filled += 1
        elif curr_was_moved and not nxt_was_moved:
            extend = gap + crossfade_sec; src_len = get_source_length(curr['id'])
            take = RPR_GetActiveTake(curr['id'])
            if take and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                if available >= extend:
                    new_len = curr['length'] + extend
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len; gaps_filled += 1
                elif available > 0:
                    new_len = curr['length'] + available
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len; gaps_filled += 1
        else:
            half_gap = gap / 2.0
            extend_right = half_gap + crossfade_sec / 2.0
            src_len = get_source_length(curr['id']); take_curr = RPR_GetActiveTake(curr['id'])
            if take_curr and src_len > 0:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_curr, "D_STARTOFFS")
                available = src_len - start_offs - curr['length']
                if available >= extend_right:
                    new_len = curr['length'] + extend_right
                    RPR_SetMediaItemInfo_Value(curr['id'], "D_LENGTH", new_len)
                    curr['length'] = new_len
            extend_left = half_gap + crossfade_sec / 2.0
            take_nxt = RPR_GetActiveTake(nxt['id'])
            if take_nxt:
                start_offs = RPR_GetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS")
                if start_offs >= extend_left:
                    new_pos = nxt['pos'] - extend_left; new_offs = start_offs - extend_left
                    new_len = nxt['length'] + extend_left
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_POSITION", new_pos)
                    RPR_SetMediaItemTakeInfo_Value(take_nxt, "D_STARTOFFS", new_offs)
                    RPR_SetMediaItemInfo_Value(nxt['id'], "D_LENGTH", new_len)
                    nxt['pos'] = new_pos; nxt['length'] = new_len
            gaps_filled += 1
    return gaps_filled


# ---- Headless main ----

ref_num = 1
target_num = 2
threshold_ms = 15
mode = 100  # Precise

ref_idx = ref_num - 1
target_idx = target_num - 1
ref_track_id = RPR_GetTrack(0, ref_idx)
target_track_id = RPR_GetTrack(0, target_idx)

ref_name = get_track_name(ref_track_id)
target_name = get_track_name(target_track_id)

RPR_ShowConsoleMsg("\n=== V3.0 Headless Test (Precise) ===\n")

ref_comp = get_active_comp_items(ref_track_id)
target_comp = get_active_comp_items(target_track_id)

RPR_ShowConsoleMsg("  Ref items: {}, Target items: {}\n".format(len(ref_comp), len(target_comp)))

onset_threshold = 4.0 - 2.0 * (mode / 100.0)
onset_min_gap = 0.05 - 0.025 * (mode / 100.0)
match_window = 0.045 + 0.025 * (mode / 100.0)

ref_onsets, ref_strengths = detect_onsets(ref_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)
target_onsets, target_strengths = detect_onsets(target_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)

RPR_ShowConsoleMsg("  Ref onsets: {}, Target onsets: {}\n".format(len(ref_onsets), len(target_onsets)))

matches = match_onsets(ref_onsets, ref_strengths, target_onsets, target_strengths, max_match_window=match_window)
significant = [m for m in matches if abs(m['diff_ms']) > threshold_ms]
grouped = group_adjustments(significant, mode=mode)

RPR_ShowConsoleMsg("  Matches: {}, Significant: {}, Grouped: {}\n".format(len(matches), len(significant), len(grouped)))

for adj in sorted(grouped, key=lambda x: x['target_time']):
    direction = "early" if adj['diff_ms'] > 0 else "late"
    RPR_ShowConsoleMsg("    {:.3f}s: {:.1f}ms {} (score: {:.2f})\n".format(
        adj['target_time'], abs(adj['diff_ms']), direction, adj.get('score', 0)))

RPR_Undo_BeginBlock()
new_track_idx, new_track_id = create_aligned_track(target_idx, target_comp)
successful, moved_items = apply_adjustments(new_track_id, grouped)
moved_ids = set(m['id'] for m in moved_items)
gaps_filled = fill_gaps_and_crossfade(new_track_id, moved_ids, crossfade_ms=5)
RPR_UpdateArrange()
RPR_Undo_EndBlock("V3.0 Headless Test (Precise)", -1)

RPR_ShowConsoleMsg("\n  Applied: {}/{}, Gaps filled: {}\n".format(successful, len(grouped), gaps_filled))
RPR_ShowConsoleMsg("  New track: {} (\"{}\")\n".format(new_track_idx + 1, target_name + " (Aligned V3)"))
RPR_ShowConsoleMsg("=== DONE ===\n")
