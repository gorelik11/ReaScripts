"""An in-memory FX chain, enough of one to test the V1.0 -> V1.1 migration offline.

Local to this repository on purpose. `midi-composition/tests/_reaper_fakes.py` has 62 functions
and no TrackFX_* at all, it sits outside this branch, and it currently has uncommitted changes -
editing it would mix this feature into unrelated work in another project and leave the test
dependency somewhere the RCBitNova commit does not reach.

What it models, because that is what the migration's correctness is made of:
  - chain order, and what a move does to it
  - FX identity by GUID STRING (the raw TrackFX_GetFXGUID pointer does not survive a move, which
    is measured behaviour, not a guess)
  - parameter values, names, envelopes
  - enabled / offline
  - named config (pdc, modulation, oversampling) and pin mappings
  - undo block balance: opened, closed, and real undos
"""

N_DECLARED_V10 = 95
N_DECLARED_V11 = 175          # frozen: the shipped V1.1
N_DECLARED_V12 = 176          # V1.1's 175 plus the panel-state slider
N_DECLARED_V15 = 176          # V1.5 inherits the same declared block; only two RANGES widen
HOST_TAIL = ("Bypass", "Wet", "Delta")


class FakeParam:
    """A declared parameter. `normalized` is what the host stores; `value` is what the user sees.

    Keeping BOTH, over an explicit range, is the only way an offline test can tell a correct
    migration from a raw normalised copy - and telling those apart is the whole reason the
    V1.4 -> V1.5 migration needs a fake at all.

    `range` and NOT `lo`/`hi`, because that is exactly what reapy.FXParam exposes (measured: name,
    normalized, range, envelope, formatted, format_value, add_envelope). A fake with a friendlier
    API is how production code that cannot work live passes offline. __slots__ makes the absence
    real rather than a convention.
    """

    __slots__ = ("name", "normalized", "envelope", "_lo", "_hi", "step")

    def __init__(self, name, value=0.0, envelope=None, lo=0.0, hi=1.0, step=0.0):
        self.name, self.normalized, self.envelope = name, value, envelope
        self._lo, self._hi, self.step = lo, hi, step

    @property
    def range(self):
        return (self._lo, self._hi)

    @property
    def value(self):
        return self._lo + self.normalized * (self._hi - self._lo)

    @value.setter
    def value(self, v):
        v = min(max(v, self._lo), self._hi)
        if self.step:
            v = round(v / self.step) * self.step
        self.normalized = 0.0 if self._hi == self._lo else (v - self._lo) / (self._hi - self._lo)


