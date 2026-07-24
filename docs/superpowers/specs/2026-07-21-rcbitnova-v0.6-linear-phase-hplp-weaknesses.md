# RCBitNova V0.6 Linear-Phase HP/LP - Weakness Review

**Date:** 2026-07-21  
**Reviewed spec:** `2026-07-21-rcbitnova-v0.6-linear-phase-hplp-design.md`  
**Context:** worktree `~/projects/reascripts/.claude/worktrees/rcbitnova/`

The scope boundary is sensible: linearize only the static HP/LP section and leave
the nonlinear dynamics path honestly described as minimum-phase/time-varying. The
weak points are mostly in the FFT architecture and transition contract. Several
currently stated invariants cannot all hold with the proposed even-length kernel,
in-place kernel rebuild, and dynamic PDC.

## P0 - FFT Buffers Cannot Simply Start After `hplp_cf`

Section 7 says to allocate all convolution buffers after `hplp_cf`. That guarantees
ordinary memory disjointness, but it is insufficient for JSFX FFT safety. The
official JSFX reference requires every `fft`/`ifft` and `convolve_c` buffer span to
stay inside one 65,536-item page. The V0.5 end offset is not page-aligned, while
Arthur's standalone engine starts at zero and arranges its large complex blocks on
safe boundaries.

With two engines, a merely contiguous layout can make an `Hspec` partition, FDL
partition, `fftw`, `yacc`, or `tmpc` cross a page boundary. That is undefined
behavior even if no two named buffers overlap.

**Recommendation:** pin a page-aware allocator/layout in the spec, not just a
disjointness test. For every actual FFT/convolution call assert:

`floor(start / 65536) == floor((start + item_count - 1) / 65536)`

Include all per-lane buffers (`fdlA/fdlB`, `inA/inB`, `outA/outB`, `dryA/dryB`),
padding, final memory high-water mark, `freembuf` boundary, and an `__memtop()`
guard. Reference: <https://www.reaper.fm/sdk/js/advfunc.php>.

## P0 - Even Kernel Symmetry Conflicts With The Proposed Construction And Delay

The test requires `k[i] == k[N-1-i]` for `N=8192`, which is symmetry around
4095.5 samples and therefore a Type-II FIR with 4095.5-sample group delay. But the
specified real zero-phase IFFT plus integer `fftshift` centers the circular impulse
at index 4096. Arthur then applies a Kaiser window symmetric around 4095.5. These
operations do not generally produce the asserted symmetry.

The identity-magnitude case exposes the contradiction immediately: the IFFT is a
delta at 0, and `fftshift` moves it to `k[4096]`; its `N-1-i` mirror is `k[4095]`,
which is zero. The claimed integer kernel delay `BD/2 = 4096` and the asserted
even-length symmetry cannot both describe that sequence exactly.

**Recommendation:** choose and pin one coherent design:

- An odd-length symmetric FIR (for example 8191 taps) with integer group delay;
- A true even-length Type-II kernel with half-sample delay and an explicit dry/PDC
  alignment solution; or
- Arthur's approximately centered construction, with the word "exactly" removed
  and measured phase-error limits.

Add tests for symmetry, unwrapped phase residual, impulse peak/centroid, and exact
reported PDC. Do not infer latency only from constants.

## P0 - Dynamic PDC Conflicts With Seamless Phase/Off/Bypass Switching

The reported delay can jump among 0, 6144, 12288, and those values plus Mode-B
lookahead when Phase, Slope, or master bypass changes. The official JSFX docs allow
`pdc_delay` updates but explicitly warn not to change it too often. A host PDC
change does not repair already queued convolution samples or create missing input
history.

The strongest conflict is master bypass: `pdc_delay=0` gives immediate dry audio,
whereas the active path may be 256 ms behind. Toggling bypass or Phase therefore
causes a timeline jump even if every buffer is numerically correct.

**Recommendation:** define the transition contract explicitly. Options include:

- Keep maximum PDC while the instance is loaded and delay bypass/min-path dry;
- Treat Phase/Slope/bypass changes as non-seamless topology changes and document
  the time jump;
- Run old/new pipelines in parallel during a host-approved latency transition.

At minimum, test active->bypass->active, Min<->Linear, one-filter<->two-filter, and
Off<->active while playing and while stopped. Reference:
<https://www.reaper.fm/sdk/js/vars.php>.

## P1 - Two Serial Engines Are A Choice, Not A Placement Requirement

The spec says independent Placement means HP and LP cannot share one kernel and
therefore require two serial engines whose latency adds. Independent Placement
does prevent one scalar transfer function in a single fixed domain, but it does
not require two FFT stages.

