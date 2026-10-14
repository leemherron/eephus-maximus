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
      location (~50% on these clips). This is the bar for reading the swing itself.
      Sharpest form: on clips where that strategy is WRONG, mid-swing accuracy
      still rises above release.

Primary tests are at the player level, so one prolific player can't carry the
result: a one-sided t-test of per-player accuracy vs 1/3 (H1) and of
per-player (swing − release) vs 0 (H2). 95% intervals come from resampling
players (cluster bootstrap). Pooled binomial tests are shown for reference.

Planned sample: PLANNED_SESSIONS sessions. Results before then are interim —
don't stop early because a p-value dips under 0.05.

Quality gates: a trial is dropped if the frame shown was more than a frame off
the intended freeze (later could leak contact), and by default if the player had
seen the clip before (memory, not anticipation).

  python scripts/analyze.py [--include-repeats]
  python scripts/analyze.py --simulate 0.33,0.36,0.45 --sessions 60   # check the tests on fake players
"""
import argparse
import json
import math
import os
import random
from collections import defaultdict

from scipy import stats

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
TRIALS = os.path.join(ROOT, 'data', 'trials.jsonl')
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
BASELINES = os.path.join(ROOT, 'anticipation', 'baselines.json')
CHANCE = 1 / 3
LEADS = {'release': 24 / 60, 'flight': 12 / 60, 'swing': 4 / 60}
FRAME = 1 / 60
PLANNED_SESSIONS = 60        # ≈1080 trials; ~80% power for swing−release of 10 points
MIN_PLAYER_TRIALS = 9
BOOT = 4000            # bootstrap resamples


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


def cluster_boot(rows, stat, rng):
    """95% interval for stat(rows), resampling whole players."""
    by_p = defaultdict(list)
    for r in rows:
        by_p[r['player_id']].append(r)
    players = list(by_p.values())
    if len(players) < 2:
        return (float('nan'), float('nan'))
    vals = []
    for _ in range(BOOT):
        sample = [r for p in rng.choices(players, k=len(players)) for r in p]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])


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
    rng = random.Random(7)

    off = [r for r in rows if abs(r['frozen_at'] - (r['contact_time'] - r['lead_s'])) > 1.5 * FRAME]
    repeats = [r for r in rows if r.get('repeat')]
    keep = [r for r in rows if r not in off and (include_repeats or not r.get('repeat'))]
    sessions = len({r['session_id'] for r in rows})

    say(f"\n{len(rows)} trials · {len({r['player_id'] for r in rows})} players · "
        f"{sessions} sessions ({sessions}/{PLANNED_SESSIONS} planned"
        f"{' — interim' if sessions < PLANNED_SESSIONS else ''})")
    say(f"Dropped: {len(off)} frozen off-target, {0 if include_repeats else len(repeats)} repeat views")
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
    say(line('pooled', k, len(keep)))
    lo, hi = cluster_boot(keep, acc, rng) if not quiet else (0, 0)   # bootstrap only for the printed report
    accs = [acc(rs) for rs in players.values()]
    if len(accs) >= 3:
        t = stats.ttest_1samp(accs, CHANCE, alternative='greater')
        out['H1'] = t.pvalue
        say(f"  {'per player (primary)':24s} mean {sum(accs) / len(accs):6.1%} over {len(accs)} players   "
            f"player-bootstrap CI {lo:5.1%}–{hi:5.1%}   t = {t.statistic:.2f}, p = {t.pvalue:.2g}")
    else:
        say(f"  per-player test needs ≥3 players with ≥{MIN_PLAYER_TRIALS} trials (have {len(accs)})")

    # H2
    say("\nH2  BY FREEZE POINT  (release = control: swing not started)")
    for l in LEADS:
        sub = [r for r in keep if r['lead'] == l]
        say(line(l, sum(r['correct'] for r in sub), len(sub)))
    diffs = [d for d in (lead_diff(rs) for rs in players.values()) if d is not None]
    lo, hi = cluster_boot(keep, lead_diff, rng) if not quiet else (0, 0)
    pooled = lead_diff(keep)
    if pooled is not None:
        say(f"  {'swing − release':24s} {pooled:+6.1%}   player-bootstrap CI {lo:+.1%} to {hi:+.1%}")
    if len(diffs) >= 3:
        t = stats.ttest_1samp(diffs, 0, alternative='greater')
        out['H2'] = t.pvalue
        say(f"  {'per player (primary)':24s} mean {sum(diffs) / len(diffs):+6.1%} over {len(diffs)} players   "
            f"t = {t.statistic:.2f}, p = {t.pvalue:.2g}")

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
            lo, hi = cluster_boot(wrong, lead_diff, rng) if not quiet else (0, 0)
            say(f"  {'report WRONG: swing − release':32s} {d:+6.1%}   player-bootstrap CI {lo:+.1%} to {hi:+.1%}")

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
def simulate(true_acc, n_sessions, clips, seed):
    """Fake sessions with the game's design: 6 per direction, leads balanced, given accuracy per lead."""
    rng = random.Random(seed)
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
            right = rng.random() < true_acc[l]
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
    args = ap.parse_args()

    with open(DATA) as f:
        clips = {p['play_id']: p for p in json.load(f) if p.get('contact_verified') and not p.get('exclude')}

    if args.simulate:
        true_acc = dict(zip(LEADS, map(float, args.simulate.split(','))))
        print(f"Simulating {args.runs} studies of {args.sessions} sessions, true accuracy {true_acc}")
        hits = defaultdict(int)
        for i in range(args.runs):
            res = analyze(simulate(true_acc, args.sessions, clips, i), clips, quiet=True)
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