class FakeFX:
    _next_guid = [0]

    def __init__(self, name, n_declared, chain):
        self.name = name
        self._chain = chain
        FakeFX._next_guid[0] += 1
        self.guid = "{%08X-0000-0000-0000-000000000000}" % FakeFX._next_guid[0]
        self.params = [FakeParam(f"P{i}") for i in range(n_declared)]
        # The three records the V1.4 -> V1.5 work addresses, with their real names and ranges.
        # Indices are MEASURED, from tests/fixtures/v14_declared_176.json.
        if n_declared >= 176:
            hi = 24000.0 if "V1.5" in name else 20000.0
            self.params[85] = FakeParam("HP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
            self.params[89] = FakeParam("LP Freq (Hz)", lo=20.0, hi=hi, step=1.0)
            self.params[175] = FakeParam("Panel: open dynamics card (0 none, 1..8 band)",
                                         lo=0.0, hi=8.0, step=1.0)
        for k, nm in enumerate(HOST_TAIL):
            self.params.append(FakeParam(nm))
        self.enabled = 1
        self.offline = 0
        self.config = {"pdc": "0", "instance_oversample_shift": "0"}
        self.pins = {}                      # (is_out, pin) -> mask; absent means default
        self.add_should_fail = False

    @property
    def n_params(self):
        return len(self.params)

    @property
    def index(self):
        return self._chain.fxs.index(self)

    def delete(self):
        self._chain.fxs.remove(self)


class FakeTrack:
    def __init__(self, names=()):
        self.id = "(MediaTrack*)0xFAKE"
        self.fxs = []
        self._add_hook = None
        for n in names:
            self.add_fx(n)

    @property
    def n_fxs(self):
        return len(self.fxs)

    def add_fx(self, name):
        if self._add_hook is not None:
            result = self._add_hook(name)
            if result is not None:
                return result                # None means "carry on and really add it"
        n = (N_DECLARED_V15 if ("V1.5" in name or "V1.4" in name or "V1.3" in name)
             else N_DECLARED_V12 if "V1.2" in name
             else N_DECLARED_V11 if "V1.1" in name else N_DECLARED_V10)
        fx = FakeFX(name.replace("JS: ", ""), n, self)
        self.fxs.append(fx)
        return fx


class FakeProject:
    def __init__(self, track):
        self.id = "(ReaProject*)0xFAKE"
        self.tracks = [track]


class FakeRPR:
    """Only the calls the migration makes, with the RETURN SHAPES REAPER actually uses: named
    config gives six elements with the value at [4], pin mappings give a list with retval at [0]."""

    def __init__(self, track):
        self.track = track
        self.undo_opened = 0
        self.undo_closed = 0
        self.undos = 0
        self.snapshots = []

    def _fx(self, idx):
        return self.track.fxs[idx]

    # The reapy tuple shape, positions and all: value at [0], lo at [4], hi at [5]. Production
    # code reads the range through THIS boundary and never off the param object, because the
    # param object it meets live has no .lo and no .hi.
    def TrackFX_GetParam(self, track_id, fx_index, i, _lo, _hi):
        p = self._fx(fx_index).params[i]
        return (p.value, 0, 0, 0) + p.range

    def TrackFX_SetParamNormalized(self, track_id, fx_index, i, v):
        self._fx(fx_index).params[i].normalized = v
        return True

    def TrackFX_GetFXGUID(self, tr, idx):
        return f"(GUID*){id(self._fx(idx)):#x}"          # a POINTER, like the real one

    def guidToString(self, ptr, _):
        for fx in self.track.fxs:
            if f"(GUID*){id(fx):#x}" == ptr:
                return [0, fx.guid]
        return [0, ""]

    def TrackFX_GetNamedConfigParm(self, tr, idx, key, _s, buf):
        fx = self._fx(idx)
        if key in fx.config:
            return [1, tr, idx, key, fx.config[key], buf]
        return [0, tr, idx, key, "", buf]

    def TrackFX_GetPinMappings(self, tr, idx, is_out, pin, high32):
        fx = self._fx(idx)
        return [fx.pins.get((is_out, pin), 1 << pin), tr, idx, is_out, pin, high32]

    def TrackFX_GetEnabled(self, tr, idx):
        return self._fx(idx).enabled

    def TrackFX_SetEnabled(self, tr, idx, on):
        self._fx(idx).enabled = on

    def TrackFX_GetOffline(self, tr, idx):
        return self._fx(idx).offline

    def TrackFX_SetOffline(self, tr, idx, off):
        self._fx(idx).offline = off

    def TrackFX_CopyToTrack(self, src_tr, src_idx, dst_tr, dst_idx, is_move):
        fxs = self.track.fxs
        fx = fxs.pop(src_idx)
        fxs.insert(dst_idx, fx)

    def Undo_BeginBlock2(self, _pr):
        self.undo_opened += 1
        self.snapshots.append(list(self.track.fxs))

    def Undo_EndBlock2(self, _pr, _desc, _flags):
        self.undo_closed += 1

    def Undo_DoUndo2(self, _pr):
        self.undos += 1
        if self.snapshots:
            self.track.fxs[:] = self.snapshots[-1]


def chain(*names):
    """A track plus the RPR shim that talks to it."""
    tr = FakeTrack(names)
    return tr, FakeRPR(tr)
