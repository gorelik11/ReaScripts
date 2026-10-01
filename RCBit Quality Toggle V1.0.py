#!/usr/bin/env python3
"""RCBit Quality Toggle V1.0 - flip every RCBit limiter in the project Light <-> HQ.

Covers RCBitLimiter V2.0 and RCBitBrickwall V4.0 (slider9 "Quality", 0=Light,
1=HQ) on track FX, input FX, master, monitoring FX and take FX.

Rule: if ANY loaded instance is Light, everything goes to HQ; only when all
are already HQ does everything go to Light. A mixed project therefore always
resolves to HQ - the safe state before a render. Offline instances are skipped.
One undo point. Meant for a hotkey; the per-instance view is
"RCBit Quality Manager V1.0.py".
"""

# --- shared core (keep identical in RCBit Quality Toggle / Manager) ---------
# Plugins are matched by fx_ident (the JSFX file path under Effects/), NOT by
# the display name: a renamed FX keeps working, and REAPER's cached name can
# be stale. The basename is compared so a subfolder install also matches.
TARGET_PLUGINS = ("RCBitLimiter V2.0", "RCBitBrickwall V4.0")
QUALITY_PARAM = 8          # slider9 -> parameter index 8
REC_FX = 0x1000000         # input FX (monitoring FX on the master)


def _rpr(name):
    fn = globals().get("RPR_" + name)
    if fn is None:
        import builtins
        fn = getattr(builtins, "RPR_" + name)
    return fn


def target_plugin(ident):
    """Return the target plugin name for an fx_ident, else None."""
    base = (ident or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base if base in TARGET_PLUGINS else None


def _fx_ident(kind, owner, fx):
    r = _rpr(kind + "FX_GetNamedConfigParm")(owner, fx, "fx_ident", "", 4096)
    return r[4] if r[0] else ""


def _probe(kind, owner, fx, where, slot):
    """Instance record for one FX slot, or None if it is not a target."""
    plugin = target_plugin(_fx_ident(kind, owner, fx))
    if plugin is None:
        return None
    pname = _rpr(kind + "FX_GetParamName")(owner, fx, QUALITY_PARAM, "", 256)[4]
    if pname.strip().lower() != "quality":
        return None
    val = _rpr(kind + "FX_GetParam")(owner, fx, QUALITY_PARAM, 0, 0)[0]
    return {
        "kind": kind, "owner": owner, "fx": fx, "plugin": plugin,
        "where": where, "slot": slot, "hq": val >= 0.5,
        "enabled": bool(_rpr(kind + "FX_GetEnabled")(owner, fx)),
        "offline": bool(_rpr(kind + "FX_GetOffline")(owner, fx)),
    }


def _fmt_time(t):
    m = int(t // 60)
    return "%d:%06.3f" % (m, t - 60 * m)


def scan_project():
    """Every target instance in the active project, in mixer order, then takes."""
    out = []

    def track_chain(tr, label, rec_label):
        for fx in range(_rpr("TrackFX_GetCount")(tr)):
            r = _probe("Track", tr, fx, label, "FX %d" % (fx + 1))
            if r:
                out.append(r)
        for fx in range(_rpr("TrackFX_GetRecCount")(tr)):
            r = _probe("Track", tr, REC_FX + fx, rec_label,
                       "FX %d" % (fx + 1))
            if r:
                out.append(r)

    track_label = {}
    master = _rpr("GetMasterTrack")(0)
    track_chain(master, "MASTER", "Monitoring FX")
    for i in range(_rpr("CountTracks")(0)):
        tr = _rpr("GetTrack")(0, i)
        name = _rpr("GetTrackName")(tr, "", 512)[2]
        label = "%d: %s" % (i + 1, name)
        track_label[tr] = label
        track_chain(tr, label, label + " [input FX]")

    for i in range(_rpr("CountMediaItems")(0)):
        item = _rpr("GetMediaItem")(0, i)
        tlabel = track_label.get(_rpr("GetMediaItem_Track")(item), "?")
        pos = _rpr("GetMediaItemInfo_Value")(item, "D_POSITION")
        for t in range(_rpr("CountTakes")(item)):
            take = _rpr("GetTake")(item, t)
            if not take:
                continue
            n = _rpr("TakeFX_GetCount")(take)
            if not n:
                continue
            where = "%s | item @ %s (%s)" % (
                tlabel, _fmt_time(pos), _rpr("GetTakeName")(take))
            for fx in range(n):
                r = _probe("Take", take, fx, where, "FX %d" % (fx + 1))
                if r:
                    out.append(r)
    return out


def toggle_target(instances):
    """True -> set all to HQ, False -> all to Light, None -> nothing loaded."""
    live = [r for r in instances if not r["offline"]]
    if not live:
        return None
    return any(not r["hq"] for r in live)


def set_quality(inst, hq):
    """Set one instance. Refuses (False) if the owner is gone or the slot now
    holds a different plugin - the scan may be older than the project."""
    kind, owner, fx = inst["kind"], inst["owner"], inst["fx"]
    ptr_type = "MediaTrack*" if kind == "Track" else "MediaItem_Take*"
    if not _rpr("ValidatePtr2")(0, owner, ptr_type):
        return False
    if target_plugin(_fx_ident(kind, owner, fx)) != inst["plugin"]:
        return False
    _rpr(kind + "FX_SetParam")(owner, fx, QUALITY_PARAM, 1.0 if hq else 0.0)
    inst["hq"] = hq
    return True


def set_all(instances, hq, undo_label):
    """Set every loaded instance; one undo point. Returns how many changed."""
    changed = 0
    _rpr("Undo_BeginBlock2")(0)
    try:
        for r in instances:
            if r["offline"] or r["hq"] == hq:
                continue
            if set_quality(r, hq):
                changed += 1
    finally:
        _rpr("Undo_EndBlock2")(0, undo_label, -1)
    return changed
# --- end shared core --------------------------------------------------------


def run_toggle():
    instances = scan_project()
    hq = toggle_target(instances)
    if hq is None:
        return {"target": None, "changed": 0, "total": len(instances)}
    label = "RCBit quality: all to %s" % ("HQ" if hq else "Light")
    changed = set_all(instances, hq, label)
    return {"target": "HQ" if hq else "Light", "changed": changed,
            "total": len(instances)}


def main():
    # NEVER raise SystemExit / sys.exit() in a ReaScript: it routes to C exit()
    # and kills REAPER. Silent on purpose - this is a hotkey; the undo history
    # names what happened.
    run_toggle()


if __name__ == "__main__":
    main()
