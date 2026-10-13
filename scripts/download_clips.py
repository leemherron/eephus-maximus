#!/usr/bin/env python3
"""
Downloads the Baseball Savant video for each play in anticipation/data.json
into raw_clips/ (gitignored) and records it as the play's raw_file.

Raw clips are never served to players; process_clips.py trims and re-encodes
them into anticipation/clips/. Requires yt-dlp (pip install yt-dlp).
"""
import json
import os
import subprocess
import sys
import time

try:
    import yt_dlp
except ImportError:
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'yt-dlp'], check=True)
    import yt_dlp

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA_FILE = os.path.join(ROOT, 'anticipation', 'data.json')
RAW_DIR = os.path.join(ROOT, 'raw_clips')


def download(play_id):
    path = os.path.join(RAW_DIR, f'{play_id}.mp4')
    opts = {
        'outtmpl': os.path.join(RAW_DIR, f'{play_id}.%(ext)s'),
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'format': 'mp4/best[ext=mp4]/best',
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([f'https://baseballsavant.mlb.com/sporty-videos?playId={play_id}'])
    return path if os.path.exists(path) else None


def save(plays):
    with open(DATA_FILE, 'w') as f:
        json.dump(plays, f, indent=2, ensure_ascii=False)


def main():
    with open(DATA_FILE) as f:
        plays = json.load(f)
    os.makedirs(RAW_DIR, exist_ok=True)

    failed = []
    for i, play in enumerate(plays):
        if play.get('exclude'):
            continue
        play_id = play['play_id']
        rel = f'raw_clips/{play_id}.mp4'
        if os.path.exists(os.path.join(ROOT, rel)):
            play['raw_file'] = rel
            continue

        print(f"[{i + 1:03d}/{len(plays)}] {play['batter']} ...", end=' ', flush=True)
        try:
            path = download(play_id)
        except Exception as e:
            path = None
            print(f"FAILED ({e})", end='')
        if path is None:
            print()
            failed.append(play_id)
            play['exclude'] = True
            play['exclude_reason'] = 'no video on Savant'
            continue
        play['raw_file'] = rel
        print("OK")
        save(plays)                      # keep partial progress
        time.sleep(0.5)

    save(plays)
    ready = sum(1 for p in plays if p.get('raw_file') and not p.get('exclude'))
    print(f"\n{ready} raw clips ready ({len(failed)} failed).")
    print("Next: python scripts/process_clips.py, then review the sheets in review/.")


if __name__ == '__main__':
    main()
