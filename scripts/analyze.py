#!/usr/bin/env python3
"""
Can people anticipate where a batted ball goes before contact?

Reads the trials the game logs (data/trials.jsonl) and tests the hypotheses
below. Chance is exactly 1/3 by design: every session shows the same number of
pull, center and oppo clips, so any strategy that ignores the video averages 1/3.

Hypotheses, fixed before data collection
  H1  Overall accuracy is above 1/3.
  H2  Accuracy is higher frozen mid-swing than at release — information arriving
      during the pitch is being read, not just the batter, count or fielders.
      (Pitch location is visible by mid-flight, so this covers pitch + swing.)
  H3  Mid-swing accuracy beats the best "no-video" strategy from
      scripts/baselines.py, which knows each hitter's tendencies AND the pitch
      location (~48% on these clips). This is the bar for reading the swing itself.
      Sharpest form: on clips where that strategy is WRONG, mid-swing accuracy
      still rises above release.

Primary tests use a mixed model with crossed random effects for players and
clips, so a "yes" must hold across people AND generalize to other batted balls
— one prolific player or a few easy clips can't carry it. Intervals come from
a crossed bootstrap (resampling players and clips), which runs wide. By-player
and by-clip t-tests and pooled binomial tests are shown for reference.

Planned sample: PLANNED_SESSIONS sessions. Results before then are interim —
don't stop early because a p-value dips under 0.05.

Quality gates: a trial is dropped if the frame shown was more than half a frame
late (could leak contact) or more than 3 frames early (would blur the freeze
points), and by default if the player had seen the clip before (memory, not
anticipation).

  python scripts/analyze.py [--include-repeats]
  python scripts/analyze.py --simulate 0.33,0.36,0.45 --sessions 60   # check the tests on fake players
"""
import argparse
import warnings
import json
import math
import os
import random
from collections import defaultdict

import numpy as np
from scipy import stats

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TRIALS = os.path.join(ROOT, 'data', 'trials.jsonl')
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
BASELINES = os.path.join(ROOT, 'anticipation', 'baselines.json')
CHANCE = 1 / 3
LEADS = {'release': 24 / 60, 'flight': 12 / 60, 'swing': 6 / 60}
FRAME = 1 / 60
PLANNED_SESSIONS = 60        # ≈1080 trials; ~80% power for swing−release of 10 points
MIN_PLAYER_TRIALS = 9
BOOT = 2000            # bootstrap resamples


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


def crossed_boot(rows, which, null, seed=7):
    """Crossed bootstrap: resample players AND clips with replacement, so the
    interval covers both "would other people do this well" and "would they on
    other clips". which = 'acc' (accuracy) or 'diff' (swing − release).
    Returns (low, high, one-sided p that the true value is <= null)."""
    if not rows:
        return (float('nan'), float('nan'), 1.0)
    players = sorted({r['player_id'] for r in rows})
    clips = sorted({r['play_id'] for r in rows})
    if len(players) < 2:
        return (float('nan'), float('nan'), 1.0)
    pi = np.array([players.index(r['player_id']) for r in rows])
    ci = np.array([clips.index(r['play_id']) for r in rows])
    y = np.array([r['correct'] for r in rows], dtype=float)
    sw = np.array([r['lead'] == 'swing' for r in rows], dtype=float)
    rl = np.array([r['lead'] == 'release' for r in rows], dtype=float)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(BOOT):
        wp = np.bincount(rng.integers(len(players), size=len(players)), minlength=len(players))
        wc = np.bincount(rng.integers(len(clips), size=len(clips)), minlength=len(clips))
        w = wp[pi] * wc[ci]
        if which == 'acc':
            if w.sum():
                vals.append((w * y).sum() / w.sum())
        else:
            a, b = (w * sw).sum(), (w * rl).sum()
            if a and b:
                vals.append((w * y * sw).sum() / a - (w * y * rl).sum() / b)
    vals = np.sort(vals)
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1], float((vals <= null).mean()))


def unit_scores(rows, unit, which):
    """Per-player or per-clip scores: accuracy − 1/3 ('acc') or swing − release ('diff')."""
    groups = defaultdict(list)
    for r in rows:
        groups[r[unit]].append(r)
    out = []
    for rs in groups.values():
        if which == 'acc':
            out.append(acc(rs) - CHANCE)
        else:
            d = lead_diff(rs)
            if d is not None:
                out.append(d)
    return out


