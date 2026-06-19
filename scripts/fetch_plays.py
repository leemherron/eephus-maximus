#!/usr/bin/env python3
"""
Fetches 25 Statcast plays matching the anticipation game criteria:
  exit velocity 90-100 mph, launch angle 10-30 degrees
Saves metadata to anticipation/data.json.
"""
import sys
import os
import json
import pandas as pd

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


def classify_direction(hc_x, stand):
    """Pull/Center/Oppo from hit coordinate and batter handedness."""
    if pd.isna(hc_x):
        return None
    # hc_x ~0=far left, ~250=far right (catcher's view)
    # RHB: pull=left field (low x), oppo=right field (high x)
    # LHB: pull=right field (high x), oppo=left field (low x)
    if hc_x < 100:
        return 'pull' if stand == 'R' else 'oppo'
    elif hc_x > 150:
        return 'oppo' if stand == 'R' else 'pull'
    else:
        return 'center'


def fmt_name(raw):
    """'Alvarez, Yordan' → 'Yordan Alvarez'"""
    raw = str(raw)
    if ', ' in raw:
        last, first = raw.split(', ', 1)
        return f"{first} {last}"
    return raw


def fetch_window(start, end):
    print(f"  Fetching {start} → {end} ...")
    df = statcast(start, end)
    mask = (
        df['launch_speed'].between(90, 100) &
        df['launch_angle'].between(10, 30) &
        df['type'].eq('X') &
        df['sv_id'].notna() &
        df['hc_x'].notna() &
        df['hc_y'].notna()
    )
    return df[mask].copy()


def main():
    print("Fetching Statcast data from Baseball Savant...")

    filtered = fetch_window('2024-07-01', '2024-07-14')
    print(f"  Found {len(filtered)} matching plays so far.")

    if len(filtered) < 25:
        more = fetch_window('2024-07-15', '2024-07-31')
        filtered = pd.concat([filtered, more])
        print(f"  Extended to full July: {len(filtered)} plays.")

    if len(filtered) < 25:
        more = fetch_window('2024-06-01', '2024-06-30')
        filtered = pd.concat([filtered, more])
        print(f"  Extended to June: {len(filtered)} plays.")

    if len(filtered) < 25:
        sys.exit(f"Only {len(filtered)} plays found. Widen the date range.")

    sample = filtered.sample(25, random_state=42).reset_index(drop=True)

    plays = []
    for _, row in sample.iterrows():
        direction = classify_direction(row['hc_x'], row['stand'])
        if direction is None:
            continue
        plays.append({
            "sv_id": str(row['sv_id']),
            "batter": fmt_name(row.get('player_name', row['batter'])),
            "stand": str(row['stand']),
            "events": str(row.get('events', '')),
            "launch_speed": round(float(row['launch_speed']), 1),
            "launch_angle": round(float(row['launch_angle']), 1),
            "hc_x": round(float(row['hc_x']), 1),
            "direction": direction,
            "game_date": str(row.get('game_date', ''))[:10],
            "clip_file": None,
            "duration": None,
            "pause_time": None,
        })

    with open(OUTPUT, 'w') as f:
        json.dump(plays, f, indent=2)

    print(f"\nSaved {len(plays)} plays → anticipation/data.json\n")
    for p in plays:
        print(f"  {p['batter']:25s} ({p['stand']})  {p['direction']:6s}  "
              f"EV {p['launch_speed']} mph  LA {p['launch_angle']}°  {p['game_date']}")
    print("\nNext: run  python scripts/download_clips.py")


if __name__ == '__main__':
    main()
