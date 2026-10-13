#!/usr/bin/env python3
"""
Fetches a direction-balanced set of Statcast plays (EV 90-100, LA 10-30;
default 8 pull / 8 center / 8 oppo, none within 3° of a boundary) from Baseball Savant,
then resolves each to a UUID playId via the MLB Stats API so videos can
be downloaded from sporty-videos.
Saves to anticipation/data.json.
"""
import sys
import os
import json
import time
import requests
import pandas as pd
import io
import math
import argparse

try:
    from pybaseball import statcast
    from pybaseball import cache
    cache.enable()
except ImportError:
    import subprocess
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'pybaseball'], check=True)
    from pybaseball import statcast
    from pybaseball import cache
    cache.enable()

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT = os.path.join(HERE, '..', 'anticipation', 'data.json')
HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── direction ──────────────────────────────────────────────────────────────────

HOME_X, HOME_Y = 125.42, 198.27   # home plate in Statcast hc_x/hc_y space
CENTER_HALF_WIDTH = 15.0          # ±15° = straightaway; splits fair territory into thirds (Savant convention)
BORDERLINE = 3.0                  # within this many degrees of a boundary → ambiguous


def spray_angle(hc_x, hc_y):
    """Degrees from straightaway center: negative = 3B/LF side, positive = 1B/RF side."""
    if pd.isna(hc_x) or pd.isna(hc_y):
        return None
    return math.degrees(math.atan2(float(hc_x) - HOME_X, HOME_Y - float(hc_y)))


def classify_direction(angle, stand):
    if angle is None:
        return None
    if abs(angle) <= CENTER_HALF_WIDTH:
        return 'center'
    to_left = angle < 0
    return 'pull' if to_left == (stand == 'R') else 'oppo'


def is_borderline(angle):
    return angle is not None and abs(abs(angle) - CENTER_HALF_WIDTH) < BORDERLINE



# ── statcast fetch ─────────────────────────────────────────────────────────────

def fetch_window(start, end):
    print(f"  Fetching {start} → {end} ...")
    df = statcast(start, end)
    mask = (
        df['launch_speed'].between(90, 100) &
        df['launch_angle'].between(10, 30) &
        df['type'].eq('X') &
        df['hc_x'].notna() &
        df['hc_y'].notna() &
        df['game_pk'].notna()
    )
    return df[mask].copy()


# ── MLB Stats API UUID lookup ──────────────────────────────────────────────────

_game_cache = {}

def load_game(game_pk):
    gk = int(game_pk)
    if gk not in _game_cache:
        url = f"https://statsapi.mlb.com/api/v1.1/game/{gk}/feed/live"
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            _game_cache[gk] = r.json()['liveData']['plays']['allPlays']
        except Exception as e:
            print(f"    Stats API error for game {gk}: {e}")
            _game_cache[gk] = []
    return _game_cache[int(game_pk)]

def get_play_id(game_pk, at_bat_number, pitch_number, launch_speed, launch_angle):
    """
    Uniquely identify a pitch by at_bat_number + pitch_number.
    at_bat_number in the CSV is 1-indexed; atBatIndex in Stats API is 0-indexed.
    Falls back to EV+LA matching if the index lookup fails.
    """
    all_plays = load_game(game_pk)

    # Primary: use at_bat position + pitch number (guaranteed unique)
    ab_idx = int(at_bat_number) - 1
    if 0 <= ab_idx < len(all_plays):
        for event in all_plays[ab_idx].get('playEvents', []):
            if event.get('pitchNumber') == int(pitch_number):
                hd = event.get('hitData') or {}
                ev = hd.get('launchSpeed')
                pid = event.get('playId')
                if pid and ev and abs(float(ev) - float(launch_speed)) < 1.0:
                    return pid, all_plays[ab_idx], event

    # Fallback: EV + LA (much safer than EV alone)
    for play in all_plays:
        for event in play.get('playEvents', []):
            hd = event.get('hitData') or {}
            ev  = hd.get('launchSpeed')
            la  = hd.get('launchAngle')
            pid = event.get('playId')
            if (pid and ev and la and
                    abs(float(ev) - float(launch_speed)) < 0.2 and
                    abs(float(la) - float(launch_angle)) < 1.0):
                return pid, play, event

    return None