def mixed_test(rows, which):
    """Linear mixed model with crossed random intercepts for player and clip, so the
    answer generalizes to other people AND other batted balls. which='acc' tests
    accuracy > 1/3; which='diff' tests mid-swing > release. Returns one-sided p."""
    import pandas as pd
    import statsmodels.formula.api as smf
    df = pd.DataFrame({'y': [float(r['correct']) for r in rows],
                       'player': [r['player_id'] for r in rows],
                       'clip': [r['play_id'] for r in rows],
                       'lead': [r['lead'] for r in rows]})
    if which == 'diff':
        df = df[df['lead'].isin(['release', 'swing'])].copy()
        df['swing'] = (df['lead'] == 'swing').astype(float)
        formula, term = 'y ~ swing', 'swing'
    else:
        df['y'] = df['y'] - CHANCE
        formula, term = 'y ~ 1', 'Intercept'
    if df['player'].nunique() < 3 or df['clip'].nunique() < 3:
        return 1.0
    df['all'] = 1
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        fit = smf.mixedlm(formula, df, groups='all', re_formula='0',
                          vc_formula={'player': '0 + C(player)', 'clip': '0 + C(clip)'}).fit(reml=True)
    z = fit.params[term] / fit.bse[term]
    return float(stats.norm.sf(z))


def unit_t(rows, unit, which):
    """One-sample t over players or over clips (supporting evidence)."""
    x = unit_scores(rows, unit, which)
    if len(x) < 3 or np.std(x) == 0:
        return None
    t = stats.ttest_1samp(x, 0, alternative='greater')
    return t.statistic, t.pvalue


def on_target(r):
    """The frame shown may be up to 3 frames early (safe; freeze points are ≥0.1s apart)
    but never more than half a frame late (could show contact)."""
    early = (r['contact_time'] - r['lead_s']) - r['frozen_at']
    return -0.5 * FRAME <= early <= 3 * FRAME


def acc(rows):
    return sum(r['correct'] for r in rows) / len(rows) if rows else None


def lead_diff(rows):
    s = [r['correct'] for r in rows if r['lead'] == 'swing']
    rel = [r['correct'] for r in rows if r['lead'] == 'release']
    return (sum(s) / len(s) - sum(rel) / len(rel)) if s and rel else None


# ── reporting ──────────────────────────────────────────────────────────────────
def line(label, k, n, ref=CHANCE):
    if not n:
        return f"  {label:24s}     —"
    lo, hi = wilson(k, n)
    return (f"  {label:24s} {k:4d}/{n:<4d} {k / n:6.1%}   95% CI {lo:5.1%}–{hi:5.1%}   "
            f"p = {binom_p(k, n, ref):.2g}")


