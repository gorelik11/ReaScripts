"""Replace a V1.0 instance with a V1.1 instance in place, preserving its settings.

The only supported migration. V1.1 is a new file, so an existing project simply reopens V1.0 and
is unaffected - this is for moving a project forward deliberately.

Everything below is measured on this machine (reapy, live REAPER, 2026-08-19/22), not assumed:

1. The host reports 98 parameters for V1.0 - 95 declared, then Bypass, Wet, Delta. V1.1 reports
   178. Only the DECLARED block is a prefix, so an index-wise copy across the whole list lands the
   host tail in the new bands.
2. `slider1` is ALSO named "Bypass". A name search finds declared parameter 0, not host parameter
   95, and the real host bypass is never copied. The tail is addressed POSITIONALLY.
3. `TrackFX_GetFXGUID` returns a POINTER that does NOT survive TrackFX_CopyToTrack - after a move
   the destination slot reports a different value. Identity is `guidToString(...)`, which does
   survive. A name search is not identity either: a track may hold more than one RCBitNova.
4. `TrackFX_GetNamedConfigParm` returns SIX elements, value at [4].
5. `TrackFX_GetPinMappings` takes five arguments and returns a list, retval at [0]; the default
   map routes pin k to bit k.

Refused: automation, parameter modulation, non-default pin maps, instance oversampling, an
ambiguous chain (two V1.0s). NOT detected and therefore NOT migrated: parameter aliases - said
plainly rather than described as refused.
"""

N_DECLARED_V10 = 95
N_DECLARED_V11 = 175
HOST_TAIL = ("Bypass", "Wet", "Delta")
UNDETECTED = "parameter aliases are not migrated and cannot be detected"


def _cfg(rpr, track, idx, key, buf=64):
    r = rpr.TrackFX_GetNamedConfigParm(track.id, idx, key, "", buf)
    return bool(r[0]), r[4]


def _guid(rpr, track, idx):
    """The GUID STRING. The raw pointer does not survive a move."""
    return rpr.guidToString(rpr.TrackFX_GetFXGUID(track.id, idx), "")[1]


def _index_of_guid(rpr, track, guid):
    for i in range(track.n_fxs):
        if _guid(rpr, track, i) == guid:
            return i
    return None


def _has_modulation(rpr, track, idx, n_declared):
    for i in range(n_declared):
        ok, value = _cfg(rpr, track, idx, f"param.{i}.mod.active", 32)
        if ok and value not in ("", "0"):
            return True
    return False


def _nondefault_pins(rpr, track, idx, n_channels=2):
    for pin in range(n_channels):
        for is_out in (0, 1):
            if rpr.TrackFX_GetPinMappings(track.id, idx, is_out, pin, 0)[0] != (1 << pin):
                return True
    return False


def _oversampled(rpr, track, idx):
    ok, value = _cfg(rpr, track, idx, "instance_oversample_shift", 32)
    return ok and value not in ("", "0")


