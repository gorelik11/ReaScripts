# RCBitNova V1.1 — Eight EQ bands, four of them dynamic

**Date:** 2026-08-19
**Branch:** `rcbitnova`
**New file:** `JSFX/RCBitNova V1.1` (copy of V1.0). `rcbitnova-v1.0` remains the fallback tag;
V1.0 and earlier are frozen.

---

## 1. Goal

Four bands is not enough for mixing or mastering work. Raise the static EQ to **eight bands**,
keeping the **dynamics on the first four**.

The roadmap has tied "expand to 8 bands" to the GUI since V0.3, because the blocker was
reachability: 95 sliders were already unmanageable, and 131 would have been worse. V1.0's graph
removes that blocker — a ninth band node costs the user nothing.

## 2. Why this split, and what it saves

The owner first asked for eight *fully* dynamic bands, then revised after seeing the cost. The
revision is worth recording, because the difference is not incremental:

| | 8 dynamic bands | **8 static, 4 dynamic** |
|---|---|---|
| Mode B delay rings | +32768 words | **unchanged** |
| `lp_base` | moves 65536 → 131072 | **unchanged** |
| Low fixed-address arrays | must be re-laid out | **all fit as-is** |
| New sliders | ~84 | **36** |
| Audio-path risk | high | low |

Verified against the shipped layout — at eight bands the static arrays still fit inside their
existing gaps:

| Array | Purpose | Per band | At 8 bands | Next array | Fits |
|---|---|---|---|---|---|
| `cf` @0 | static coefficients | 8 | 64 | `st` @64… | yes |
| `st` @64 | static filter state | 4 | 32 | `det` @96 | yes, exactly to the boundary |
| `bp` @216 | band params (fc, q, cg) | 3 | 24 | `eg` @256 | yes |
| `dp` @192 | dynamics params | 4 | — | `dm` @208 | **stays at 4 bands** |

`st` reaching exactly 96 is the tightest fit in the design and gets its own test.

## 3. Architecture: two counts, not one

`N_BANDS = 8` for static EQ; a new `N_DYN = 4` for everything dynamic. Every loop and every
allocation takes whichever applies:

| Uses `N_BANDS` (8) | Uses `N_DYN` (4) |
|---|---|
| `cf` static coefficients | `det`, `dst` detector coefficients and state |
| `st` static state | `cst` Mode-A cut state |
| `bp` band params | `dp`, `dm` dynamics params and stereo mode |
| `setup_band`, the `@sample` static loop | `eg`, `egh` Mode-A envelopes |
| the GUI's nodes and traces | `mb_band`/`mb_peak`/`mb_end` Mode-B rings |
| | `mbenv`, `mbgc`, `mbeh`, `mbwpos`, `hc` |

Bands 5–8 have no detector, no Mode-B ring and no ceilings — not disabled ones, but none
allocated. That is what keeps the memory flat.

**The `@sample` band loop splits in two**: bands 0–3 run the existing full path; bands 4–7 run
static filtering only. The dynamics branch is not entered for them at all, so they cost the same
as a disabled band today.

## 4. Sliders

Bands 1–4 keep their numbers exactly — `11–49` static, `51–88` dynamics, `91–123` ceilings.
**Nothing in that range moves.** REAPER stores parameters by number, so any shift would silently
corrupt every existing project.

Bands 5–8 take **151–189**, nine per band in the same order as bands 1–4:

```
15x1 Enable · 15x2 Type · 15x3 Freq · 15x4 Q · 15x5 Macro
15x6 Micro  · 15x7 Bit Ratio · 15x8 Placement · 15x9 Q Character
```

Addressing becomes a single helper rather than open-coded arithmetic in twenty places:

```
function band_slider_base(b) ( b < 4 ? 10 * (b + 1) : 150 + 10 * (b - 4); );
```

Open-coding it is how the two-copy problem started in V1.0's filter code, and this time the
branch would appear in the audio path, the GUI, and the coefficient builder simultaneously.

**Defaults for the new bands:** Enable off, Bell, Q 0.707, Macro 0, Ratio 1, Placement Both,
Q Character 0. Frequencies spread so the nodes do not stack: **150 / 700 / 5000 / 15000 Hz**.
An old project therefore opens with four inaudible extra bands.

## 5. GUI

Already parameterised by `N_BANDS`, so nodes, traces and hit-testing scale by changing the
constant. Two additions:

- The readout names the band (`B5`), and the numeric fields address it through the same
  `band_slider_base` helper.
- Bands without dynamics are visually distinguishable — a **thinner node outline** — so it is
  obvious which four can be made dynamic. Without it the only way to find out is to open the
  dynamics section and find nothing there.

## 6. Verification

**Oracle:** the curve maths is already band-count agnostic (`domain_bits` takes a list), so the
new tests are about the split, not the maths:

1. `band_slider_base` returns 10/20/30/40 for bands 0–3 and 150/160/170/180 for bands 4–7.
2. Static arrays at 8 bands stay inside their gaps: `cf` ≤ 96, `st` ≤ 96, `bp` ≤ 256 — and the
   `st` case is asserted exactly, since it lands on the boundary.
3. Dynamics arrays are sized by `N_DYN`, and `mb_end` is unchanged from V1.0.
4. A curve over 8 bands equals the curve over the same 4 bands when bands 5–8 are disabled.

**Live in REAPER:**

- **Null test V1.0 vs V1.1 with bands 5–8 off: digital zero.** New bands must cost nothing until
  used — this is the gate that says the split was done correctly.
- Eight nodes appear, drag, and change the sound; the four static ones show no dynamics.
- **CPU with 8 bands vs 4**, window closed, and with all four dynamic bands active in Mode B —
  the worst case the plugin supports.
- An existing project opens unchanged, with bands 5–8 off.

## 7. Out of scope

- Dynamics on bands 5–8. If the owner ever needs them, it is a separate version with the memory
  re-layout described in §2 — and the cost is known in advance now.
- Spectrum analyser (V1.2) and the dynamics display (V1.3), both already deferred.

## 8. Method

Unchanged: verify in Python first → TDD the oracle → transcribe to JSFX → live-verify with the
owner → Fable final review → tag `rcbitnova-v1.1`.

**Carried forward from V1.0's seven live defects** (spec §16 of the V1.0 design), because this
version touches the same seams: write sliders by name and never through a computed index;
recompute dependants inline rather than trusting `@slider`; quantise mouse writes to the declared
step; and check function definition order — EEL2 resolves in file order, which broke four builds.
