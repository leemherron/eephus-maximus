#!/usr/bin/env python3
"""
Downloads and trims video clips for each play in anticipation/data.json.
Requires yt-dlp (pip install yt-dlp).
Optional: ffprobe (part of ffmpeg) for accurate video duration.

Updates data.json with clip_file, duration, and pause_time for each play.
pause_time is where the video will freeze in the game (just before contact).
"""
import sys
import os
import json
import time
import glob
import subprocess
import shutil

try:
    import yt_dlp
except ImportError:
    subprocess.run([sys.executable, '-m', 'pip', 'install', 'yt-dlp'], check=True)
    import yt_dlp

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, '..', 'anticipation', 'data.json')
CLIPS_DIR = os.path.join(HERE, '..', 'anticipation', 'clips')

PAUSE_OFFSET = 0.5  # seconds before end of clip to freeze


def get_duration_ffprobe(path):
    if not shutil.which('ffprobe'):
        return None
    result = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
         '-of', 'csv=p=0', path],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return None


def get_duration_ytdlp(url):
    """Extract duration from yt-dlp info without downloading."""
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return info.get('duration')
    except Exception:
        return None


def download(url, sv_id):
    outtmpl = os.path.join(CLIPS_DIR, f'{sv_id}.%(ext)s')
    opts = {
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'format': 'mp4/best[ext=mp4]/best',
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    for ext in ('mp4', 'webm', 'mkv', 'mov'):
        candidate = os.path.join(CLIPS_DIR, f'{sv_id}.{ext}')
        if os.path.exists(candidate):
            return candidate, f'clips/{sv_id}.{ext}'
    return None, None


def main():
    with open(DATA_FILE) as f:
        plays = json.load(f)

    os.makedirs(CLIPS_DIR, exist_ok=True)

    failed = []
    for i, play in enumerate(plays):
        sv_id = play['sv_id']
        url = f'https://baseballsavant.mlb.com/sporty-videos?playId={sv_id}'
        label = f"[{i+1:02d}/25] {play['batter']} ({sv_id})"

        # Skip if already downloaded
        existing = glob.glob(os.path.join(CLIPS_DIR, f'{sv_id}.*'))
        if existing and play.get('clip_file'):
            print(f"{label} — already done, skipping")
            continue

        print(f"{label} ...", end=' ', flush=True)

        duration = get_duration_ytdlp(url)

        try:
            abs_path, rel_path = download(url, sv_id)
        except Exception as e:
            print(f"FAILED ({e})")
            failed.append(sv_id)
            continue

        if abs_path is None:
            print("FAILED (file not found after download)")
            failed.append(sv_id)
            continue

        # Prefer ffprobe duration; fall back to yt-dlp info
        file_duration = get_duration_ffprobe(abs_path) or duration or 4.0
        pause_time = round(max(1.0, file_duration - PAUSE_OFFSET), 2)

        play['clip_file'] = rel_path
        play['duration'] = round(file_duration, 2)
        play['pause_time'] = pause_time

        print(f"OK  ({file_duration:.1f}s → pause at {pause_time:.1f}s)")

        # Save after each clip so partial progress isn't lost
        with open(DATA_FILE, 'w') as f:
            json.dump(plays, f, indent=2)

        time.sleep(0.75)

    ready = sum(1 for p in plays if p.get('clip_file'))
    print(f"\n{ready}/25 clips ready.")
    if failed:
        print(f"Failed sv_ids: {failed}")
    print(f"\nTo play:")
    print(f"  cd {os.path.normpath(os.path.join(HERE, '..'))}")
    print(f"  python -m http.server 8080")
    print(f"  open http://localhost:8080/anticipation/")


if __name__ == '__main__':
    main()
