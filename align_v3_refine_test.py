"""
Test sub-hop onset refinement for V3.0.
Compares V2 hop-quantized onsets vs V3 sample-refined onsets.
Self-contained - no imports from other scripts.
"""
import struct
import math
import json
import os


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
                fmt_info['data_offset'] = f.tell()
                fmt_info['data_size'] = chunk_size
                break
            else:
                f.seek(chunk_size, 1)
        return fmt_info

    try:
        with open(filepath, 'rb') as f:
            fmt_info = parse_wav_header(f)
            if not fmt_info:
                return [], 0
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
            if is_float and bits == 32: sample_fmt = 'f'
            elif is_float and bits == 64: sample_fmt = 'd'
            elif not is_float and bits == 16: sample_fmt = 'h'
            elif not is_float and bits == 32: sample_fmt = 'i'
            elif not is_float and bits == 24: sample_fmt = None
            else: return [], sr
            samples = []
            frames_read = 0
            frame_counter = 0
            chunk_frames = 4096
            while frames_read < length_frames:
                read_count = min(chunk_frames, length_frames - frames_read)
                raw = f.read(read_count * frame_size)
                if not raw:
                    break
                actual_frames = len(raw) // frame_size
                if sample_fmt and bits != 24:
                    n_vals = actual_frames * n_ch
                    try:
                        all_vals = struct.unpack('<' + sample_fmt * n_vals, raw[:actual_frames * frame_size])
                    except struct.error:
                        break
                    for i in range(actual_frames):
                        if frame_counter % decimate == 0:
                            idx = i * n_ch
                            s = sum(all_vals[idx + ch] for ch in range(n_ch)) / n_ch
                            if sample_fmt == 'h': s /= 32768.0
                            elif sample_fmt == 'i': s /= 2147483648.0
                            samples.append(s)
                        frame_counter += 1
                else:
                    for i in range(actual_frames):
                        if frame_counter % decimate == 0:
                            s = 0.0
                            for ch in range(n_ch):
                                idx_b = (i * n_ch + ch) * 3
                                if idx_b + 3 <= len(raw):
                                    b = raw[idx_b:idx_b + 3]
                                    val = b[0] | (b[1] << 8) | (b[2] << 16)
                                    if val >= 0x800000: val -= 0x1000000
                                    s += val / 8388608.0
                            samples.append(s / n_ch)
                        frame_counter += 1
                frames_read += actual_frames
            return samples, out_sr
    except Exception:
        return [], 0


def detect_onsets_v2(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """V2 onset detection - hop=256, quantized timing."""
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
        if len(onset_strength) < 3:
            continue
        n = len(onset_strength)
        mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)
        if std_str == 0:
            continue
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
            abs_time = item['position'] + (peak * hop) / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
    all_onsets.sort()
    return all_onsets