Every Placement operation is a linear 2x2 matrix in L/R. HP and LP can each be
written as a frequency-dependent 2x2 transfer matrix; their serial composition is
another 2x2 matrix. One partitioned engine can transform L/R once, apply the four
matrix spectra (`H_LL`, `H_LR`, `H_RL`, `H_RR`), and inverse-transform two outputs.
That preserves independent Both/Mid/Side/Left/Right semantics with one engine
latency, at the cost of more spectral multiply-accumulates and a more complex
kernel builder.

**Recommendation:** record two serial engines as the selected simplicity tradeoff,
not a fundamental consequence. Before accepting 12288 samples, compare the serial
design against a matrix engine for latency, CPU, memory, and implementation risk.

## P1 - "Our Magnitude" Must Mean The Exact Digital V0.5 Transfer Function

Section 5 names `butter_cascade_mag` and the same Butterworth Q law, but this does
not fully specify the magnitude formula. Arthur's `hp_mag/lp_mag` uses an analog
ratio `r=f/fc`. V0.5 uses a bilinear/TPT digital SVF with
`g=tan(pi*fc_eff/srate)`. The two responses diverge toward Nyquist even when their
Q values match.

**Recommendation:** state that kernel bins come from the exact digital
`svf_response`/state-space transfer of V0.5 coefficients, including `fc_eff`, not
Arthur's analog-ratio helper. Test parity at high cutoff and 44.1 kHz, where a
wrong formula is easiest to expose.

## P1 - Kaiser Windowing Invalidates An Unqualified Magnitude-Parity Claim

Sampling the desired magnitude, taking an IFFT, truncating/centering it, and
multiplying by a Kaiser window changes the realized response. The change is largest
around steep cutoffs and narrow resonance. A beta control changes that error again.
Therefore Linear cannot simultaneously equal the analytic Min magnitude exactly
and have an arbitrary window beta.

**Recommendation:** define separate measurable limits for:

- Passband ripple;
- Stopband attenuation;
- Cutoff/peak gain error;
- Resonance peak-frequency and bandwidth error;
- Transition-width error.

Pin the frequency grid and exclude a documented transition neighborhood where
appropriate. Decide beta in the spec before fixing tolerances; a user beta control
makes Min/Linear parity parameter-dependent.

## P1 - "Brickwall" Is Not Infinite Slope After Finite FIR Windowing

The desired magnitude step is mathematically discontinuous, but an 8192-sample
windowed FIR has finite transition width, finite stopband rejection, bin-quantized
cutoff, and pre/post ringing. At the ideal discontinuity, a finite Fourier
approximation also does not preserve an unqualified 0/1 step.

Calling the result Brickwall/infinite-slope without numeric qualifications is too
strong, especially because the same plugin uses "Brick" for a hard ceiling with a
literal guarantee.

**Recommendation:** define Brick as a finite-FIR brick-style slope and pin minimum
stopband attenuation, transition width, passband ripple, cutoff convention, and
maximum ringing for the selected beta/sample rates. Consider a distinct UI label
such as `FIR Brick` to avoid confusion with Mode-B Brick.

## P1 - In-Place Kernel Rebuild Has No Click-Safe State Policy

`need_rebuild` builds a new `Hspec` in `@block`, while FDL history and queued output
still belong to the old kernel. Frequency, Resonance, Slope, beta, or Brick changes
can therefore produce a hybrid of old queued output and new convolution. Rapid
automation can rebuild every block and cause both discontinuities and audio-thread
CPU spikes.

Placement is even riskier: it is absent from the stated kernel signature because
it changes routing rather than magnitude, but old FDL/input/output history remains
encoded in the previous L/R or M/S domain. Recombining it under the new Placement
can leak the wrong channel/domain for several blocks.

**Recommendation:** pin one policy for all topology/kernel changes:

- Dual kernels/pipelines with a delayed-domain crossfade;
- Flush and refill with an explicitly accepted mute/transition;
- Rebuild only while transport is stopped;
- Rate-limit/coalesce automation and declare affected controls non-continuous.

Compare previous parameters individually. Do not port Arthur's weighted floating
`sig` expression as a hash because distinct parameter sets can collide.

## P1 - Off Engines Need A History And Wake-Up Contract

The PDC formula counts only active linear filters, but the spec does not say whether
an Off engine continues collecting input history. If it stops processing, Off->On
starts with empty FDL/output buffers and cannot reproduce the pre-transition signal
needed by a long FIR. If it keeps running an identity/history path, Off is no longer
free in CPU and state terms.

**Recommendation:** specify dormant-engine behavior, buffer reset points, refill
duration, initial output, and PDC timing. Apply the same decision to
Brick<->finite-slope and one-active-filter<->two-active-filter transitions.

## P1 - Placement Routing Is Not Fully Defined For Delayed Dry Lanes

