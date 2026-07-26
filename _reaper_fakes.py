"""FakeReaper: in-memory stand-ins for REAPER APIs so ReaScript glue can be unit
tested without a live REAPER. Extend with RPR_* / audio-item fakes as needed."""


class FakeImGui:
    """Scripted ReaImGui stand-in. Widgets echo the passed-in value; Button returns
    True only for the label selected via the apply/cancel flags."""

    def __init__(self, apply=False, cancel=False, open_=1):
        self._apply = apply
        self._cancel = cancel
        self._open = open_
        self.ended = 0

    def CreateContext(self, label):
        return object()

    def Begin(self, ctx, name, p_open=None, flags=None):
        return True, self._open

    def End(self, ctx):
        self.ended += 1

    def InputInt(self, ctx, label, v, *a):
        return False, v

    def Combo(self, ctx, label, current, items, *a):
        return False, current

    def Checkbox(self, ctx, label, v, *a):
        return False, v

    def Button(self, ctx, label, *a):
        if label == "Apply":
            return self._apply
        if label == "Cancel":
            return self._cancel
        return False

    def SameLine(self, ctx, *a):
        return None

    def DestroyContext(self, ctx):
        return None


class FakeSource:
    def __init__(self, length=60.0, src_type="WAVE", filename="/fake/audio.wav",
                 samples=None, sr=22050):
        self.length = length
        self.src_type = src_type
        self.filename = filename
        self.samples = samples or []
        self.sr = sr


class FakeTake:
    def __init__(self, source, start_offs=0.0, playrate=1.0):
        self.source = source
        self.start_offs = start_offs
        self.playrate = playrate


class FakeItem:
    def __init__(self, track, position, length, take):
        self.track = track
        self.position = position
        self.length = length
        self.take = take
        self.selected = False
        self.fixed_lane = 0


class FakeTrack:
    def __init__(self, project):
        self.project = project
        self.items = []

    def add_item(self, position, length, start_offs=0.0, playrate=1.0,
                 src_type="WAVE", source_length=60.0, samples=None, sr=22050):
        src = FakeSource(length=source_length, src_type=src_type, samples=samples,
                         sr=sr)
        item = FakeItem(self, position, length,
                        FakeTake(src, start_offs=start_offs, playrate=playrate))
        self.items.append(item)
        self.project.items.append(item)
        return item


class FakeAccessor:
    def __init__(self, take):
        self.take = take
        self.destroyed = False


class FakeProject:
    """In-memory REAPER stand-in: linear tempo map, item/track graph, accessors.

    split_fail_within: if the requested split position falls closer than this to
    the item end, SplitMediaItem returns None. Models the REAPER behaviour the
    V2 audit flagged as unchecked (audit P1-4) so a regression test can exist.
    """

    def __init__(self, bpm=120.0, grid_division=0.25, sample_rate=96000):
        # Real REAPER snaps a split to the sample grid, so a piece never starts
        # exactly at the requested time. Modelling that here is what makes the
        # harness able to catch piece/note mismatches (it could not before).
        self.sample_rate = sample_rate
        self.bpm = bpm
        self.grid_division = grid_division
        self.tracks = []
        self.items = []
        self.time_selection = None
        self.undo_depth = 0
        self.undo_blocks = 0
        self.ui_refresh = 0
        self.accessors = []
        self.split_fail_within = 0.0
        # REAPER's "auto-crossfade on split" (on by default) pulls the new
        # right-hand piece back by the crossfade length, so its start is NOT
        # the requested cut time. Modelling it stops the harness from trusting
        # positions that a live run does not reproduce.
        self.split_autocrossfade = 0.0
        self.messages = []

    def add_track(self):
        tr = FakeTrack(self)
        self.tracks.append(tr)
        return tr

    def qn_to_time(self, qn):
        return qn * 60.0 / self.bpm

    def time_to_qn(self, t):
        return t * self.bpm / 60.0

    def render_timeline(self, sr, t0, t1):
        """Sum every item's audible source window into a project-time buffer.

        This is what makes attack-level assertions possible: geometry tests
        cannot tell a moved attack from a duplicated one.
        """
        n = int(round((t1 - t0) * sr))
        out = [0.0] * n
        for it in self.items:
            src = it.take.source
            i0 = max(0, int((it.position - t0) * sr))
            i1 = min(n, int((it.position + it.length - t0) * sr) + 1)
            for i in range(i0, i1):
                p = t0 + i / float(sr)
                if not (it.position - 1e-12 <= p < it.position + it.length):
                    continue
                st = it.take.start_offs + (p - it.position)
                idx = int(round(st * src.sr))
                if 0 <= idx < len(src.samples):
                    out[i] += src.samples[idx]
        return out