def detect_onsets_v3(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
    """V3 onset detection - hop=256 for detection, then refine to sample level."""
    all_onsets = []
    all_strengths = []

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
        if len(onset_strength) < 3:
            continue
        n = len(onset_strength)
        mean_str = sum(onset_strength) / n
        variance = sum((x - mean_str) ** 2 for x in onset_strength) / n
        std_str = math.sqrt(variance)
        if std_str == 0:
            continue
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

        # REFINEMENT: For each detected peak, zoom in to find exact transient
        for pi, peak in enumerate(peaks):
            coarse_sample = (peak + 1) * hop
            # Look at +-1.5 hops around the coarse position
            window_start = max(0, coarse_sample - hop - hop // 2)
            window_end = min(len(samples), coarse_sample + hop + hop // 2)

            if window_end - window_start < 32:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time)
                    all_strengths.append(peak_strengths[pi])
                continue

            # Compute sample-level energy using small RMS window (~1ms)
            rms_win = max(8, int(0.001 * sr))
            local = samples[window_start:window_end]
            n_local = len(local)

            # Compute running energy
            local_energy = []
            for i in range(0, n_local - rms_win, rms_win // 2):
                e = sum(local[i + j] ** 2 for j in range(rms_win))
                local_energy.append(e)

            if len(local_energy) < 4:
                abs_time = item['position'] + coarse_sample / sr
                if abs_time <= item['position'] + item['length']:
                    all_onsets.append(abs_time)
                    all_strengths.append(peak_strengths[pi])
                continue

            # Find steepest energy rise
            max_deriv = -float('inf')
            max_deriv_idx = 0
            for i in range(1, len(local_energy)):
                deriv = local_energy[i] - local_energy[i - 1]
                if deriv > max_deriv:
                    max_deriv = deriv
                    max_deriv_idx = i

            # Convert back to sample position
            refined_sample = window_start + max_deriv_idx * (rms_win // 2)
            abs_time = item['position'] + refined_sample / sr

            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
                all_strengths.append(peak_strengths[pi])

    if all_onsets:
        paired = sorted(zip(all_onsets, all_strengths))
        all_onsets = [p[0] for p in paired]
        all_strengths = [p[1] for p in paired]
    return all_onsets, all_strengths


def match_onsets_v3(ref_onsets, ref_strengths, target_onsets, target_strengths,
                     max_match_window=0.055):
    """V3 matching - strength-weighted, unique (no double-matching)."""
    matches = []
    used_ref = set()

    for ti, t_onset in enumerate(target_onsets):
        best_idx = -1
        best_score = -float('inf')
        for ri, r_onset in enumerate(ref_onsets):
            if ri in used_ref:
                continue
            time_diff = abs(t_onset - r_onset)
            if time_diff > max_match_window:
                continue
            time_score = 1.0 - (time_diff / max_match_window)
            if ref_strengths[ri] > 0 and target_strengths[ti] > 0:
                ratio = min(ref_strengths[ri], target_strengths[ti]) / max(ref_strengths[ri], target_strengths[ti])
            else:
                ratio = 0.5
            score = time_score * 0.7 + ratio * 0.3
            if score > best_score:
                best_score = score
                best_idx = ri
        if best_idx >= 0 and best_score > 0.3:
            used_ref.add(best_idx)
            min_diff = t_onset - ref_onsets[best_idx]
            matches.append({
                'target_time': t_onset,
                'ref_time': ref_onsets[best_idx],
                'diff_sec': min_diff,
                'diff_ms': min_diff * 1000,
                'score': best_score
            })
    return matches


def run_test():
    results = {}
    ref_track = RPR_GetTrack(0, 0)
    target_track = RPR_GetTrack(0, 1)

    def get_items(track_id):
        n_items = RPR_GetTrackNumMediaItems(track_id)
        items = []
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
            items.append({
                'item_id': item_id, 'position': pos, 'length': length,
                'file': filename, 'offset': offset, 'index': i
            })
        return items

    ref_items = get_items(ref_track)
    target_items = get_items(target_track)

    # V2 detection (mode 100 settings)
    v2_ref = detect_onsets_v2(ref_items, threshold_factor=2.0, min_onset_gap=0.025)
    v2_target = detect_onsets_v2(target_items, threshold_factor=2.0, min_onset_gap=0.025)

    # V3 detection with refinement (same threshold settings)
    v3_ref, v3_ref_str = detect_onsets_v3(ref_items, threshold_factor=2.0, min_onset_gap=0.025)
    v3_target, v3_target_str = detect_onsets_v3(target_items, threshold_factor=2.0, min_onset_gap=0.025)

    # Compare onset positions
    results['v2'] = {
        'ref_onsets': [round(t, 5) for t in v2_ref],
        'target_onsets': [round(t, 5) for t in v2_target],
        'ref_count': len(v2_ref),
        'target_count': len(v2_target)
    }
    results['v3'] = {
        'ref_onsets': [round(t, 5) for t in v3_ref],
        'target_onsets': [round(t, 5) for t in v3_target],
        'ref_count': len(v3_ref),
        'target_count': len(v3_target)
    }

    # Onset-by-onset comparison (same count since same detection, just refined positions)
    if len(v2_ref) == len(v3_ref):
        ref_compare = []
        for v2_t, v3_t in zip(v2_ref, v3_ref):
            ref_compare.append({
                'v2': round(v2_t, 5),
                'v3': round(v3_t, 5),
                'shift_ms': round((v3_t - v2_t) * 1000, 3)
            })
        results['ref_comparison'] = ref_compare

    if len(v2_target) == len(v3_target):
        tgt_compare = []
        for v2_t, v3_t in zip(v2_target, v3_target):
            tgt_compare.append({
                'v2': round(v2_t, 5),
                'v3': round(v3_t, 5),
                'shift_ms': round((v3_t - v2_t) * 1000, 3)
            })
        results['target_comparison'] = tgt_compare

    # V2 matching
    v2_matches_raw = []
    for t_onset in v2_target:
        best_idx = -1
        best_diff = float('inf')
        for i, r_onset in enumerate(v2_ref):
            diff = abs(t_onset - r_onset)
            if diff < best_diff:
                best_diff = diff
                best_idx = i
        if best_idx >= 0 and best_diff < 0.07:
            min_diff = t_onset - v2_ref[best_idx]
            v2_matches_raw.append({
                'target': round(t_onset, 5),
                'ref': round(v2_ref[best_idx], 5),
                'diff_ms': round(min_diff * 1000, 3)
            })
    results['v2_matches'] = v2_matches_raw

    # V3 matching
    v3_matches = match_onsets_v3(v3_ref, v3_ref_str, v3_target, v3_target_str,
                                  max_match_window=0.07)
    results['v3_matches'] = [{
        'target': round(m['target_time'], 5),
        'ref': round(m['ref_time'], 5),
        'diff_ms': round(m['diff_ms'], 3),
        'score': round(m['score'], 3)
    } for m in v3_matches]

    output_path = os.path.expanduser('~/ReaScripts/align_v3_refine_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)
    RPR_ShowConsoleMsg("\nV3 refinement test done -> {}\n".format(output_path))

run_test()
