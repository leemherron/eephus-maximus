#!/usr/bin/env python3
"""
How well could someone do WITHOUT reading the swing?

Beating 1/3 proves the video carries information, but some of that could come
from things a fan knows before the pitch: who's hitting and where the pitch is.
This scores "no-video" strategies on the game's own clips, giving a higher bar
than chance for the release/flight/swing results to be compared against.

Strategies (each predicts one direction per clip):
  hitter     — the batter's most common direction on similar 2024 batted balls
               (90-100 mph, 10-30°), leaving the clip itself out
  location   — the most common direction league-wide for pitches that far
               inside/outside, by batter handedness
  combined   — hitter tendency x pitch location (naive Bayes)

Clips are balanced 1/3 each, so each strategy is scored two ways: naive
(argmax of the natural probabilities) and balance-aware (divide out the
natural base rates first — what a player who knows the rounds are balanced
should do). The better of the two is reported.

Writes anticipation/baselines.json for the results page.
Usage:  python scripts/baselines.py
"""
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_plays import classify_direction, is_borderline, spray_angle  # noqa: E402

from pybaseball import cache, statcast_batter  # noqa: E402
cache.enable()

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
OUT = os.path.join(ROOT, 'anticipation', 'baselines.json')
SEASON = ('2024-03-20', '2024-09-30')
DIRS = ('pull', 'center', 'oppo')
LOC_BINS = [-9, -0.6, -0.2, 0.2, 0.6, 9]   # "inside-ness" in feet (positive = toward the batter)
SMOOTH = 1.0                               # add-one smoothing on direction counts


def inside(plate_x, stand):
    """Horizontal location with positive = inside (toward the batter), any handedness."""
    return -plate_x if stand == 'R' else plate_x


def loc_bin(x):
    for i in range(len(LOC_BINS) - 1):
        if LOC_BINS[i] <= x < LOC_BINS[i + 1]:
            return i
    return None


def batter_season(batter_id):
    df = statcast_batter(SEASON[0], SEASON[1], batter_id)
    df = df[df['launch_speed'].between(90, 100) & df['launch_angle'].between(10, 30)
            & df['type'].eq('X') & df['hc_x'].notna() & df['hc_y'].notna() & df['plate_x'].notna()]
    rows = []
    for _, r in df.iterrows():
        a = spray_angle(r['hc_x'], r['hc_y'])
        if a is None or is_borderline(a):
            continue
        rows.append({'game_pk': int(r['game_pk']), 'ab': int(r['at_bat_number']), 'stand': r['stand'],
                     'dir': classify_direction(a, r['stand']), 'in': inside(float(r['plate_x']), r['stand'])})
    return rows


_feeds = {}


def pitch_x(play):
    """plate_x of the clip's pitch, from the MLB feed."""
    gk = play['game_pk']
    if gk not in _feeds:
        _feeds[gk] = requests.get(f"https://statsapi.mlb.com/api/v1.1/game/{gk}/feed/live",
                                  timeout=20).json()['liveData']['plays']['allPlays']
    for p in _feeds[gk]:
        for ev in p['playEvents']:
            if ev.get('playId') == play['play_id']:
                return p['about']['atBatIndex'] + 1, ev['pitchData']['coordinates']['pX']
    return None, None


def dist(counter):
    tot = sum(counter[d] for d in DIRS) + SMOOTH * 3
    return {d: (counter[d] + SMOOTH) / tot for d in DIRS}


def main():
    with open(DATA) as f:
        clips = [p for p in json.load(f) if p.get('contact_frame_checked') and not p.get('exclude')]

    print(f"Loading 2024 seasons for {len({c['batter_id'] for c in clips})} batters (cached after first run)...")
    seasons = {}
    for i, bid in enumerate(sorted({c['batter_id'] for c in clips})):
        seasons[bid] = batter_season(bid)
        print(f"  {i + 1}", end='\r', flush=True)
    league = [r for rows in seasons.values() for r in rows]
    print(f"  {len(league)} comparable batted balls")

    for c in clips:
        c['_ab'], px = pitch_x(c)
        c['_in'] = inside(px, c['stand']) if px is not None else None
        time.sleep(0.05)

    def is_clip(r, c):
        return r['game_pk'] == c['game_pk'] and r['ab'] == c['_ab']

    results = {}
    per_clip = []
    for c in clips:
        st = c['stand']
        lg = [r for r in league if r['stand'] == st and not is_clip(r, c)]
        base = dist(Counter(r['dir'] for r in lg))                       # natural base rates
        own = [r for r in seasons[c['batter_id']] if not is_clip(r, c)]
        hitter = dist(Counter(r['dir'] for r in own))
        b = loc_bin(c['_in']) if c['_in'] is not None else None
        same_bin = [r for r in lg if loc_bin(r['in']) == b]
        location = dist(Counter(r['dir'] for r in same_bin)) if b is not None else base
        # naive Bayes: P(d | hitter, loc) ∝ P(d | hitter) · P(d | loc) / P(d)
        comb = {d: hitter[d] * location[d] / base[d] for d in DIRS}

        preds = {}
        for name, p in (('hitter', hitter), ('location', location), ('combined', comb)):
            preds[f'{name}/naive'] = max(DIRS, key=lambda d: p[d])
            preds[f'{name}/balanced'] = max(DIRS, key=lambda d: p[d] / base[d])
        per_clip.append({'play_id': c['play_id'], 'direction': c['direction'], 'n_hitter': len(own), **preds})
        for k, v in preds.items():
            results.setdefault(k, []).append(v == c['direction'])

    n = len(clips)
    print(f"\nNo-video strategies on the {n} game clips (chance = 33.3%)")
    best = {}
    for k, hits in sorted(results.items()):
        acc = sum(hits) / n
        print(f"  {k:20s} {sum(hits):3d}/{n}  {acc:6.1%}")
        name = k.split('/')[0]
        if name not in best or acc > best[name]['acc']:
            best[name] = {'acc': acc, 'k': sum(hits), 'n': n, 'rule': k.split('/')[1]}

    labels = {'hitter': "Knowing each hitter's tendencies", 'location': 'Knowing the pitch location',
              'combined': 'Knowing both'}
    out = {'n_clips': n, 'generated': time.strftime('%Y-%m-%d'),
           'strategies': [{'key': k, 'label': labels[k], **v} for k, v in best.items()],
           'per_clip': per_clip}
    with open(OUT, 'w') as f:
        json.dump(out, f, indent=2)
    print(f"\nBest of each → {os.path.relpath(OUT, ROOT)}")
    for s in out['strategies']:
        print(f"  {s['label']:34s} {s['acc']:6.1%}  ({s['rule']})")


if __name__ == '__main__':
    main()
