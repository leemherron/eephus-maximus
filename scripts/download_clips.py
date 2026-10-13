#!/usr/bin/env python3
"""
Downloads and trims video clips for each play in anticipation/data.json.
Requires yt-dlp (pip install yt-dlp).
Optional: ffprobe (part of ffmpeg) for accurate video duration.

Updates data.json with clip_file and duration for each play.
pause_time (where the game freezes, just before contact) is NOT set here: Savant
clips put contact ~3.3-3.6s in, nowhere near a fixed offset from the end.
Set it with the editor's "Auto-detect contact" button, then eyeball each clip.
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


def download(url, file_id):
    outtmpl = os.path.join(CLIPS_DIR, f'{file_id}.%(ext)s')
    opts = {
        'outtmpl': outtmpl,
        'quiet': True,
        'no_warnings': True,
        'format': 'mp4/best[ext=mp4]/best',
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])

    for ext in ('mp4', 'webm', 'mkv', 'mov'):
        candidate = os.path.join(CLIPS_DIR, f'{file_id}.{ext}')
        if os.path.exists(candidate):
            return candidate, f'clips/{file_id}.{ext}'
    return None, None


def main():
    with open(DATA_FILE) as f:
        plays = json.load(f)

    os.makedirs(CLIPS_DIR, exist_ok=True)

    failed = []
    for i, play in enumerate(plays):
        play_id = play.get('play_id') or play.get('sv_id')
        if not play_id:
            print(f"[{i+1:02d}/{len(plays)}] {play['batter']} — no play_id, skipping")
            continue

        url = f'https://baseballsavant.mlb.com/sporty-videos?playId={play_id}'
        safe_id = play_id.replace('/', '_')
        label = f"[{i+1:02d}/{len(plays)}] {play['batter']}"

        # Skip if already downloaded (check by file existence, not clip_file field)
        existing_file = None
        for ext in ('mp4', 'webm', 'mkv', 'mov'):
            candidate = os.path.join(CLIPS_DIR, f'{safe_id}.{ext}')
            if os.path.exists(candidate):
                existing_file = (candidate, f'clips/{safe_id}.{ext}')
                break

        if existing_file:
            abs_path, rel_path = existing_file
            play['clip_file'] = rel_path
            if not play.get('duration'):
                dur = get_duration_ffprobe(abs_path) or 4.0
                play['duration'] = round(dur, 2)
            print(f"{label} — already on disk, skipping")
            continue

        print(f"{label} ...", end=' ', flush=True)

        duration = get_duration_ytdlp(url)

        try:
            abs_path, rel_path = download(url, safe_id)
        except Exception as e:
            print(f"FAILED ({e})")
            failed.append(play_id)
            continue

        if abs_path is None:
            print("FAILED (file not found after download)")
            failed.append(play_id)
            continue

        file_duration = get_duration_ffprobe(abs_path) or duration or 4.0

        play['clip_file']  = rel_path
        play['duration']   = round(file_duration, 2)

        print(f"OK  ({file_duration:.1f}s)")

        # Save after each clip so partial progress isn't lost
        with open(DATA_FILE, 'w') as f:
            json.dump(plays, f, indent=2, ensure_ascii=False)

        time.sleep(0.75)

    with open(DATA_FILE, 'w') as f:
        json.dump(plays, f, indent=2, ensure_ascii=False)

    ready = sum(1 for p in plays if p.get('clip_file'))
    print(f"\n{ready}/{len(plays)} clips ready.")
    if failed:
        print(f"Failed sv_ids: {failed}")
    print("\nNext, set pause times:")
    print("  python scripts/editor_server.py")
    print("  open http://localhost:8080/anticipation/editor.html  → Auto-detect contact, then review each clip")
    print("Then play at http://localhost:8080/anticipation/")


if __name__ == '__main__':
    main()
