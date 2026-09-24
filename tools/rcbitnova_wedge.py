"""The Mode-B lookahead maximum, twice: V1.5's rescan and the monotonic queue that replaces it.

WHY THIS FILE EXISTS. V1.5 finds the worst peak in the lookahead window by rescanning the whole
window on EVERY sample, for every lane of every enabled band:

    worstA = 0; i = 0;
    loop(Lk + 1, p = mb_peak[baseA + ((wp - i + MAX_LOOK) % MAX_LOOK)]; p > worstA ? worstA = p; i += 1;);

Measured live on 2026-09-24 at 96 kHz, eight bands in Mode B Split: CPU = 1.4% + 0.0215% * Lk.
At a 2 ms lookahead that loop is 72% of the plugin; at 10 ms it is 94%. A sliding-window maximum
returns THE SAME value in amortised O(1).

WHAT "THE SAME" MEANS HERE, and it is not what it sounds like. The acceptance for V1.6 is a null
against V1.5, so the queue must reproduce V1.5 BUG FOR BUG. V1.5 advances a band's ring cursor
even in placements where lane B is never written - `mbwpos[b] = (wp + 1) % MAX_LOOK` at
JSFX/RCBitNova V1.5:2230 sits OUTSIDE the `two ?` block that writes lane B at 2175-2182. So after
Both -> Mid -> Both the rescan reads values left in the ring from an earlier rotation and limits
on them. A queue that quietly computed the mathematically clean maximum would be more correct and
would fail the null.

(That staleness is a latent defect in V1.5 in its own right - a band returning to Both can briefly
limit against a peak up to MAX_LOOK samples old. It is recorded in the V1.6 design and must NOT be
fixed in V1.6, because fixing it breaks the null that proves everything else.)

Run: python3 -m pytest tests/test_rcbitnova_wedge.py -v
"""

MAX_LOOK_DEFAULT = 2048


def brute_max(peaks, wp, Lk, max_look=MAX_LOOK_DEFAULT):
    """V1.5's rescan, transcribed. The window is the Lk + 1 positions ending at wp."""
    worst = 0.0
    for i in range(Lk + 1):
        p = peaks[(wp - i + max_look) % max_look]
        if p > worst:
            worst = p
    return worst


class Wedge:
    """Monotonic deque of (value, position), values decreasing from head to tail.

    Capacity is MAX_LOOK + 1 on purpose. The reference pushes BEFORE evicting, so occupancy is
    transiently Lk + 2; at the clamp Lk = MAX_LOOK - 1 = 2047 that is 2049, one past a 2048-slot
    buffer, which would overwrite its own head and corrupt the position test. Reachable only at
    352.8/384 kHz - which is precisely why it would have survived every null run at 96 kHz.
    """

    def __init__(self, cap=MAX_LOOK_DEFAULT + 1):
        self.cap = cap
        self.v = [0.0] * cap
        self.p = [0] * cap
        self.head = self.tail = self.cnt = 0

    def reset(self):
        self.head = self.tail = self.cnt = 0

    def count(self):
        return self.cnt

    def push(self, value, pos):
        run = True
        while run:
            if self.cnt > 0:
                t = self.tail - 1
                if t < 0:
                    t += self.cap
                if self.v[t] <= value:
                    self.tail = t
                    self.cnt -= 1
                else:
                    run = False
            else:
                run = False
        t = self.tail
        self.v[t] = value
        self.p[t] = pos
        t += 1
        if t >= self.cap:
            t = 0
        self.tail = t
        self.cnt += 1
        assert self.cnt <= self.cap, "queue overflow: capacity must be MAX_LOOK + 1"

    def evict(self, pos):
        """Exactly one position leaves the window per sample, so one equality test suffices."""
        if self.cnt > 1 and self.p[self.head] == pos:
            h = self.head + 1
            if h >= self.cap:
                h = 0
            self.head = h
            self.cnt -= 1

    def top(self):
        return self.v[self.head]

    def rebuild(self, peaks, wp, Lk, max_look=MAX_LOOK_DEFAULT):
        """Replay the positions V1.5 would scan, oldest to newest, EXCLUDING wp itself.

        Reading `peaks` at those positions - rather than recomputing anything from the signal -
        is what reproduces the stale values a skipped lane leaves behind.
        """
        self.reset()
        for r in range(Lk, 0, -1):
            pos = (wp - r + max_look) % max_look
            self.push(peaks[pos], pos)


def _drive(samples, lk_at_sample, active_at_sample, max_look, engine, cap=None):
    """Run one lane. `active_at_sample(n)` False models a placement in which this lane is not
    written - and the cursor advances anyway, exactly as V1.5 does."""
    peaks = [0.0] * max_look
    state = {"lk": None, "valid": False, "last_wp": None,
             "wedge": Wedge(cap or (max_look + 1))}
    wp = 0
    out = []
    for n, s in enumerate(samples):
        lk = lk_at_sample(n)
        if active_at_sample(n):
            peaks[wp] = abs(s)
            out.append(engine(state, peaks, wp, lk, max_look))
        else:
            out.append(None)
        wp = (wp + 1) % max_look
    return out


def _ref_engine(state, peaks, wp, lk, max_look):
    return brute_max(peaks, wp, lk, max_look)


def _wedge_engine(state, peaks, wp, lk, max_look):
    w = state["wedge"]
    expected = (wp - 1 + max_look) % max_look
    stale_cursor = state["last_wp"] is not None and state["last_wp"] != expected
    if (not state["valid"]) or state["lk"] != lk or stale_cursor:
        w.rebuild(peaks, wp, lk, max_look)
        state["lk"] = lk
        state["valid"] = True
    w.push(peaks[wp], wp)
    w.evict((wp - lk - 1 + max_look) % max_look)
    state["last_wp"] = wp
    return w.top()


def run_reference(samples, lk_at_sample, active_at_sample, max_look=MAX_LOOK_DEFAULT):
    return _drive(samples, lk_at_sample, active_at_sample, max_look, _ref_engine)


def run_wedge(samples, lk_at_sample, active_at_sample, max_look=MAX_LOOK_DEFAULT, cap=None):
    return _drive(samples, lk_at_sample, active_at_sample, max_look, _wedge_engine, cap)
