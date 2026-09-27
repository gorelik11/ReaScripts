# V1.6 live matrix — what only you can check

**The machine half is green before this page is read:** 416 tests, source gate, live manifest
(183 parameters; V1.5's 176 records as an exact prefix, then the analyser's four, pinned),
compile with the analyser ON, and **null 12/12 bit-identical against V1.5 at zero tolerance** —
six steady cases, three transitions, and three with the analyser ON, including switched on and
off under audio. An analyser that is on and still nulls is the only proof available from outside
the plugin that its taps do not write.

## Already confirmed live

| When | What | How it was measured |
|---|---|---|
| 2026-09-25 | A Phase switch clicked **under playback** commits, both ways, no reload | plugin PDC 12288 ↔ 0, transport playing, instance online |
| 2026-09-25 | The lookahead term is gone | FX CPU at 0.1 / 2 / 10 ms: V1.5 2.8 / 9.6 / **50 %**, V1.6 2.6 / 2.6 / **3.0 %** |
| 2026-09-25 | The analyser draws: IN and OUT, Mid domain | by eye |
| 2026-09-26 | M/S mode paints Side-over-Mid red, in two shades | by eye, against SPAN in Mid/Side |
| 2026-09-26 | **A mono source never goes red** | mono sum inserted directly before the plugin — Side is zero by construction; no column went red at any level |

The M/S comparison with SPAN found the plugin paints more red than SPAN does, because SPAN
smooths at 1/6 octave. Both are honest at different grain; **the fine grain was kept on purpose**
(see the design, §4.4.1).

## Still to check

### 1. The four buttons

Second row of the top bar, right-aligned: `Analyzer`, `Dom`, `Tilt`, `Peak`.

- `Analyzer: Off → On` — the picture appears within a fraction of a second **of playback**.
- `Dom` cycles Mid → Side → Left → Right → M/S → Mid. **At each change the picture must go
  empty for a moment and refill.** If it instead morphs smoothly from one domain into the next,
  two streams are being mixed on screen for ~85 ms — the rings were not cleared.
- `Tilt` cycles 0 → 3 → 4.5; the whole spectrum pivots around 1 kHz.
- None of the four may enable a band, arm a drag, or move a node. **Try it at the default size,
  at the smallest size before small mode hides the strip, and on the Retina screen.**

### 2. Peak hold

- `Peak: Hold` draws a thin line above each fill that **only ever rises**.
- **Right-click** on `Peak` clears it without turning it off.
- A **domain change** clears it.
- A **transport start** does NOT clear it. (REAPER re-runs `@init` there; the peaks live in memory
  for exactly this reason.)

### 3. Transport stopped

- Change `Dom` with the transport **stopped**. The picture clears and stays empty until audio
  flows. **That is correct, not a hang** — the rings are cleared by the audio thread, which is not
  running.
- Three bugs of this plugin lived only with the transport stopped. This is the section the tests
  cannot reach.

### 4. The lookahead knob under playback

Turn `Lookahead (ms, Mode B)` up and down while it plays, with bands in Mode B. **No click.**

This replaces two null cases that had to be removed: a change of lookahead is a change of the
plugin's latency, and a null test across a latency change compares REAPER's compensation rather
than the detector. The case was bit-identical alone and failed deterministically after any other
case — the same sample every time — so it measured the host. The detector's side of it is covered
by the Python oracle, up, down, and during an inactive lane. The *audible* side is only coverable
here.

### 5. Nyquist

Switch a scratch project to **44.1 kHz** and open the analyser. The region above 22.05 kHz must be
**empty** — not the last real bin painted across to 24 kHz.

### 6. Anti-phase, if you have a way to make it

Invert the polarity of one channel. In `M/S`, the affected range must go **bright red**.

## Open, and stated as open

**"The EQ works only after a reset"** — reported 2026-09-27 on a working project with 25 V1.6
instances. Not reproduced: a fresh instance with the analyser ON showed no runtime error, and after
a reset the EQ worked from both the GUI and the Param list. The most likely explanation is that
**REAPER does not re-read a JSFX for instances that already exist**, so a project worked on across
several edits of the file held a mix of compiled generations. All 25 were rebuilt on one file with
every value verified.

That explains everything observed and proves none of it. **If it happens again, note which
instance, whether the transport was running, and what was clicked last** — that is what would
turn an explanation into a finding.

## Tag

`rcbitnova-v1.6` goes on after this page has been run, and its message records what was confirmed
live and what was not — including the open item above, as open.
