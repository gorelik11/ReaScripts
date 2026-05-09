"""Headless test: Run V3.0 onset detection + matching on Align Test project.
Tests both Smart (mode=0) and Precise (mode=100), outputs JSON results."""

import wave
import struct
import math
import json

# ---- Copy of V3.0 core functions ----

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
        if riff not in (b'RIFF', b'RF64'):
            return None
        f.read(4)
        if f.read(4) != b'WAVE':
            return None
        fmt_info = None
        data_offset = None
        data_size = None
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
                fmt_info = {'channels': n_channels, 'sr': sr, 'bits': bits, 'is_float': is_float}
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
        decimate = max(1, sr // target_sr)
        out_sr = sr / decimate
        f.seek(fmt_info['data_offset'] + start_frame * frame_size)
        chunk_frames = 4096
        samples = []
        frames_read = 0
        frame_counter = 0
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
                try:
                    all_vals = struct.unpack('<' + sample_fmt * n_vals, raw[:actual_frames * frame_size])
                except struct.error: break
                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        idx = i * n_ch
                        s = 0.0
                        for ch in range(n_ch):
                            s += all_vals[idx + ch]
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
                                b = raw[idx:idx + 3]
                                val = b[0] | (b[1] << 8) | (b[2] << 16)
                                if val >= 0x800000: val -= 0x1000000
                                s += val / 8388608.0
                        samples.append(s / n_ch)
                    frame_counter += 1
            frames_read += actual_frames
        return samples, out_sr

    try:
        with wave.open(filepath, 'rb') as wf:
            sr = wf.getframerate()
            sampwidth = wf.getsampwidth()
            n_ch = wf.getnchannels()
            n_total = wf.getnframes()
            start_frame = int(offset_sec * sr)
            length_frames = int(length_sec * sr)
            if start_frame >= n_total: return [], sr
            if start_frame + length_frames > n_total: length_frames = n_total - start_frame
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
                                idx = (i * n_ch + ch) * 3
                                b = raw[idx:idx + 3]
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
    return all_items


def detect_onsets_v3(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """V3: hop=256 + sub-hop sample-level refinement."""
    all_onsets = []
    all_strengths = []
    for item in comp_items:
        if not item['file']: continue
        samples, sr = read_wav_segment(item['file'], item['offset'], item['length'])
        if len(samples) < 512 or sr == 0: continue
        hop = 256
        frame_size = 512
        n_frames = (len(samples) - frame_size) // hop
        if n_frames < 3: continue
        energy = []
        for i in range(n_frames):
            start = i * hop
            frame = samples[start:start + frame_size]
            e = sum(s * s for s in frame)
            energy.append(e)
        onset_strength = []
        for i in range(1, len(energy)):
            diff = energy[i] - energy[i - 1]
            onset_strength.append(max(diff, 0.0))
        if len(onset_strength) < 3: continue
        n = len(onset_strength)
        mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)
        if std_str == 0: continue
        threshold = mean_str + threshold_factor * std_str
        min_dist_frames = int(min_onset_gap * sr / hop)
        peaks = []
        peak_strengths = []
        for idx in range(1, len(onset_strength) - 1):
            if onset_strength[idx] > threshold:
                if (onset_strength[idx] > onset_strength[idx - 1] and
                        onset_strength[idx] >= onset_strength[idx + 1]):
                    if not peaks or (idx - peaks[-1]) >= min_dist_frames:
                        peaks.append(idx)
                        peak_strengths.append(onset_strength[idx])
        # Sub-hop refinement
        rms_win = max(8, int(0.001 * sr))
        rms_step = max(1, rms_win // 2)
        for pi, peak in enumerate(peaks):
            coarse_sample = (peak + 1) * hop
            window_start = max(0, coarse_sample - hop - hop // 2)
            window_end = min(len(samples), coarse_sample + hop + hop // 2)
            if window_end - window_start < rms_win * 2:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time)
                    all_strengths.append(peak_strengths[pi])
                continue
            local = samples[window_start:window_end]
            n_local = len(local)
            local_energy = []
            for i in range(0, n_local - rms_win, rms_step):
                e = sum(local[i + j] ** 2 for j in range(rms_win))
                local_energy.append(e)
            if len(local_energy) < 4:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time)
                    all_strengths.append(peak_strengths[pi])
                continue
            max_deriv = -float('inf')
            max_deriv_idx = 0
            for i in range(1, len(local_energy)):
                deriv = local_energy[i] - local_energy[i - 1]
                if deriv > max_deriv:
                    max_deriv = deriv
                    max_deriv_idx = i
            refined_sample = window_start + max_deriv_idx * rms_step
            abs_time = item['position'] + refined_sample / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
                all_strengths.append(peak_strengths[pi])
    if all_onsets:
        paired = sorted(zip(all_onsets, all_strengths))
        all_onsets = [p[0] for p in paired]
        all_strengths = [p[1] for p in paired]
    return all_onsets, all_strengths


def detect_onsets_v2(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """V2: hop=256, no sub-hop refinement (for comparison)."""
    all_onsets = []
    all_strengths = []
    for item in comp_items:
        if not item['file']: continue
        samples, sr = read_wav_segment(item['file'], item['offset'], item['length'])
        if len(samples) < 512 or sr == 0: continue
        hop = 256
        frame_size = 512
        n_frames = (len(samples) - frame_size) // hop
        if n_frames < 3: continue
        energy = []
        for i in range(n_frames):
            start = i * hop
            frame = samples[start:start + frame_size]
            e = sum(s * s for s in frame)
            energy.append(e)
        onset_strength = []
        for i in range(1, len(energy)):
            diff = energy[i] - energy[i - 1]
            onset_strength.append(max(diff, 0.0))
        if len(onset_strength) < 3: continue
        n = len(onset_strength)
        mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)
        if std_str == 0: continue
        threshold = mean_str + threshold_factor * std_str
        min_dist_frames = int(min_onset_gap * sr / hop)
        peaks = []
        peak_strengths = []
        for idx in range(1, len(onset_strength) - 1):
            if onset_strength[idx] > threshold:
                if (onset_strength[idx] > onset_strength[idx - 1] and
                        onset_strength[idx] >= onset_strength[idx + 1]):
                    if not peaks or (idx - peaks[-1]) >= min_dist_frames:
                        peaks.append(idx)
                        peak_strengths.append(onset_strength[idx])
        for pi, peak in enumerate(peaks):
            coarse_sample = (peak + 1) * hop
            abs_time = item['position'] + coarse_sample / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
                all_strengths.append(peak_strengths[pi])
    if all_onsets:
        paired = sorted(zip(all_onsets, all_strengths))
        all_onsets = [p[0] for p in paired]
        all_strengths = [p[1] for p in paired]
    return all_onsets, all_strengths


def match_onsets_v3(ref_onsets, ref_strengths, target_onsets, target_strengths, max_match_window=0.055):
    """V3: Strength-weighted, unique matching."""
    matches = []
    used_ref = set()
    for ti, t_onset in enumerate(target_onsets):
        best_idx = -1
        best_score = -float('inf')
        for ri, r_onset in enumerate(ref_onsets):
            if ri in used_ref: continue
            time_diff = abs(t_onset - r_onset)
            if time_diff > max_match_window: continue
            time_score = (1.0 - (time_diff / max_match_window)) ** 0.5
            if ref_strengths[ri] > 0 and target_strengths[ti] > 0:
                ratio = min(ref_strengths[ri], target_strengths[ti]) / max(ref_strengths[ri], target_strengths[ti])
            else:
                ratio = 0.5
            score = time_score * 0.8 + ratio * 0.2
            if score > best_score:
                best_score = score
                best_idx = ri
        if best_idx >= 0 and best_score > 0.2:
            used_ref.add(best_idx)
            min_diff = t_onset - ref_onsets[best_idx]
            matches.append({'target_time': t_onset, 'ref_time': ref_onsets[best_idx],
                            'diff_ms': round(min_diff * 1000, 3), 'score': round(best_score, 3)})
    return matches


def match_onsets_v2(ref_onsets, target_onsets, max_match_window=0.055):
    """V2: Simple nearest-neighbor matching (for comparison)."""
    matches = []
    for t_onset in target_onsets:
        best_ref = None
        best_diff = float('inf')
        for r_onset in ref_onsets:
            diff = abs(t_onset - r_onset)
            if diff < best_diff:
                best_diff = diff
                best_ref = r_onset
        if best_ref is not None and best_diff <= max_match_window:
            min_diff = t_onset - best_ref
            matches.append({'target_time': t_onset, 'ref_time': best_ref,
                            'diff_ms': round(min_diff * 1000, 3)})
    return matches


def group_adjustments(adjustments, mode=0):
    if not adjustments: return []
    min_gap = 0.30 * (1.0 - mode / 100.0)
    if min_gap < 0.001: return list(adjustments)
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


# ---- Main test ----

ref_track_id = RPR_GetTrack(0, 0)  # Track 1
target_track_id = RPR_GetTrack(0, 1)  # Track 2

ref_comp = get_active_comp_items(ref_track_id)
target_comp = get_active_comp_items(target_track_id)

results = {}

for mode in [0, 100]:
    onset_threshold = 4.0 - 2.0 * (mode / 100.0)
    onset_min_gap = 0.05 - 0.025 * (mode / 100.0)
    match_window = 0.045 + 0.025 * (mode / 100.0)

    # V2 detection (no refinement)
    v2_ref_onsets, v2_ref_str = detect_onsets_v2(ref_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)
    v2_tgt_onsets, v2_tgt_str = detect_onsets_v2(target_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)

    # V3 detection (sub-hop refinement)
    v3_ref_onsets, v3_ref_str = detect_onsets_v3(ref_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)
    v3_tgt_onsets, v3_tgt_str = detect_onsets_v3(target_comp, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)

    # V2 matching (simple nearest neighbor)
    v2_matches = match_onsets_v2(v2_ref_onsets, v2_tgt_onsets, max_match_window=match_window)
    v2_significant = [m for m in v2_matches if abs(m['diff_ms']) > 15]
    v2_grouped = group_adjustments(v2_significant, mode=mode)

    # V3 matching (strength-weighted unique)
    v3_matches = match_onsets_v3(v3_ref_onsets, v3_ref_str, v3_tgt_onsets, v3_tgt_str, max_match_window=match_window)
    v3_significant = [m for m in v3_matches if abs(m['diff_ms']) > 15]
    v3_grouped = group_adjustments(v3_significant, mode=mode)

    mode_key = "smart" if mode == 0 else "precise"
    results[mode_key] = {
        "mode": mode,
        "onset_threshold": onset_threshold,
        "match_window_ms": match_window * 1000,
        "v2": {
            "ref_onsets": len(v2_ref_onsets),
            "target_onsets": len(v2_tgt_onsets),
            "matches": len(v2_matches),
            "significant": len(v2_significant),
            "grouped": len(v2_grouped),
            "match_details": v2_matches,
            "grouped_details": v2_grouped
        },
        "v3": {
            "ref_onsets": len(v3_ref_onsets),
            "target_onsets": len(v3_tgt_onsets),
            "matches": len(v3_matches),
            "significant": len(v3_significant),
            "grouped": len(v3_grouped),
            "match_details": v3_matches,
            "grouped_details": v3_grouped,
            "ref_onsets_list": [round(o, 5) for o in v3_ref_onsets],
            "target_onsets_list": [round(o, 5) for o in v3_tgt_onsets]
        }
    }

output_path = "/Users/dimagorelik/ReaScripts/v3_test_results.json"
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2)

RPR_ShowConsoleMsg("\n=== V3 Headless Test Complete ===\n")
for mode_key in ["smart", "precise"]:
    r = results[mode_key]
    RPR_ShowConsoleMsg("\nMode: {} (threshold={:.1f}, window={:.0f}ms)\n".format(
        mode_key, r["onset_threshold"], r["match_window_ms"]))
    RPR_ShowConsoleMsg("  V2: {} onsets ref, {} tgt -> {} matches, {} sig, {} grouped\n".format(
        r["v2"]["ref_onsets"], r["v2"]["target_onsets"], r["v2"]["matches"],
        r["v2"]["significant"], r["v2"]["grouped"]))
    RPR_ShowConsoleMsg("  V3: {} onsets ref, {} tgt -> {} matches, {} sig, {} grouped\n".format(
        r["v3"]["ref_onsets"], r["v3"]["target_onsets"], r["v3"]["matches"],
        r["v3"]["significant"], r["v3"]["grouped"]))

RPR_ShowConsoleMsg("\nResults saved to: {}\n".format(output_path))
