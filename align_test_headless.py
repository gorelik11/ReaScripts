"""
Headless alignment test - runs V2.0 alignment at mode 100 without dialog.
Writes detailed results to file for analysis.
"""
import wave
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

def get_track_name(track_id):
    result = RPR_GetSetMediaTrackInfo_String(track_id, "P_NAME", "", False)
    if isinstance(result, tuple):
        for item in result:
            if isinstance(item, str) and item != "P_NAME" and item != "":
                if item.startswith("(MediaTrack*)") or item.startswith("0x"):
                    continue
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
        with open(filepath, 'rb') as f:
            fmt_info = parse_wav_header(f)
            if not fmt_info: return [], 0
            return read_and_decimate(f, fmt_info, offset_sec, length_sec, target_sr)
    except Exception:
        return [], 0


def read_wav_segment_fullrate(filepath, offset_sec, length_sec):
    """Read at full sample rate - used for cross-correlation refinement."""
    return read_wav_segment(filepath, offset_sec, length_sec, target_sr=1000000)


def detect_onsets_v3(comp_items, threshold_factor=3.0, min_onset_gap=0.05, hop=256):
    """V3 onset detection with configurable hop size for better timing resolution."""
    all_onsets = []
    # Also return onset strengths for matching quality
    all_onset_strengths = []

    for item in comp_items:
        if not item['file']:
            continue
        samples, sr = read_wav_segment(item['file'], item['offset'], item['length'])
        if len(samples) < 512 or sr == 0:
            continue
        frame_size = min(512, hop * 2)
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
        for pi, peak in enumerate(peaks):
            abs_time = item['position'] + (peak * hop) / sr
            if abs_time <= item['position'] + item['length']:
                all_onsets.append(abs_time)
                all_onset_strengths.append(peak_strengths[pi])

    # Sort by time
    if all_onsets:
        paired = sorted(zip(all_onsets, all_onset_strengths))
        all_onsets = [p[0] for p in paired]
        all_onset_strengths = [p[1] for p in paired]
    return all_onsets, all_onset_strengths


def cross_correlate_refine(ref_file, ref_offset, target_file, target_offset,
                            ref_onset_time, target_onset_time, window_sec=0.03, max_lag_sec=0.07):
    """Refine onset match timing using cross-correlation at full sample rate.

    Reads a small window around each onset and finds the lag that maximizes
    cross-correlation. Returns refined timing difference in seconds.
    """
    # Read windows around onsets at higher sample rate (48kHz is enough)
    refine_sr = 48000
    half_window = window_sec

    ref_read_start = max(0, (ref_onset_time - ref_offset) - half_window)
    ref_samples, ref_sr = read_wav_segment(ref_file, ref_offset + ref_read_start,
                                            half_window * 2, target_sr=refine_sr)

    target_read_start = max(0, (target_onset_time - target_offset) - half_window)
    target_samples, target_sr = read_wav_segment(target_file, target_offset + target_read_start,
                                                  half_window * 2, target_sr=refine_sr)

    if len(ref_samples) < 10 or len(target_samples) < 10 or ref_sr == 0:
        return target_onset_time - ref_onset_time  # Return original diff

    effective_sr = ref_sr
    max_lag_samples = int(max_lag_sec * effective_sr)

    # Cross-correlation with limited lag range
    best_lag = 0
    best_corr = -float('inf')

    ref_len = len(ref_samples)
    tgt_len = len(target_samples)

    for lag in range(-max_lag_samples, max_lag_samples + 1):
        corr = 0.0
        count = 0
        for i in range(ref_len):
            j = i + lag
            if 0 <= j < tgt_len:
                corr += ref_samples[i] * target_samples[j]
                count += 1
        if count > 0:
            corr /= count
        if corr > best_corr:
            best_corr = corr
            best_lag = lag

    # Convert lag to time
    lag_sec = best_lag / effective_sr

    # The refined difference: positive = target is after ref
    # Original onset positions give a coarse estimate
    # Cross-correlation gives a fine correction
    coarse_diff = target_onset_time - ref_onset_time

    # The lag tells us how much to shift target to align with ref
    # If lag > 0, target signal comes after ref signal
    refined_diff = (target_read_start + target_offset) - (ref_read_start + ref_offset) + lag_sec / effective_sr

    # Actually simpler: the cross-correlation lag directly refines the timing
    # lag > 0 means target is shifted right relative to ref in the correlation
    # So the refined diff is: coarse_diff adjusted by the lag
    # If the coarse diff was the hop-quantized version, and xcorr finds a lag of N samples,
    # the refined position adjustment is based on the lag

    # Let's just return the lag-based refinement
    # The ref window starts at ref_onset_time - half_window (project time)
    # The target window starts at target_onset_time - half_window (project time)
    # xcorr lag of N means target is N samples late relative to ref in the windows
    refined_diff_sec = (target_onset_time - ref_onset_time) - (best_lag / effective_sr)
    # Wait, if lag>0 means shifting target right aligns better, target is early by lag
    # If lag<0, target is late by |lag|
    # Actually: xcorr(ref, target)[lag] measures similarity when target is shifted by lag
    # If best_lag > 0, the best alignment is when target is shifted right by lag samples
    # This means target is currently lag samples too early (or ref is lag samples too late)
    # So the actual timing difference target - ref should be adjusted

    # Let me think simply:
    # Both windows are centered on their respective detected onsets
    # If xcorr peak is at lag=0, the onsets are at the same position within their windows
    # If peak is at lag=+5, target window needs to shift right by 5 to align
    #   -> target's onset is 5 samples earlier than ref's onset (relative to window centers)
    #   -> actual diff is slightly more negative (target is earlier)

    # refined_diff = coarse_diff + (lag / sr)  ... hmm
    # Actually the windows are read starting from onset - half_window
    # xcorr lag=0 means the window positions are aligned correctly
    # lag=+N means we need to read target N samples later for best match
    # So target's true onset is N/sr later than detected
    # refined target_onset = target_onset_time + lag/sr
    # refined diff = (target_onset + lag/sr) - ref_onset

    return coarse_diff + (best_lag / effective_sr)


