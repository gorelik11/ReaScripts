# V1.5 live matrix — what only you can check

**Everything machine-checkable is green before this page is handed over.** What follows is the part
no test in this repository can reach.

REAPER is at **96 kHz**, which matters: at 44.1 kHz nothing above 22.05 kHz is representable, so
step 1 below cannot fail there and the whole acceptance would be vacuous.

## 1. The acceptance test, and it must FAIL first

1. A 96 kHz project, on material with **known energy above 22 kHz**.
2. `Phase: Linear`. FIR Brick exists only in the linear engine — under Min the slope maps to zero
   sections and no filter runs at all. Switch it with the transport **stopped**; the phase change
   is deferred to a stop, and V1.4 made that commit reach the engine from the button.
3. `LP res: High`. A FIR's transition band is roughly constant in Hz, so its steepness in octaves
   depends entirely on the kernel length: an HP brick at 43 Hz spans 1.65 octaves at BD 8192 and
   0.37 at 32768. At 21.5 kHz both are invisible, but state it so the result is reproducible.
4. **With `LP Slope: Off`, the analyser must SHOW that energy above 22 kHz.** A test that cannot
   fail has not passed. If the source has nothing up there, stop and change material.
5. Now `LP Slope: FIR Brick`, and type **21500** into the new `LP` field in the top bar.
6. Read it back from the **Param** list: it must say 21500 Hz exactly, not a normalised neighbour.
7. Measure the rejection above 22 kHz and **write the dBFS figure down**. "Nothing" is not a result
   for a finite windowed FIR.

## 2. Both fields, both gestures

The typed path and the dragged path go through different code, and the drag is what the id
resolver exists for — a commit-only path passes step 6 and fails this one.

- Type into `HP`, and type into `LP`.
- **Drag** each of them. The law is logarithmic, 120 logical pixels per octave, so 20000 -> 21500
  is about 12 pixels. If it feels like it moves 1 Hz per pixel, the wrong branch is running.
- After every gesture, observe the effect **immediately**, without touching anything else.

## 3. The one that broke before anyone looked for it

**Click each field where a band node sits underneath it, with that band DISABLED.**

No band may be enabled, and no band value may change. Until V1.5 the node hit set was collected
before those controls were even drawn, so a click on that spot both enabled the band and armed its
drag. The three global buttons — `Phase`, `HP res`, `LP res` — had the same exposure since V1.0;
try one of those too.

## 4. Stopped transport

Three separate bugs in V1.3 and V1.4 lived exactly here, and no test in this repository can see
them: the null harness writes parameters before rendering, and a write runs `@slider`.

**With the transport stopped**, set the HP and LP frequencies by both gestures and confirm each
takes effect without a plugin reload.

## 5. The migration

On a scratch project: a V1.4 instance with `LP Freq` at 12000 Hz. Run `migrate_v14_to_v15`. The
V1.5 instance's `LP Freq` must read **12000** in the Param list, not 14398.

## 6. The graph, for a second look

The axis now reaches 24 kHz, so every band node sits about 2.3% of the width further left than it
did. Frequencies are unchanged; the ruler is wider. Worth one glance so it does not read as drift.

## Still open, not part of this

The orange gain-reduction tint appears only after a plugin reload — reported 2026-09-15, recorded
in `OPEN-gr-display-needs-reload.md`, and untouched by V1.5.