def install_reaper_fakes(module, project):
    """Bind RPR_* names the script calls onto `module`, backed by `project`."""
    p = project

    def sel_items():
        return [i for i in p.items if i.selected]

    module.RPR_CountSelectedMediaItems = lambda proj: len(sel_items())
    module.RPR_GetSelectedMediaItem = lambda proj, i: sel_items()[i]
    module.RPR_GetMediaItem_Track = lambda item: item.track
    module.RPR_GetTrackNumMediaItems = lambda tr: len(tr.items)
    module.RPR_GetTrackMediaItem = lambda tr, i: sorted(
        tr.items, key=lambda x: x.position)[i]
    module.RPR_GetActiveTake = lambda item: item.take
    module.RPR_GetMediaItemTake_Source = lambda take: take.source

    def get_item_val(item, key):
        return {"D_POSITION": item.position,
                "D_LENGTH": item.length,
                "I_FIXEDLANE": float(item.fixed_lane)}[key]

    def set_item_val(item, key, value):
        if key == "D_POSITION":
            item.position = value
        elif key == "D_LENGTH":
            item.length = value
        elif key == "I_FIXEDLANE":
            item.fixed_lane = int(value)
        return True

    def get_take_val(take, key):
        return {"D_STARTOFFS": take.start_offs, "D_PLAYRATE": take.playrate}[key]

    def set_take_val(take, key, value):
        if key == "D_STARTOFFS":
            take.start_offs = value
        elif key == "D_PLAYRATE":
            take.playrate = value
        return True

    module.RPR_GetMediaItemInfo_Value = get_item_val
    module.RPR_SetMediaItemInfo_Value = set_item_val
    module.RPR_GetMediaItemTakeInfo_Value = get_take_val
    module.RPR_SetMediaItemTakeInfo_Value = set_take_val

    def split(item, pos):
        if pos <= item.position + 1e-9:
            return None
        if pos >= item.position + item.length - p.split_fail_within - 1e-9:
            return None
        if p.sample_rate:
            pos = round(pos * p.sample_rate) / float(p.sample_rate)
        left_len = pos - item.position
        xf = min(p.split_autocrossfade, left_len, item.length - left_len)
        right = FakeItem(item.track, pos - xf, (item.length - left_len) + xf,
                         FakeTake(item.take.source,
                                  start_offs=item.take.start_offs + left_len - xf,
                                  playrate=item.take.playrate))
        right.fixed_lane = item.fixed_lane
        item.length = left_len
        item.track.items.append(right)
        p.items.append(right)
        return right

    module.RPR_SplitMediaItem = split

    def delete_item(tr, item):
        if item in tr.items:
            tr.items.remove(item)
        if item in p.items:
            p.items.remove(item)
        return True

    module.RPR_DeleteTrackMediaItem = delete_item

    def create_accessor(take):
        acc = FakeAccessor(take)
        p.accessors.append(acc)
        return acc

    def get_samples(acc, sr, nch, start_time, ns, buf):
        # Accessor time 0 is the take's first AUDIBLE sample, so reads are
        # offset by D_STARTOFFS. Without this, every take sharing a FakeSource
        # reads from the array start and a duplicated attack is invisible.
        # The accessor also RESAMPLES to the requested rate, so the fixture's
        # own sample rate must not leak into the time axis - indexing by output
        # sample number silently compressed every test's timeline.
        src = acc.take.source
        t0 = acc.take.start_offs + start_time
        for i in range(ns * nch):
            t = t0 + (i // nch) / float(sr)
            idx = int(round(t * src.sr))
            buf[i] = src.samples[idx] if 0 <= idx < len(src.samples) else 0.0
        return (1, buf)

    def destroy_accessor(acc):
        acc.destroyed = True

    module.RPR_CreateTakeAudioAccessor = create_accessor
    module.RPR_GetAudioAccessorSamples = get_samples
    module.RPR_DestroyAudioAccessor = destroy_accessor

    module.RPR_GetMediaSourceLength = lambda src, qn: (src.length, src, False)
    module.RPR_GetMediaSourceType = lambda src, buf, sz: (1, src, src.src_type, sz)
    module.RPR_GetMediaSourceFileName = lambda src, buf, sz: (1, src, src.filename, sz)

    module.RPR_TimeMap2_timeToQN = lambda proj, t: p.time_to_qn(t)
    module.RPR_TimeMap2_QNToTime = lambda proj, q: p.qn_to_time(q)
    module.RPR_GetSetProjectGrid = lambda proj, is_set, *a: (
        1, proj, is_set, p.grid_division, 0, 0.0)

    def loop_range(is_set, is_loop, start, end, allow):
        if p.time_selection is None:
            return (0, False, False, 0.0, 0.0, False)
        return (0, False, False, p.time_selection[0], p.time_selection[1], False)

    module.RPR_GetSet_LoopTimeRange = loop_range

    def undo_begin():
        p.undo_depth += 1

    def undo_end(name, flags):
        p.undo_depth -= 1
        p.undo_blocks += 1

    module.RPR_Undo_BeginBlock = undo_begin
    module.RPR_Undo_EndBlock = undo_end
    module.RPR_PreventUIRefresh = lambda n: setattr(p, "ui_refresh", p.ui_refresh + n)
    module.RPR_UpdateArrange = lambda: None
    module.RPR_MarkProjectDirty = lambda proj: None
    module.RPR_ShowMessageBox = lambda msg, title, kind: p.messages.append((title, msg))
    module.RPR_ShowConsoleMsg = lambda msg: p.messages.append(("console", msg))
    module.RPR_GetExtState = lambda sect, key: ""
    module.RPR_SetExtState = lambda sect, key, val, persist: None
    module.RPR_defer = lambda code: None
    module.RPR_GetResourcePath = lambda: "/fake/resource"
