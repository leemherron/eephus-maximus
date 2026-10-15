#!/usr/bin/env python3
"""
Can people anticipate where a batted ball goes before contact?

Every clip freezes 2 frames (1/30 s) before the bat meets the ball. This reads
the trials the game logs (data/trials.jsonl) and tests the hypotheses below.
Chance is exactly 1/3 by design: every session shows the same number of pull,
center and oppo clips, so any strategy that ignores the video averages 1/3.

Hypotheses, fixed before data collection (H1 and H3 are primary)
  H1  Accuracy is above 1/3: people anticipate the direction at all.
  H3  On clips where the "scouting report" — the best no-video strategy from
      scripts/baselines.py (each hitter's tendencies + the pitch location) —
      points the wrong way, accuracy is still above 1/3. Someone leaning on
      hitter/location priors scores BELOW 1/3 on those clips, so beating 1/3
      there means reading the swing itself. Simulations: ~85-100% power at 60
      sessions for players who read swings moderately well.
  H2  (descriptive) People vs the scouting report trial by trial on the same
      clips. Reported, but with little power — its per-trial differences are
      noisy — so it is not a primary test.

Primary tests are linear mixed models with crossed random intercepts for
players and clips, so a "yes" must hold across people AND generalize to other
batted balls — one prolific player or a few easy clips can't carry it.
`--simulate` checks the tests on fake players (false-positive rate, power).

Planned sample: PLANNED_SESSIONS sessions. Results before then are interim —
don't stop early because a p-value dips under 0.05.

Quality gates: a trial is dropped if the frame shown was more than half a frame
late (could show contact) or more than 3 frames early, and by default if the
player had seen the clip before (memory, not anticipation).

  python scripts/analyze.py [--include-repeats]
  python scripts/analyze.py --simulate 0.40,0.38 --clip-sd 0.8   # accuracy on report-right, report-wrong clips
"""
import argparse
import json
import math
import os
import random
import warnings
from collections import defaultdict

import numpy as np
from scipy import stats

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TRIALS = os.path.join(ROOT, 'data', 'trials.jsonl')
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
BASELINES = os.path.join(ROOT, 'anticipation', 'baselines.json')
CHANCE = 1 / 3
FRAME = 1 / 60
FREEZE_FRAMES = 2            # keep in sync with app.js
PLANNED_SESSIONS = 60        # ≈1080 trials
BOOT = 2000                  # bootstrap resamples


# ── stats helpers ──────────────────────────────────────────────────────────────
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def binom_p(k, n, p=CHANCE):
    return stats.binomtest(k, n, p, alternative='greater').pvalue if n else 1.0


def bh(pvals):
    """Benjamini-Hochberg adjusted p-values (same order as input)."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 1.0
    for rank, i in reversed(list(enumerate(order, start=1))):
        running = min(running, pvals[i] * m / rank)
        adj[i] = running
    return adj


def mixed_test(rows, y):
    """One-sided test that mean(y) > 0, from a linear mixed model with crossed
    random intercepts for player and clip. Returns (estimate, p)."""
    import pandas as pd
    import statsmodels.formula.api as smf
    df = pd.DataFrame({'y': y, 'player': [r['player_id'] for r in rows], 'clip': [r['play_id'] for r in rows]})
    if df['player'].nunique() < 3 or df['clip'].nunique() < 3 or df['y'].std() == 0:
        return (float(df['y'].mean()) if len(df) else float('nan'), 1.0)
    df['all'] = 1
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        fit = smf.mixedlm('y ~ 1', df, groups='all', re_formula='0',
                          vc_formula={'player': '0 + C(player)', 'clip': '0 + C(clip)'}).fit(reml=True)
    est, se = fit.params['Intercept'], fit.bse['Intercept']
    return (float(est), float(stats.norm.sf(est / se)) if se > 0 else 1.0)


def crossed_boot(rows, y, seed=7):
    """95% interval for mean(y), resampling players AND clips (runs wide)."""
    players = sorted({r['player_id'] for r in rows})
    clips = sorted({r['play_id'] for r in rows})
    if len(players) < 2 or len(clips) < 2:
        return (float('nan'), float('nan'))
    pi = np.array([players.index(r['player_id']) for r in rows])
    ci = np.array([clips.index(r['play_id']) for r in rows])
    y = np.asarray(y, dtype=float)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(BOOT):
        wp = np.bincount(rng.integers(len(players), size=len(players)), minlength=len(players))
        wc = np.bincount(rng.integers(len(clips), size=len(clips)), minlength=len(clips))
        w = wp[pi] * wc[ci]
        if w.sum():
            vals.append((w * y).sum() / w.sum())
    vals = np.sort(vals)
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])


def on_target(r):
    """The frame shown may be up to 3 frames early but never more than half a frame late."""
    early = (r['contact_time'] - r['lead_s']) - r['frozen_at']
    return -0.5 * FRAME <= early <= 3 * FRAME


def line(label, k, n, ref=CHANCE):
    if not n:
        return f"  {label:28s}     —"
    lo, hi = wilson(k, n)
    return (f"  {label:28s} {k:4d}/{n:<4d} {k / n:6.1%}   95% CI {lo:5.1%}–{hi:5.1%}   "
            f"p = {binom_p(k, n, ref):.2g}")


def load_scout():
    """play_id -> the scouting report's pick (best no-video strategy), or None."""
    if not os.path.exists(BASELINES):
        return None, None
    with open(BASELINES) as f:
        base = json.load(f)
    best = max(base['strategies'], key=lambda s: s['acc'])
    rule = f"{best['key']}/{best['rule']}"
    return {c['play_id']: c[rule] for c in base['per_clip']}, best


