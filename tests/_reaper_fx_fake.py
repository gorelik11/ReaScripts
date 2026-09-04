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
HOST_TAIL = ("Bypass", "Wet", "Delta")


class FakeParam:
    def __init__(self, name, value=0.0, envelope=None):
        self.name = name
        self.normalized = value
        self.envelope = envelope


class FakeFX:
    _next_guid = [0]

    def __init__(self, name, n_declared, chain):
        self.name = name
        self._chain = chain
        FakeFX._next_guid[0] += 1
        self.guid = "{%08X-0000-0000-0000-000000000000}" % FakeFX._next_guid[0]
        self.params = [FakeParam(f"P{i}") for i in range(n_declared)]
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
        n = N_DECLARED_V12 if "V1.2" in name else N_DECLARED_V11 if "V1.1" in name else N_DECLARED_V10
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