def match_onsets_v3(ref_onsets, ref_strengths, target_onsets, target_strengths,
                     max_match_window=0.055):
    """V3 matching with onset strength weighting."""
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
            # Score: prioritize close matches, weight by onset strength similarity
            time_score = 1.0 - (time_diff / max_match_window)
            # Strength similarity (0-1, 1 = identical strength)
            if ref_strengths[ri] > 0 and target_strengths[ti] > 0:
                ratio = min(ref_strengths[ri], target_strengths[ti]) / max(ref_strengths[ri], target_strengths[ti])
            else:
                ratio = 0.5
            score = time_score * 0.7 + ratio * 0.3
            if score > best_score:
                best_score = score
                best_idx = ri

        if best_idx >= 0:
            used_ref.add(best_idx)
            min_diff = t_onset - ref_onsets[best_idx]
            matches.append({
                'target_time': t_onset,
                'ref_time': ref_onsets[best_idx],
                'diff_sec': min_diff,
                'diff_ms': min_diff * 1000,
                'match_score': best_score,
                'target_strength': target_strengths[ti],
                'ref_strength': ref_strengths[best_idx]
            })

    return matches


# Main test
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

    # V2.0 approach (mode 100): hop=256, threshold=2.0
    v2_ref_onsets, _ = detect_onsets_v3(ref_items, threshold_factor=2.0, min_onset_gap=0.025, hop=256)
    v2_target_onsets, _ = detect_onsets_v3(target_items, threshold_factor=2.0, min_onset_gap=0.025, hop=256)

    # V3.0 approach: hop=64 for finer resolution
    v3_ref_onsets, v3_ref_str = detect_onsets_v3(ref_items, threshold_factor=2.0, min_onset_gap=0.025, hop=64)
    v3_target_onsets, v3_target_str = detect_onsets_v3(target_items, threshold_factor=2.0, min_onset_gap=0.025, hop=64)

    results['v2_hop256'] = {
        'ref_onsets': [round(t, 4) for t in v2_ref_onsets],
        'target_onsets': [round(t, 4) for t in v2_target_onsets],
        'ref_count': len(v2_ref_onsets),
        'target_count': len(v2_target_onsets),
        'timing_resolution_ms': round(256 / 24000.0 * 1000, 2)
    }

    results['v3_hop64'] = {
        'ref_onsets': [round(t, 4) for t in v3_ref_onsets],
        'target_onsets': [round(t, 4) for t in v3_target_onsets],
        'ref_count': len(v3_ref_onsets),
        'target_count': len(v3_target_onsets),
        'timing_resolution_ms': round(64 / 24000.0 * 1000, 2)
    }

    # V3 matching with strength weighting
    v3_matches = match_onsets_v3(v3_ref_onsets, v3_ref_str, v3_target_onsets, v3_target_str,
                                  max_match_window=0.07)
    results['v3_matches'] = [{
        'target': round(m['target_time'], 4),
        'ref': round(m['ref_time'], 4),
        'diff_ms': round(m['diff_ms'], 2),
        'score': round(m['match_score'], 3)
    } for m in v3_matches]

    # Cross-correlation refinement on V3 matches
    if ref_items and target_items:
        ref_file = ref_items[0]['file']
        ref_offset = ref_items[0]['offset']
        target_file = target_items[0]['file']
        target_offset = target_items[0]['offset']

        refined = []
        for m in v3_matches:
            try:
                refined_diff = cross_correlate_refine(
                    ref_file, ref_offset, target_file, target_offset,
                    m['ref_time'], m['target_time'],
                    window_sec=0.02, max_lag_sec=0.07
                )
                refined.append({
                    'target': round(m['target_time'], 4),
                    'ref': round(m['ref_time'], 4),
                    'coarse_diff_ms': round(m['diff_ms'], 2),
                    'refined_diff_ms': round(refined_diff * 1000, 2)
                })
            except Exception as e:
                refined.append({
                    'target': round(m['target_time'], 4),
                    'ref': round(m['ref_time'], 4),
                    'coarse_diff_ms': round(m['diff_ms'], 2),
                    'error': str(e)
                })
        results['xcorr_refined'] = refined

    output_path = os.path.expanduser('~/ReaScripts/align_v3_test_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    RPR_ShowConsoleMsg("\nV3 test complete. Results: {}\n".format(output_path))

run_test()