# ── analysis ───────────────────────────────────────────────────────────────────
def analyze(rows, clips, include_repeats=False, quiet=False):
    """Prints the report (unless quiet) and returns {'H1': p, 'H2': p, 'H3': p}."""
    say = (lambda *a, **k: None) if quiet else print
    scout, best = load_scout()

    off = [r for r in rows if not on_target(r)]
    repeats = [r for r in rows if r.get('repeat')]
    keep = [r for r in rows if r not in off and (include_repeats or not r.get('repeat'))]
    sessions = len({r['session_id'] for r in rows})

    say(f"\n{len(rows)} trials · {len({r['player_id'] for r in rows})} players · "
        f"{sessions} sessions ({sessions}/{PLANNED_SESSIONS} planned"
        f"{' — interim' if sessions < PLANNED_SESSIONS else ''})")
    say(f"Dropped: {len(off)} frozen off-target (>½ frame late or >3 frames early), "
        f"{0 if include_repeats else len(repeats)} repeat views")
    if not keep:
        return {}
    out = {}

    # H1
    k = sum(r['correct'] for r in keep)
    say("\nH1  BEAT CHANCE  (33.3%)")
    say(line('pooled (reference)', k, len(keep)))
    est, out['H1'] = mixed_test(keep, [r['correct'] - CHANCE for r in keep])
    say(f"  {'mixed model (primary)':28s} {est + CHANCE:6.1%}   p = {out['H1']:.2g}")
    if not quiet:
        lo, hi = crossed_boot(keep, [r['correct'] for r in keep])
        if not math.isnan(lo):
            say(f"  {'players × clips interval':28s} {lo:5.1%}–{hi:5.1%}  (crossed bootstrap; runs wide)")

    # H2 / H3
    if scout:
        scored = [r for r in keep if r['play_id'] in scout]
        right = [r for r in scored if scout[r['play_id']] == r['direction']]
        wrong = [r for r in scored if scout[r['play_id']] != r['direction']]
        s_acc = len(right) / len(scored) if scored else float('nan')

        say(f"\nH2  VS THE SCOUTING REPORT  ({best['label'].lower()}, no video; descriptive)")
        say(f"  {'people':28s} {sum(r['correct'] for r in scored) / len(scored):6.1%}   "
            f"scouting report on the same trials {s_acc:6.1%}")
        diff = [r['correct'] - (scout[r['play_id']] == r['direction']) for r in scored]
        est, out['H2'] = mixed_test(scored, diff)
        say(f"  {'people − report':28s} {est:+6.1%}   p = {out['H2']:.2g}")

        say("\nH3  CLIPS WHERE THE SCOUTING REPORT IS WRONG  (priors alone score below 33%)")
        say(line('report right', sum(r['correct'] for r in right), len(right)))
        say(line('report WRONG', sum(r['correct'] for r in wrong), len(wrong)))
        if wrong:
            est, out['H3'] = mixed_test(wrong, [r['correct'] - CHANCE for r in wrong])
            say(f"  {'report WRONG, mixed model':28s} {est + CHANCE:6.1%}   p = {out['H3']:.2g}   (primary)")
            agree = sum(r['guess'] == scout[r['play_id']] for r in wrong) / len(wrong)
            say(f"  {'guessed what the report said':28s} {agree:6.1%} of report-wrong trials")

    # secondary
    say("\nLEARNING  (does accuracy rise within a session?)")
    first = [r for r in keep if r['trial'] < 9]
    second = [r for r in keep if r['trial'] >= 9]
    say(line('trials 1–9', sum(r['correct'] for r in first), len(first)))
    say(line('trials 10–18', sum(r['correct'] for r in second), len(second)))

    say("\nBY EXPERIENCE")
    for exp in ['none', 'youth', 'college']:
        sub = [r for r in keep if r.get('experience') == exp]
        say(line(exp, sum(r['correct'] for r in sub), len(sub)))

    say("\nCONFUSION  (rows = actual, cols = guessed)")
    dirs = ['pull', 'center', 'oppo']
    say('              ' + ''.join(f'{d:>8s}' for d in dirs))
    for d in dirs:
        say(f'  {d:10s}  ' + ''.join(
            f"{sum(1 for r in keep if r['direction'] == d and r['guess'] == g):8d}" for g in dirs))

    by_clip = defaultdict(list)
    for r in keep:
        by_clip[r['play_id']].append(r)
    clip_rows = [(pid, sum(r['correct'] for r in rs), len(rs)) for pid, rs in by_clip.items() if len(rs) >= 5]
    if clip_rows:
        adj = bh([binom_p(k, n) for _, k, n in clip_rows])
        ranked = sorted(zip(clip_rows, adj), key=lambda x: x[1])
        say("\nREADABLE PITCHES  (clips with ≥5 trials; BH-adjusted p < 0.05 marked ★)")
        for (pid, k, n), q in ranked[:15]:
            c = clips.get(pid, {})
            say(f"  {'★' if q < 0.05 else ' '} {c.get('batter', pid[:8]):22s} {c.get('direction', ''):6s} "
                f"{k:3d}/{n:<3d} {k / n:5.0%}  adj p = {q:.2g}")
    say()
    return out