def find_by_play_id(game_pk, play_id):
    for play in load_game(game_pk):
        for event in play.get('playEvents', []):
            if event.get('playId') == play_id:
                return play, event
    return None, None


def feed_fields(play, event, fallback_stand=None):
    """Batter/pitcher/context straight from the Stats API feed.
    (Statcast's `player_name` column is the *pitcher*, so never use it for the batter.)"""
    hd = event.get('hitData') or {}
    coords = hd.get('coordinates') or {}
    matchup = play.get('matchup', {})
    stand = (matchup.get('batSide') or {}).get('code') or fallback_stand
    angle = spray_angle(coords.get('coordX', float('nan')), coords.get('coordY', float('nan')))
    about = play.get('about', {})
    return {
        "batter": matchup.get('batter', {}).get('fullName'),
        "batter_id": matchup.get('batter', {}).get('id'),
        "pitcher": matchup.get('pitcher', {}).get('fullName'),
        "stand": stand,
        "p_throws": (matchup.get('pitchHand') or {}).get('code'),
        "pitch_type": (event.get('details', {}).get('type') or {}).get('description'),
        "pitch_speed": (event.get('pitchData') or {}).get('startSpeed'),
        "trajectory": hd.get('trajectory'),
        "hc_x": coords.get('coordX'),
        "hc_y": coords.get('coordY'),
        "spray_angle": round(angle, 1) if angle is not None else None,
        "direction": classify_direction(angle, stand),
        "borderline": is_borderline(angle),
        "description": play.get('result', {}).get('description'),
        "inning": f"{'Top' if about.get('isTopInning') else 'Bot'} {about.get('inning')}",
    }


def repair():
    """Re-derive batter + direction for an existing data.json without touching clip timings."""
    with open(OUTPUT) as f:
        plays = json.load(f)
    for p in plays:
        play, event = find_by_play_id(p['game_pk'], p['play_id'])
        if play is None:
            print(f"  ! {p['play_id']} not found in game {p['game_pk']}")
            continue
        old_dir = p.get('direction')
        p.update(feed_fields(play, event, p.get('stand')))
        flag = '  (was ' + old_dir + ')' if old_dir != p['direction'] else ''
        print(f"  {p['batter']:25s} ({p['stand']}) vs {p['pitcher']:20s} "
              f"{p['spray_angle']:6.1f}°  {p['direction']}{flag}{'  borderline' if p['borderline'] else ''}")
        time.sleep(0.1)
    with open(OUTPUT, 'w') as f:
        json.dump(plays, f, indent=2, ensure_ascii=False)
    print(f"\nRepaired {len(plays)} plays → anticipation/data.json")


# ── main ───────────────────────────────────────────────────────────────────────

DIRECTIONS = ('pull', 'center', 'oppo')
MAX_PER_BATTER = 2   # spread clips across hitters so no one swing dominates

# Two-week windows spread over the 2024 regular season
# (pybaseball caches each window locally, so re-runs are fast).
WINDOWS = [('2024-07-01', '2024-07-14'), ('2024-04-15', '2024-04-28'), ('2024-05-13', '2024-05-26'),
           ('2024-06-10', '2024-06-23'), ('2024-08-05', '2024-08-18'), ('2024-09-02', '2024-09-15')]


def candidate_pool():
    """Shuffled Statcast rows from every window, so clips span the season (parks, weather, matchups)."""
    pool = pd.concat([fetch_window(start, end) for start, end in WINDOWS])
    print(f"  Pool: {len(pool)} batted balls")
    return pool.sample(frac=1, random_state=42).reset_index(drop=True)



def keepable(p):
    """An existing play worth keeping: playable, not excluded, not on a direction boundary."""
    return not p.get('exclude') and not p.get('borderline') and p.get('direction') in DIRECTIONS


