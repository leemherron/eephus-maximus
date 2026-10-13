#!/usr/bin/env python3
"""
Can people anticipate where a batted ball goes before contact?

Reads the trials the game logs (data/trials.jsonl) and tests accuracy against
chance. Chance is exactly 1/3 by design: every session shows the same number of
pull, center and oppo clips, so any strategy that ignores the video averages 1/3.

  python scripts/analyze.py [--include-repeats]

What it reports
  - Overall accuracy vs 1/3 (exact one-sided binomial test, Wilson 95% CI).
  - Per-player accuracy vs 1/3 (t-test across players), since trials from the
    same person aren't independent.
  - Accuracy by freeze point. "release" is the control (only batter, count,
    fielders and pitcher are visible); a rise toward "swing" is evidence the
    swing itself is being read.
  - Per clip, with Benjamini-Hochberg correction: which pitches are readable.

Quality gates: a trial is dropped if the frame shown was more than a frame
off the intended freeze (later could leak contact), and by default if the player had seen the clip
before (memory, not anticipation).
"""
import argparse
import json
import math
import os
from collections import defaultdict

from scipy import stats

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TRIALS = os.path.join(ROOT, 'data', 'trials.jsonl')
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
CHANCE = 1 / 3
LEAD_ORDER = ['release', 'flight', 'swing']
FRAME = 1 / 60


def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    d = 1 + z * z / n
    c = (ph + z * z / (2 * n)) / d
    h = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d
    return (max(0, c - h), min(1, c + h))


def binom_p(k, n):
    return stats.binomtest(k, n, CHANCE, alternative='greater').pvalue if n else 1.0


def line(label, k, n):
    if not n:
        return f"  {label:22s}     —"
    lo, hi = wilson(k, n)
    return (f"  {label:22s} {k:4d}/{n:<4d} {k / n:6.1%}   95% CI {lo:5.1%}–{hi:5.1%}   "
            f"p = {binom_p(k, n):.2g}")


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--include-repeats', action='store_true',
                    help='keep trials where the player had already seen the clip')
    args = ap.parse_args()

    if not os.path.exists(TRIALS):
        print("No trials yet — play some rounds at /anticipation/ with scripts/server.py running.")
        return
    with open(TRIALS) as f:
        rows = [json.loads(l) for l in f if l.strip()]
    with open(DATA) as f:
        clips = {p['play_id']: p for p in json.load(f)}

    # The frame shown must be the intended one (±1 frame). Later would risk showing contact;
    # much earlier means the trial really belongs to a different condition.
    late = [r for r in rows if abs(r['frozen_at'] - (r['contact_time'] - r['lead_s'])) > 1.5 * FRAME]
    repeats = [r for r in rows if r.get('repeat')]
    keep = [r for r in rows if r not in late and (args.include_repeats or not r.get('repeat'))]

    print(f"\n{len(rows)} trials logged · {len({r['player_id'] for r in rows})} players · "
          f"{len({r['session_id'] for r in rows})} sessions")
    print(f"Dropped: {len(late)} frozen off-target (>1 frame from intended), "
          f"{0 if args.include_repeats else len(repeats)} repeat views")
    if not keep:
        return

    k = sum(r['correct'] for r in keep)
    print("\nOVERALL  (chance = 33.3%)")
    print(line('all trials', k, len(keep)))

    by_player = defaultdict(list)
    for r in keep:
        by_player[r['player_id']].append(r['correct'])
    accs = [sum(v) / len(v) for v in by_player.values() if len(v) >= 9]
    if len(accs) >= 3:
        t = stats.ttest_1samp(accs, CHANCE, alternative='greater')
        print(f"  {'per player (≥9 trials)':22s} mean {sum(accs) / len(accs):6.1%} across {len(accs)} players   "
              f"t = {t.statistic:.2f}, p = {t.pvalue:.2g}")
    else:
        print(f"  per-player test needs ≥3 players with ≥9 trials (have {len(accs)})")

    print("\nBY FREEZE POINT  (release = control: no swing visible yet)")
    by_lead = {l: [r['correct'] for r in keep if r['lead'] == l] for l in LEAD_ORDER}
    for l in LEAD_ORDER:
        print(line(l, sum(by_lead[l]), len(by_lead[l])))
    a, b = by_lead['release'], by_lead['swing']
    if a and b:
        p1, p2 = sum(a) / len(a), sum(b) / len(b)
        pooled = (sum(a) + sum(b)) / (len(a) + len(b))
        se = math.sqrt(pooled * (1 - pooled) * (1 / len(a) + 1 / len(b))) or float('inf')
        z = (p2 - p1) / se
        print(f"  swing − release: {p2 - p1:+.1%}  (z = {z:.2f}, one-sided p = {stats.norm.sf(z):.2g})")

    print("\nBY EXPERIENCE")
    for exp in ['none', 'youth', 'college']:
        sub = [r['correct'] for r in keep if r.get('experience') == exp]
        print(line(exp, sum(sub), len(sub)))

    print("\nCONFUSION  (rows = actual, cols = guessed)")
    dirs = ['pull', 'center', 'oppo']
    print('            ' + ''.join(f'{d:>8s}' for d in dirs))
    for d in dirs:
        print(f'  {d:8s}  ' + ''.join(
            f"{sum(1 for r in keep if r['direction'] == d and r['guess'] == g):8d}" for g in dirs))

    by_clip = defaultdict(list)
    for r in keep:
        by_clip[r['play_id']].append(r)
    clip_rows = [(pid, sum(r['correct'] for r in rs), len(rs)) for pid, rs in by_clip.items() if len(rs) >= 5]
    if clip_rows:
        adj = bh([binom_p(k, n) for _, k, n in clip_rows])
        ranked = sorted(zip(clip_rows, adj), key=lambda x: x[1])
        print(f"\nREADABLE PITCHES  (clips with ≥5 trials; BH-adjusted p < 0.05 marked ★)")
        for (pid, k, n), q in ranked[:15]:
            c = clips.get(pid, {})
            star = '★' if q < 0.05 else ' '
            print(f"  {star} {c.get('batter', pid[:8]):22s} {c.get('direction', ''):6s} "
                  f"{k:3d}/{n:<3d} {k / n:5.0%}  adj p = {q:.2g}")
    print()


if __name__ == '__main__':
    main()