def migrate_chain(track, rpr, project, dry_run=True):
    """The whole algorithm, with the host injected so it can be driven by a fake."""
    srcs = [fx for fx in track.fxs if "RCBitNova V1.0" in fx.name]
    if not srcs:
        return "no V1.0 instance on this track"
    if len(srcs) > 1:
        return f"REFUSED: {len(srcs)} V1.0 instances on this track; migrate them one by one"
    src = srcs[0]
    src_idx = src.index
    src_guid = _guid(rpr, track, src_idx)

    names = [src.params[i].name for i in range(src.n_params)]
    if len(names) != N_DECLARED_V10 + len(HOST_TAIL):
        return (f"REFUSED: V1.0 reports {len(names)} parameters, expected "
                f"{N_DECLARED_V10 + len(HOST_TAIL)} - this REAPER build exposes a different "
                "special-parameter set; migrate by hand")
    if tuple(names[N_DECLARED_V10:]) != HOST_TAIL:
        return f"REFUSED: unexpected host tail {names[N_DECLARED_V10:]!r}; migrate by hand"

    if any(src.params[i].envelope is not None for i in range(src.n_params)):
        return "REFUSED: this instance has automation; migrate it by hand"
    if _has_modulation(rpr, track, src_idx, N_DECLARED_V10):
        return "REFUSED: this instance has parameter modulation; migrate it by hand"
    if _nondefault_pins(rpr, track, src_idx):
        return "REFUSED: this instance has a non-default pin map; migrate it by hand"
    if _oversampled(rpr, track, src_idx):
        return "REFUSED: this instance uses per-FX oversampling; migrate it by hand"

    declared = [src.params[i].normalized for i in range(N_DECLARED_V10)]
    # POSITIONAL, not by name: declared parameter 0 is also called "Bypass".
    host = [src.params[N_DECLARED_V10 + k].normalized for k in range(len(HOST_TAIL))]
    enabled = rpr.TrackFX_GetEnabled(track.id, src_idx)
    offline = rpr.TrackFX_GetOffline(track.id, src_idx)

    if dry_run:
        return (f"would copy {len(declared)} declared + {len(host)} host parameters into chain "
                f"position {src_idx}; {UNDETECTED}")

    # EVERYTHING below is inside try/finally, add_fx included: the one failure the tests exercise
    # is add_fx returning None or raising, and outside the block that would leave the undo open
    # and possibly an orphan behind.
    rpr.Undo_BeginBlock2(project.id)
    dst_guid = None
    closed = False
    try:
        dst = track.add_fx("JS: RCBitNova V1.1")
        if dst is None:
            raise RuntimeError("add_fx returned None: is JSFX/RCBitNova V1.1 installed?")
        dst_guid = _guid(rpr, track, dst.index)
        dst_names = [dst.params[i].name for i in range(dst.n_params)]
        if len(dst_names) != N_DECLARED_V11 + len(HOST_TAIL):
            raise RuntimeError(f"V1.1 reports {len(dst_names)} parameters, expected "
                               f"{N_DECLARED_V11 + len(HOST_TAIL)}")
        if tuple(dst_names[N_DECLARED_V11:]) != HOST_TAIL:
            raise RuntimeError(f"V1.1 host tail is {dst_names[N_DECLARED_V11:]!r}")

        for i, v in enumerate(declared):
            dst.params[i].normalized = v
        for k, v in enumerate(host):
            dst.params[N_DECLARED_V11 + k].normalized = v

        # Read back BEFORE destroying the only known-good instance.
        for i, v in enumerate(declared):
            got = dst.params[i].normalized
            if got != v:
                raise RuntimeError(f"parameter {i} ({dst_names[i]}) did not take: "
                                   f"wrote {v}, read {got}")
        for k, v in enumerate(host):
            if dst.params[N_DECLARED_V11 + k].normalized != v:
                raise RuntimeError(f"host parameter {HOST_TAIL[k]} did not take")

        dst_idx = _index_of_guid(rpr, track, dst_guid)
        rpr.TrackFX_SetEnabled(track.id, dst_idx, enabled)
        rpr.TrackFX_SetOffline(track.id, dst_idx, offline)

        # Move into the source's slot, then verify the move landed before deleting anything.
        rpr.TrackFX_CopyToTrack(track.id, dst_idx, track.id, src_idx, True)
        if _index_of_guid(rpr, track, dst_guid) != src_idx:
            raise RuntimeError(f"move failed: V1.1 is at {_index_of_guid(rpr, track, dst_guid)}, "
                               f"expected {src_idx}")
        stale = _index_of_guid(rpr, track, src_guid)
        if stale is None:
            raise RuntimeError("lost track of the V1.0 instance after the move")
        track.fxs[stale].delete()
    except Exception as exc:                      # noqa: BLE001 - any failure rolls back
        if dst_guid is not None:                  # BY GUID: the track may hold another V1.1
            doomed = _index_of_guid(rpr, track, dst_guid)
            if doomed is not None:
                track.fxs[doomed].delete()
        rpr.Undo_EndBlock2(project.id, "RCBitNova migration (failed)", -1)
        closed = True
        if _index_of_guid(rpr, track, src_guid) is None:
            rpr.Undo_DoUndo2(project.id)          # the source is already gone: undo for real
            return f"FAILED after the source was removed; undone: {exc}"
        return f"REFUSED, source untouched: {exc}"
    finally:
        if not closed:                            # closed exactly once, on every path
            rpr.Undo_EndBlock2(project.id, "RCBitNova V1.0 -> V1.1", -1)
    return f"migrated {len(declared)} declared + {len(host)} host parameters"


def migrate(track_index=0, dry_run=True):
    import reapy
    with reapy.inside_reaper():
        from reapy import reascript_api as RPR
        pr = reapy.Project()
        return migrate_chain(pr.tracks[track_index], RPR, pr, dry_run=dry_run)


if __name__ == "__main__":
    print(migrate(dry_run=True))