def main(per_dir, fresh):
    # Equal counts per direction, so no single always-guess strategy beats 1/3.
    old = []
    if os.path.exists(OUTPUT) and not fresh:
        with open(OUTPUT) as f:
            old = json.load(f)

    # Keep already-downloaded, already-timed plays where we can (up to per_dir each).
    kept = {d: [] for d in DIRECTIONS}
    for p in old:
        if keepable(p) and len(kept[p['direction']]) < per_dir:
            kept[p['direction']].append(p)
    excluded = [p for p in old if p.get('exclude')]   # kept forever so they're never re-fetched
    dropped = [p for p in old if not p.get('exclude')
               and not any(p is k for ks in kept.values() for k in ks)]
    need = {d: per_dir - len(kept[d]) for d in DIRECTIONS}
    print(f"Keeping {sum(map(len, kept.values()))} existing plays; need "
          + ', '.join(f"{n} {d}" for d, n in need.items()))

    new = {d: [] for d in DIRECTIONS}
    if any(need.values()):
        print("\nFetching Statcast data from Baseball Savant...")
        pool = candidate_pool()
        have_ids = {p['play_id'] for p in old}
        per_batter = {}
        for p in (p for ks in kept.values() for p in ks):
            per_batter[p.get('batter_id')] = per_batter.get(p.get('batter_id'), 0) + 1

        print("\nResolving UUID playIds from MLB Stats API...")
        for _, row in pool.iterrows():
            if all(len(new[d]) >= need[d] for d in DIRECTIONS):
                break
            angle = spray_angle(row['hc_x'], row['hc_y'])
            direction = classify_direction(angle, str(row['stand']))
            if direction is None or is_borderline(angle) or len(new[direction]) >= need[direction]:
                continue
            if pd.isna(row.get('at_bat_number')) or pd.isna(row.get('pitch_number')):
                continue
            if per_batter.get(int(row['batter']), 0) >= MAX_PER_BATTER:
                continue

            gk = int(row['game_pk'])
            ev = float(row['launch_speed'])
            la = float(row['launch_angle'])
            found = get_play_id(gk, int(row['at_bat_number']), int(row['pitch_number']), ev, la)
            if found is None:
                continue
            play_id, feed_play, feed_event = found
            if play_id in have_ids:
                continue
            fields = feed_fields(feed_play, feed_event, str(row['stand']))
            if fields['direction'] != direction or fields['borderline']:
                continue  # feed coordinates disagree with Statcast's; skip rather than guess
            have_ids.add(play_id)
            per_batter[fields['batter_id']] = per_batter.get(fields['batter_id'], 0) + 1

            new[direction].append({
                "play_id": play_id,
                "events": str(row.get('events', '')),
                "launch_speed": round(ev, 1),
                "launch_angle": round(la, 1),
                "game_date": str(row.get('game_date', ''))[:10],
                "game_pk": gk,
                **fields,
                "raw_file": None,
            })
            print(f"  + {fields['batter']:25s} ({fields['stand']})  {direction:6s}  {fields['spray_angle']:6.1f}°")
            time.sleep(0.1)

        short = {d: need[d] - len(new[d]) for d in DIRECTIONS if len(new[d]) < need[d]}
        if short:
            print(f"Warning: pool ran out — still short {short}. Widen the date window.")

    plays = [p for d in DIRECTIONS for p in kept[d] + new[d]] + excluded
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, 'w') as f:
        json.dump(plays, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(plays)} plays → anticipation/data.json  "
          + ' / '.join(f"{sum(p['direction'] == d and not p.get('exclude') for p in plays)} {d}"
                       for d in DIRECTIONS) + f"  (+{len(excluded)} excluded, kept as a blocklist)")
    if dropped:
        print("Dropped:")
        for p in dropped:
            print(f"  - {p.get('batter')}  {p.get('direction')}  "
                  f"({'borderline' if p.get('borderline') else 'over quota'})")
    print("\nNext: python scripts/download_clips.py && python scripts/process_clips.py, then review.")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--repair', action='store_true',
                    help='fix batter names + spray-angle direction in the existing data.json')
    ap.add_argument('--per-dir', type=int, default=8,
                    help='plays per direction (pull/center/oppo); default 8')
    ap.add_argument('--fresh', action='store_true',
                    help='ignore the existing data.json instead of topping it up')
    args = ap.parse_args()
    repair() if args.repair else main(args.per_dir, args.fresh)
