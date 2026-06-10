"""FakeReaper: in-memory stand-ins for REAPER APIs so ReaScript glue can be unit
tested without a live REAPER. Extend with RPR_* / audio-item fakes as needed."""


class FakeImGui:
    """Scripted ReaImGui stand-in. Widgets echo the passed-in value; Button returns
    True only for the label selected via apply/cancel. Any unknown attribute (color
    constants Col_*, PushStyleColor/PopStyleColor, etc.) becomes a no-op returning 0,
    so theme calls don't break the test."""

    def __init__(self, apply=False, cancel=False, open_=1):
        self._apply = apply
        self._cancel = cancel
        self._open = open_
        self.ended = 0
        self.pushed = 0
        self.popped = 0

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

    def PushStyleColor(self, ctx, slot, col):
        self.pushed += 1

    def PopStyleColor(self, ctx, count=1):
        self.popped += count

    def __getattr__(self, name):
        # Col_* color constants and any other unscripted call -> no-op returning 0.
        return lambda *a, **k: 0