# ── simulation: do the tests work? ─────────────────────────────────────────────
def simulate(acc_right, acc_wrong, n_sessions, clips, scout, seed, clip_sd=0.0):
    """Fake sessions with the game's design (6 clips per direction). Players are right with
    probability acc_right on clips the scouting report gets right and acc_wrong where it's
    wrong; clip_sd adds clip-to-clip difficulty (log-odds SD), centered so those averages hold.
    On report-wrong clips, half of the wrong guesses follow the report (a prior-led player)."""
    rng = random.Random(seed)
    offset = {pid: rng.gauss(0, clip_sd) for pid in clips}
    sig = lambda x: 1 / (1 + math.exp(-x))
    r99 = random.Random(99)
    draws = [r99.gauss(0, clip_sd) for _ in range(4000)]

    def center(target):
        lo, hi = -8.0, 8.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if sum(sig(mid + e) for e in draws) / len(draws) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    c_right, c_wrong = center(acc_right), center(acc_wrong)
    pool = {d: [c for c in clips.values() if c.get('direction') == d] for d in ('pull', 'center', 'oppo')}
    rows = []
    for s in range(n_sessions):
        trials = [c for cs in pool.values() for c in rng.sample(cs, 6)]
        rng.shuffle(trials)
        for i, c in enumerate(trials):
            report_wrong = scout.get(c['play_id'], c['direction']) != c['direction']
            right = rng.random() < sig((c_wrong if report_wrong else c_right) + offset[c['play_id']])
            if right:
                guess = c['direction']
            elif report_wrong and rng.random() < 0.5:
                guess = scout[c['play_id']]
            else:
                guess = rng.choice([d for d in pool if d != c['direction']])
            rows.append({'player_id': f'p{s}', 'session_id': f's{s}', 'trial': i, 'play_id': c['play_id'],
                         'lead': 'pre2', 'lead_s': FREEZE_FRAMES * FRAME, 'guess': guess,
                         'direction': c['direction'], 'correct': guess == c['direction'],
                         'frozen_at': 3.0 - FREEZE_FRAMES * FRAME - 0.005, 'contact_time': 3.0,
                         'repeat': False, 'experience': 'none'})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include-repeats', action='store_true')
    ap.add_argument('--simulate', help='true accuracy on report-right,report-wrong clips, e.g. 0.40,0.38')
    ap.add_argument('--sessions', type=int, default=PLANNED_SESSIONS)
    ap.add_argument('--runs', type=int, default=200, help='simulated studies')
    ap.add_argument('--clip-sd', type=float, default=0.0, help='clip difficulty spread (log-odds SD)')
    args = ap.parse_args()

    with open(DATA) as f:
        clips = {p['play_id']: p for p in json.load(f) if p.get('contact_frame_checked') and not p.get('exclude')}

    if args.simulate:
        a_right, a_wrong = map(float, args.simulate.split(','))
        scout, _ = load_scout()
        print(f"Simulating {args.runs} studies of {args.sessions} sessions: accuracy {a_right:.0%} where the "
              f"report is right, {a_wrong:.0%} where it's wrong, clip SD {args.clip_sd}")
        hits = defaultdict(int)
        for i in range(args.runs):
            res = analyze(simulate(a_right, a_wrong, args.sessions, clips, scout, i, args.clip_sd), clips, quiet=True)
            for h, p in res.items():
                hits[h] += p < 0.05
        for h in ('H1', 'H2', 'H3'):
            print(f"  {h} significant in {hits[h] / args.runs:.0%} of studies")
        return

    if not os.path.exists(TRIALS):
        print("No trials yet — play some rounds at /anticipation/ with scripts/server.py running.")
        return
    with open(TRIALS) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    analyze(rows, clips, args.include_repeats)


if __name__ == '__main__':
    main()
