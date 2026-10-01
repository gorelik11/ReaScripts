#!/usr/bin/env python3
"""RCBit Quality Manager V1.0 - list every RCBit limiter and switch Light/HQ.

A ReaImGui window listing each RCBitLimiter V2.0 / RCBitBrickwall V4.0 in the
project (track FX, input FX, master, monitoring FX, take FX) with its current
Quality. Click the Light/HQ button in a row to flip that one instance, "Show"
to open its FX window, or use the bulk buttons. The list rescans itself when
the project changes. Hotkey-only flip of everything: "RCBit Quality Toggle".
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

TITLE = "RCBit Quality Manager"
RESCAN_MIN_S = 1.0         # throttle for automatic rescans on project change

# 0xRRGGBBAA: button, hovered, active
_HQ_COLS = (0x2E7D32FF, 0x388E3CFF, 0x1B5E20FF)
_LIGHT_COLS = (0xB26A00FF, 0xC77800FF, 0x8C5300FF)

_QM = None  # {"imgui", "ctx", "rows", "scc", "proj", "t", "scan_ms", "msg"}


def counts(rows):
    light = sum(1 for r in rows if not r["offline"] and not r["hq"])
    hq = sum(1 for r in rows if not r["offline"] and r["hq"])
    off = sum(1 for r in rows if r["offline"])
    return light, hq, off


def _project():
    return _rpr("EnumProjects")(-1, "", 0)[0]


def _rescan(g):
    t0 = _rpr("time_precise")()
    try:
        g["rows"] = scan_project()
    except Exception as e:  # never let a scan error kill the window
        g["rows"] = []
        g["msg"] = "Scan failed: %s" % e
    t1 = _rpr("time_precise")()
    g["scan_ms"] = (t1 - t0) * 1000.0
    g["t"] = t1
    g["scc"] = _rpr("GetProjectStateChangeCount")(0)
    g["proj"] = _project()


def _maybe_rescan(g):
    proj = _project()
    if proj != g["proj"]:
        _rescan(g)
        return
    if _rpr("GetProjectStateChangeCount")(0) != g["scc"] and \
            _rpr("time_precise")() - g["t"] >= RESCAN_MIN_S:
        _rescan(g)


def _show_fx(r):
    ptr_type = "MediaTrack*" if r["kind"] == "Track" else "MediaItem_Take*"
    if _rpr("ValidatePtr2")(0, r["owner"], ptr_type):
        _rpr(r["kind"] + "FX_Show")(r["owner"], r["fx"], 3)  # 3 = floating


def do_action(g, action):
    """Apply one GUI action, then rescan so the list shows the real state."""
    kind = action[0]
    rows = g["rows"]
    if kind == "all":
        hq = action[1]
        n = set_all(rows, hq, "RCBit quality: all to %s" % ("HQ" if hq else "Light"))
        g["msg"] = "%d instance(s) set to %s" % (n, "HQ" if hq else "Light")
    elif kind == "toggle":
        hq = toggle_target(rows)
        if hq is None:
            g["msg"] = "Nothing to toggle"
        else:
            n = set_all(rows, hq, "RCBit quality: all to %s" % ("HQ" if hq else "Light"))
            g["msg"] = "%d instance(s) set to %s" % (n, "HQ" if hq else "Light")
    elif kind == "one":
        r = rows[action[1]]
        hq = not r["hq"]
        _rpr("Undo_BeginBlock2")(0)
        ok = set_quality(r, hq)
        _rpr("Undo_EndBlock2")(0, "RCBit quality: %s to %s"
                               % (r["plugin"], "HQ" if hq else "Light"), -1)
        g["msg"] = "" if ok else "That FX moved or was removed - list refreshed"
    elif kind == "show":
        _show_fx(rows[action[1]])
        return
    _rescan(g)


def _quality_button(ImGui, ctx, r):
    cols = _HQ_COLS if r["hq"] else _LIGHT_COLS
    ImGui.PushStyleColor(ctx, ImGui.Col_Button(), cols[0])
    ImGui.PushStyleColor(ctx, ImGui.Col_ButtonHovered(), cols[1])
    ImGui.PushStyleColor(ctx, ImGui.Col_ButtonActive(), cols[2])
    clicked = ImGui.Button(ctx, "HQ" if r["hq"] else "Light", 70, 0)
    ImGui.PopStyleColor(ctx, 3)
    return clicked


def _qm_frame():
    """One ReaImGui frame; re-defers itself until the window is closed."""
    global _QM
    g = _QM
    if g is None:
        return
    ImGui = g["imgui"]
    ctx = g["ctx"]
    _maybe_rescan(g)
    rows = g["rows"]

    action = None
    ImGui.SetNextWindowSize(ctx, 760, 460, ImGui.Cond_FirstUseEver())
    visible, open_ = ImGui.Begin(ctx, TITLE, True)
    if visible:
        light, hq, off = counts(rows)
        ImGui.Text(ctx, "Light: %d    HQ: %d    Offline: %d    (scan %.0f ms)"
                   % (light, hq, off, g["scan_ms"]))
        if ImGui.Button(ctx, "All to HQ"):
            action = ("all", True)
        ImGui.SameLine(ctx)
        if ImGui.Button(ctx, "All to Light"):
            action = ("all", False)
        ImGui.SameLine(ctx)
        if ImGui.Button(ctx, "Toggle all"):
            action = ("toggle",)
        ImGui.SameLine(ctx)
        if ImGui.Button(ctx, "Refresh"):
            action = ("refresh",)
        if g["msg"]:
            ImGui.Text(ctx, g["msg"])
        ImGui.Separator(ctx)

        if not rows:
            ImGui.Text(ctx, "No %s in this project." % " / ".join(TARGET_PLUGINS))
        elif ImGui.BeginTable(ctx, "rcq", 4,
                              ImGui.TableFlags_Borders() | ImGui.TableFlags_RowBg()
                              | ImGui.TableFlags_ScrollY()
                              | ImGui.TableFlags_Resizable()):
            ImGui.TableSetupScrollFreeze(ctx, 0, 1)
            ImGui.TableSetupColumn(ctx, "Location")
            ImGui.TableSetupColumn(ctx, "Plugin")
            ImGui.TableSetupColumn(ctx, "Quality")
            ImGui.TableSetupColumn(ctx, "")
            ImGui.TableHeadersRow(ctx)
            for i, r in enumerate(rows):
                ImGui.TableNextRow(ctx)
                ImGui.PushID(ctx, "r%d" % i)
                ImGui.TableNextColumn(ctx)
                ImGui.Text(ctx, "%s / %s" % (r["where"], r["slot"]))
                ImGui.TableNextColumn(ctx)
                ImGui.Text(ctx, r["plugin"] + ("" if r["enabled"] else " (bypassed)"))
                ImGui.TableNextColumn(ctx)
                if r["offline"]:
                    ImGui.Text(ctx, "offline")
                elif _quality_button(ImGui, ctx, r):
                    action = ("one", i)
                ImGui.TableNextColumn(ctx)
                if ImGui.SmallButton(ctx, "Show"):
                    action = ("show", i)
                ImGui.PopID(ctx)
            ImGui.EndTable(ctx)
    ImGui.End(ctx)  # ImGui requires End even when Begin returns not-visible

    if action is not None:
        if action[0] == "refresh":
            g["msg"] = ""
            _rescan(g)
        else:
            do_action(g, action)
    if not open_:
        _QM = None
        return
    _rpr("defer")("_qm_frame()")


def open_manager():
    """Open the window. Returns immediately (defer loop); never crashes REAPER."""
    global _QM
    try:
        import os
        import sys
        api = os.path.join(_rpr("GetResourcePath")(),
                           "Scripts", "ReaTeam Extensions", "API")
        if api not in sys.path:
            sys.path.insert(0, api)
        import imgui as _ImGui
    except Exception:
        try:
            _rpr("ShowMessageBox")(
                "ReaImGui is required for the RCBit Quality Manager.\n\n"
                "Install it via ReaPack:\n"
                "Extensions > ReaPack > Browse packages > search 'ReaImGui'.",
                TITLE, 0)
        except Exception:
            pass
        return None
    g = {"imgui": _ImGui, "ctx": _ImGui.CreateContext(TITLE), "rows": [],
         "scc": None, "proj": None, "t": 0.0, "scan_ms": 0.0, "msg": ""}
    _rescan(g)
    _QM = g
    _rpr("defer")("_qm_frame()")
    return None


def main():
    # NEVER raise SystemExit / sys.exit() in a ReaScript: it routes to C exit()
    # and kills REAPER. The defer loop ends by not re-deferring.
    open_manager()


if __name__ == "__main__":
    main()