def analyze(rows, clips, include_repeats=False, quiet=False):
    """Returns {'H1': p, 'H2': p} (player-level); prints the full report unless quiet."""
    say = (lambda *a, **k: None) if quiet else print

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

    by_player = defaultdict(list)
    for r in keep:
        by_player[r['player_id']].append(r)
    players = {p: rs for p, rs in by_player.items() if len(rs) >= MIN_PLAYER_TRIALS}
    out = {}

    # H1
    k = sum(r['correct'] for r in keep)
    say("\nH1  OVERALL ACCURACY  (chance = 33.3%)")
    say(line('pooled (reference)', k, len(keep)))
    p = mixed_test(keep, 'acc')
    out['H1'] = p
    say(f"  {'mixed model (primary)':24s} {acc(keep):6.1%}   p = {p:.2g}   (random player + clip effects)")
    if not quiet:
        lo, hi, _ = crossed_boot(keep, 'acc', CHANCE)
        if not math.isnan(lo):
            say(f"  {'players × clips interval':24s} {lo:5.1%}–{hi:5.1%}  (crossed bootstrap; runs wide)")
        for unit, label in (('player_id', 'by player'), ('play_id', 'by clip')):
            t = unit_t(keep, unit, 'acc')
            if t:
                say(f"  {label:24s} t = {t[0]:.2f}, p = {t[1]:.2g}")

    # H2
    say("\nH2  BY FREEZE POINT  (release = control: swing not started)")
    for l in LEADS:
        sub = [r for r in keep if r['lead'] == l]
        say(line(l, sum(r['correct'] for r in sub), len(sub)))
    pooled = lead_diff(keep)
    if pooled is not None:
        p = mixed_test(keep, 'diff')
        out['H2'] = p
        say(f"  {'swing − release':24s} {pooled:+6.1%}   mixed model p = {p:.2g}   (primary)")
        if not quiet:
            lo, hi, _ = crossed_boot(keep, 'diff', 0)
            if not math.isnan(lo):
                say(f"  {'players × clips interval':24s} {lo:+.1%} to {hi:+.1%}  (crossed bootstrap; runs wide)")
            for unit, label in (('player_id', 'by player'), ('play_id', 'by clip')):
                t = unit_t(keep, unit, 'diff')
                if t:
                    say(f"  {label:24s} t = {t[0]:.2f}, p = {t[1]:.2g}")

    # H3
    if os.path.exists(BASELINES):
        with open(BASELINES) as f:
            base = json.load(f)
        best = max(base['strategies'], key=lambda s: s['acc'])
        sw = [r for r in keep if r['lead'] == 'swing']
        say(f"\nH3  MID-SWING vs BEST NO-VIDEO STRATEGY  ({best['label'].lower()}: {best['acc']:.1%} on "
            f"{best['n']} clips)")
        say(line('mid-swing vs that rate', sum(r['correct'] for r in sw), len(sw), ref=best['acc']))
        rel = [r for r in keep if r['lead'] == 'release']
        say(line('release vs that rate', sum(r['correct'] for r in rel), len(rel), ref=best['acc']))

        # The sharpest test: clips where the scouting report points the wrong way. Someone
        # leaning on hitter + location priors is pulled toward a wrong answer there, so
        # mid-swing beating release on these clips means reading what the report can't see.
        rule = f"{best['key']}/{best['rule']}"
        report_right = {c['play_id'] for c in base['per_clip'] if c[rule] == c['direction']}
        say(f"\n  Split by whether {best['label'].lower()} gets the clip right "
            f"({len(report_right)}/{best['n']} clips):")
        for label, want in (('report right', True), ('report WRONG', False)):
            sub = [r for r in keep if (r['play_id'] in report_right) == want]
            for l in LEADS:
                ls = [r for r in sub if r['lead'] == l]
                say(line(f'{label} · {l}', sum(r['correct'] for r in ls), len(ls)))
        wrong = [r for r in keep if r['play_id'] not in report_right]
        d = lead_diff(wrong)
        if d is not None:
            p = mixed_test(wrong, 'diff')
            say(f"  {'report WRONG: swing − release':32s} {d:+6.1%}   mixed model p = {p:.2g}")

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
def simulate(true_acc, n_sessions, clips, seed, clip_sd=0.0):
    """Fake sessions with the game's design: 6 per direction, leads balanced, given accuracy per lead.
    clip_sd adds clip-to-clip difficulty (SD on the log-odds scale, drawn fresh each study), the
    situation where a test that treats these clips as fixed would overstate the evidence."""
    rng = random.Random(seed)
    offset = {pid: rng.gauss(0, clip_sd) for pid in clips}
    sig = lambda x: 1 / (1 + math.exp(-x))
    # Spread on the log-odds scale shifts the average; pick each lead's center so the
    # average over the clip population is exactly true_acc (bisection on a fixed sample).
    r99 = random.Random(99)
    draws = [r99.gauss(0, clip_sd) for _ in range(4000)]
    center = {}
    for l, target in true_acc.items():
        lo, hi = -6.0, 6.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if sum(sig(mid + e) for e in draws) / len(draws) < target:
                lo = mid
            else:
                hi = mid
        center[l] = (lo + hi) / 2

    def p_right(c, l):
        return sig(center[l] + offset[c['play_id']])

    pool = {d: [c for c in clips.values() if c.get('direction') == d] for d in ('pull', 'center', 'oppo')}
    rows = []
    for s in range(n_sessions):
        trials = []
        for d, cs in pool.items():
            leads = [l for l in LEADS for _ in range(2)]
            rng.shuffle(leads)
            for c, l in zip(rng.sample(cs, 6), leads):
                trials.append((c, l))
        rng.shuffle(trials)
        for i, (c, l) in enumerate(trials):
            right = rng.random() < p_right(c, l)
            guess = c['direction'] if right else rng.choice([d for d in pool if d != c['direction']])
            rows.append({'player_id': f'p{s}', 'session_id': f's{s}', 'trial': i, 'play_id': c['play_id'],
                         'lead': l, 'lead_s': LEADS[l], 'guess': guess, 'direction': c['direction'],
                         'correct': right, 'frozen_at': 3.0 - LEADS[l] - 0.01, 'contact_time': 3.0,
                         'repeat': False, 'experience': 'none'})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include-repeats', action='store_true')
    ap.add_argument('--simulate', help='true accuracy at release,flight,swing e.g. 0.33,0.36,0.45')
    ap.add_argument('--sessions', type=int, default=PLANNED_SESSIONS)
    ap.add_argument('--runs', type=int, default=200, help='simulated studies for the power estimate')
    ap.add_argument('--clip-sd', type=float, default=0.0, help='clip difficulty spread (log-odds SD)')
    args = ap.parse_args()

    with open(DATA) as f:
        clips = {p['play_id']: p for p in json.load(f) if p.get('contact_verified') and not p.get('exclude')}

    if args.simulate:
        true_acc = dict(zip(LEADS, map(float, args.simulate.split(','))))
        print(f"Simulating {args.runs} studies of {args.sessions} sessions, true accuracy {true_acc}, "
              f"clip SD {args.clip_sd}")
        hits = defaultdict(int)
        for i in range(args.runs):
            res = analyze(simulate(true_acc, args.sessions, clips, i, args.clip_sd), clips, quiet=True)
            for h, p in res.items():
                hits[h] += p < 0.05
        for h in ('H1', 'H2'):
            print(f"  {h} significant in {hits[h] / args.runs:.0%} of studies")
        print("(At 0.333,0.333,0.333 these are false-positive rates and should be ≈5%.)")
        return

    if not os.path.exists(TRIALS):
        print("No trials yet — play some rounds at /anticipation/ with scripts/server.py running.")
        return
    with open(TRIALS) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    analyze(rows, clips, args.include_repeats)


if __name__ == '__main__':
    main()