"A single channel duplicated for Mid-only" is not enough to define the output.
For Mid, Side, Left, or Right placement, the untouched complementary component must
be delayed by exactly the same engine latency before recombination. With two serial
engines, the first engine's untouched lane must also enter the second at the same
time origin as its filtered lane.

**Recommendation:** specify encode, two-lane input, filtered lane, delayed-dry lane,
and decode equations for all five Placements. Add impulse and random-signal routing
tests proving that untouched components null after compensating the exact latency.

## P1 - Mode-B Integration Needs A Sample-Level Timing Diagram

The phrase "Mode-B detectors still run un-delayed" is ambiguous. In Linear mode,
the whole downstream signal is already delayed by the HP/LP convolution. Relative
to that stream, Mode B should analyze the current post-HP/LP sample and delay its
dry/correction bus only by `Lk`; externally reported PDC is then linear latency plus
`Lk`. It must not add the linear latency again inside `bus_dry`.

**Recommendation:** pin a sample-index equation for:

- Original input sample;
- Linear HP output and LP output;
- Static/Mode-A processing;
- Mode-B detector sample;
- Mode-B dry-bus write/read and correction sample;
- Final output and reported PDC.

Test all four combinations: no linear/no Mode B, linear only, Mode B only, and both,
with one and two active linear filters. Use impulses to catch double-delay and
off-by-one errors.

## P1 - Kernel Tail And Transport Reset Are Missing

A causalized FIR continues producing output after input silence. Two serial FIRs
have a longer effective tail than one. The spec does not set `ext_tail_size`, define
flush behavior on stop/seek, or say whether @init clears all large buffers on every
transport start.

**Recommendation:** pin `ext_tail_size` (or `-1` automatic detection), transport
start/stop/seek behavior, and offline-render tail expectations. Test an impulse at
the end of a rendered item and verify that the full post-ringing tail is present.
The variable is documented at <https://www.reaper.fm/sdk/js/vars.php>.

## P1 - Verification Can Share The Same Wrong Delay And Scaling

`partitioned == direct` only proves that two Python paths agree on the chosen
kernel. It does not prove JSFX FFT permutation/scaling, absolute latency, channel
routing, or PDC. A shared shift or `1/B`/`1/BD` mistake can pass the proposed three
tests.

**Recommendation:** add permanent tests for:

- Identity/all-pass kernel amplitude and delay;
- Unit impulse gain, full impulse response, and exact peak/centroid sample;
- DC and Nyquist-bin handling;
- `1/BD` kernel-IFFT and `1/B` runtime-IFFT scaling independently;
- JSFX source guards for `fft_permute`/`fft_ipermute` order;
- Arbitrary host block sizes and a hop spanning block boundaries;
- One/two filters, every Placement, Off, Brick, and Mode-B integration;
- Memory page-boundary assertions for every FFT/convolution call.

## P2 - Python Test Scope May Become Impractically Large

A hand-written 8192-point radix-2 FFT is reasonable for a focused oracle, but the
V0.5 parameter matrix multiplied by kernel construction, direct convolution, two
filters, and Brick cases can make the stdlib-only suite slow enough that developers
stop running it.

**Recommendation:** separate fast analytic tests from a small set of full-kernel
golden cases. Use smaller power-of-two kernels for exhaustive partition-bookkeeping
tests and reserve `BD=8192` for representative acceptance cases.

## P2 - Open Decisions Belong In The Spec, Not The Plan

Slider number, beta policy, and Brick behavior in Min mode affect automation,
presets, response tolerances, and safety. Leaving them open while calling the design
ready for an implementation plan creates branching requirements.

**Recommendation:** before planning, pin:

- Exact Phase slider number/default;
- Fixed beta or exact beta slider number/range/default;
- Brick-in-Min behavior (Off vs 96; greying out is not available in stock slider UI
  without explicit `slider_show`/custom UI behavior);
- Whether Phase/Slope/beta are automatable during playback;
- Fixed or dynamic latency policy.

## Suggested Pre-Implementation Edits

1. Replace the contiguous memory note with a 65,536-page-safe exact layout.
2. Resolve even-length symmetry, group delay, and PDC as one mathematical contract.
3. Decide whether doubled serial latency is worth avoiding a 2x2 matrix engine.
4. Define kernel/PDC/Placement/Off transition behavior before promising automation.
5. Pin exact digital V0.5 magnitude and quantitative FIR/Brick tolerances.
6. Add sample-indexed Mode-B integration and delayed-dry Placement equations.
7. Add tail, transport, rebuild-spike, scaling, impulse-latency, and page-boundary
   verification.
8. Close slider/beta/Brick-in-Min open items before writing the implementation plan.
