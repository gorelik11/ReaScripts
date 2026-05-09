"""
Headless analysis script - runs V2.0 onset detection and matching
without making any changes. Writes results to a file.
"""
import wave
import struct
import math
import json
import os

# Reuse V2.0 functions
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
        if is_float and bits == 32:
            sample_fmt = 'f'
        elif is_float and bits == 64:
            sample_fmt = 'd'
        elif not is_float and bits == 16:
            sample_fmt = 'h'
        elif not is_float and bits == 32:
            sample_fmt = 'i'
        elif not is_float and bits == 24:
            sample_fmt = None
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
                    all_vals = struct.unpack('<' + sample_fmt * n_vals, raw[:actual_frames * frame_size])
                except struct.error:
                    break
                for i in range(actual_frames):
                    if frame_counter % decimate == 0:
                        idx = i * n_ch
                        s = 0.0
                        for ch in range(n_ch):
                            s += all_vals[idx + ch]
                        s /= n_ch
                        if sample_fmt == 'h':
                            s /= 32768.0
                        elif sample_fmt == 'i':
                            s /= 2147483648.0
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
                                if val >= 0x800000:
                                    val -= 0x1000000
                                s += val / 8388608.0
                        samples.append(s / n_ch)
                    frame_counter += 1
            frames_read += actual_frames
        return samples, out_sr

    try:
        with open(filepath, 'rb') as f:
            fmt_info = parse_wav_header(f)
            if not fmt_info:
                return [], 0
            return read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr)
    except Exception:
        return [], 0


def detect_onsets(comp_items, threshold_factor=3.0, min_onset_gap=0.05):
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


def match_onsets(ref_onsets, target_onsets, max_match_window=0.055):
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
    if not adjustments:
        return []
    min_gap = 0.30 * (1.0 - mode / 100.0)
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


# Main analysis
def run_analysis():
    results = {}

    # Get tracks
    ref_track = RPR_GetTrack(0, 0)
    target_track = RPR_GetTrack(0, 1)

    # Get items for both tracks
    def get_items(track_id):
        n_items = RPR_GetTrackNumMediaItems(track_id)
        items = []
        for i in range(n_items):
            item_id = RPR_GetTrackMediaItem(track_id, i)
            pos = RPR_GetMediaItemInfo_Value(item_id, "D_POSITION")
            length = RPR_GetMediaItemInfo_Value(item_id, "D_LENGTH")
            active_take = RPR_GetActiveTake(item_id)
            if not active_take:
                continue
            source = RPR_GetMediaItemTake_Source(active_take)
            if not source:
                continue
            filename = get_source_filename(source)
            offset = RPR_GetMediaItemTakeInfo_Value(active_take, "D_STARTOFFS")
            items.append({
                'item_id': item_id,
                'position': pos,
                'length': length,
                'file': filename,
                'offset': offset,
                'index': i
            })
        return items

    ref_items = get_items(ref_track)
    target_items = get_items(target_track)

    results['ref_items'] = len(ref_items)
    results['target_items'] = len(target_items)
    results['ref_file'] = ref_items[0]['file'] if ref_items else ''
    results['target_file'] = target_items[0]['file'] if target_items else ''

    # Test multiple mode settings
    for mode in [0, 25, 50, 75, 100]:
        onset_threshold = 4.0 - 2.0 * (mode / 100.0)
        onset_min_gap = 0.05 - 0.025 * (mode / 100.0)
        match_window = 0.045 + 0.025 * (mode / 100.0)

        ref_onsets = detect_onsets(ref_items, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)
        target_onsets = detect_onsets(target_items, threshold_factor=onset_threshold, min_onset_gap=onset_min_gap)

        matches = match_onsets(ref_onsets, target_onsets, max_match_window=match_window)

        significant_15 = [m for m in matches if abs(m['diff_ms']) > 15]
        significant_10 = [m for m in matches if abs(m['diff_ms']) > 10]
        significant_5 = [m for m in matches if abs(m['diff_ms']) > 5]

        grouped = group_adjustments(significant_15, mode=mode)

        mode_results = {
            'onset_threshold': onset_threshold,
            'onset_min_gap_ms': onset_min_gap * 1000,
            'match_window_ms': match_window * 1000,
            'ref_onsets': len(ref_onsets),
            'target_onsets': len(target_onsets),
            'ref_onset_times': [round(t, 4) for t in ref_onsets],
            'target_onset_times': [round(t, 4) for t in target_onsets],
            'matched_pairs': len(matches),
            'matches_detail': [{'target': round(m['target_time'], 4), 'ref': round(m['ref_time'], 4), 'diff_ms': round(m['diff_ms'], 2)} for m in matches],
            'significant_gt15ms': len(significant_15),
            'significant_gt10ms': len(significant_10),
            'significant_gt5ms': len(significant_5),
            'grouped_15ms': len(grouped),
        }
        results['mode_{}'.format(mode)] = mode_results

    # Write results
    output_path = os.path.expanduser('~/ReaScripts/align_analysis_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    RPR_ShowConsoleMsg("\nAnalysis complete. Results written to: {}\n".format(output_path))

run_analysis()
