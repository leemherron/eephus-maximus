#!/usr/bin/env python3
"""
Turns raw Savant downloads (raw_clips/) into game clips (anticipation/clips/).

For each play:
  1. Find bat-ball contact in the raw clip from the audio: the crack of the bat
     is the sharpest high-frequency transient. Savant clips put contact
     ~3.2-3.7s in, so only that window is searched. A contact time that has
     been checked by eye (contact_verified) is never overwritten.
  2. Trim to [contact - PRE, contact + POST] and re-encode at constant 60fps,
     960 wide, with a keyframe every 0.25s, so seeking is exact and files are ~2MB.
     In the processed clip, contact is always at t = PRE.
  3. Write review sheets (review/<play_id>.jpg) showing the frames the game can
     freeze on, plus one frame after contact, for checking by eye.

Usage:  python scripts/process_clips.py [--force] [--only PLAY_ID ...]
"""
import argparse
import json
import os
import subprocess

import numpy as np
from PIL import Image, ImageDraw

import imageio_ffmpeg

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
OUT_DIR = os.path.join(ROOT, 'anticipation', 'clips')
REVIEW_DIR = os.path.join(ROOT, 'review')

PRE, POST = 3.0, 4.5          # seconds kept before / after contact
SEARCH = (2.5, 4.6)           # where to look for contact in the raw clip
SR = 16000                    # audio analysis sample rate
WIN = 0.005                   # 5ms energy windows
WEAK = 150                    # peak/median below this → flag for a closer look

FREEZE_FRAMES = 2           # the game freezes 2 frames (60fps) before contact — keep in sync with app.js


def detect_contact(raw_path):
    pcm = subprocess.run(
        [FFMPEG, '-v', 'error', '-i', raw_path, '-ac', '1', '-ar', str(SR), '-f', 's16le', '-'],
        capture_output=True, check=True).stdout
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
    d = np.diff(x)                                   # first difference = crude high-pass
    n = int(SR * WIN)
    e = (d[: len(d) // n * n].reshape(-1, n) ** 2).sum(axis=1)
    lo, hi = int(SEARCH[0] / WIN), min(len(e), int(SEARCH[1] / WIN))
    peak = lo + int(np.argmax(e[lo:hi]))
    onset = peak
    while onset > 0 and e[onset - 1] > e[peak] * 0.25:   # walk back to where the transient starts
        onset -= 1
    strength = float(e[peak] / max(np.median(e), 1e-12))
    return round(onset * WIN, 3), round(strength)


def encode(raw_path, out_path, contact):
    start = max(0.0, contact - PRE)
    subprocess.run(
        [FFMPEG, '-v', 'error', '-y', '-i', raw_path, '-ss', f'{start:.3f}', '-t', f'{PRE + POST:.3f}',
         # 960 wide at CRF 27 keeps bat and ball as sharp as 1280/CRF 24 at under half the size
         '-vf', 'fps=60,scale=960:-2', '-c:v', 'libx264', '-preset', 'slow', '-crf', '27',
         '-g', '15', '-keyint_min', '15', '-sc_threshold', '0', '-pix_fmt', 'yuv420p',
         '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', out_path],
        check=True)
    return round(contact - start, 3)   # contact time inside the processed clip (PRE unless clipped at 0)


def frame(path, t, crop=None):
    """The frame nearest time t. ffmpeg returns the first frame at or after the seek
    point, and encoded frames sit a hair before each 1/60 s mark, so seek half a frame
    early — otherwise requests drift onto the next frame and can repeat a frame."""
    vf = 'scale=1280:720'
    if crop:
        vf += f',crop={crop}'
    png = subprocess.run(
        [FFMPEG, '-v', 'error', '-ss', f'{max(0.0, t - 0.5 / 60):.5f}', '-i', path, '-frames:v', '1', '-vf', vf,
         '-f', 'image2pipe', '-vcodec', 'png', '-'], capture_output=True, check=True).stdout
    from io import BytesIO
    return Image.open(BytesIO(png)).convert('RGB')


def review_sheet(play, clip_path, contact):
    """Top row: full frames 0.2s before, at the freeze, at contact, and after. Bottom row: the batter zone, same
    times plus +0.10s (must show the swing through / ball gone)."""
    shots = [('-0.2s', -0.2), (f'freeze (-{FREEZE_FRAMES}f)', -FREEZE_FRAMES / 60),
             ('contact', 0.0), ('+0.10s', 0.10)]
    W = 400
    sheet = Image.new('RGB', (W * 4, 225 + 300 + 28), (0, 0, 0))
    g = ImageDraw.Draw(sheet)
    title = (f"{play['batter']} ({play['stand']})  {play['direction']}  "
             f"{play.get('spray_angle')}°  contact {contact:.3f}s  strength {play.get('contact_strength')}")
    g.text((6, 6), title, fill=(255, 255, 0))
    for i, (label, dt) in enumerate(shots):
        full = frame(clip_path, contact + dt).resize((W, 225))
        zone = frame(clip_path, contact + dt, crop='512:384:384:0').resize((W, 300))  # middle of the CF view
        sheet.paste(full, (i * W, 28))
        sheet.paste(zone, (i * W, 28 + 225))
        g.text((i * W + 6, 32), label, fill=(255, 255, 0))
    os.makedirs(REVIEW_DIR, exist_ok=True)
    out = os.path.join(REVIEW_DIR, f"{play['play_id']}.jpg")
    sheet.save(out, quality=82)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--force', action='store_true', help='re-encode clips that already exist')
    ap.add_argument('--only', nargs='*', help='process just these play_ids')
    args = ap.parse_args()

    with open(DATA) as f:
        plays = json.load(f)
    os.makedirs(OUT_DIR, exist_ok=True)

    for p in plays:
        if args.only and p['play_id'] not in args.only:
            continue
        if p.get('exclude'):
            continue
        raw = os.path.join(ROOT, p.get('raw_file') or '')
        if not p.get('raw_file') or not os.path.exists(raw):
            continue
        out = os.path.join(OUT_DIR, f"{p['play_id']}.mp4")
        if os.path.exists(out) and p.get('clip_file') and not args.force:
            continue

        if not p.get('contact_verified'):
            p['contact_raw'], p['contact_strength'] = detect_contact(raw)
        p['contact_time'] = encode(raw, out, p['contact_raw'])
        p['clip_file'] = f"clips/{p['play_id']}.mp4"
        p['duration'] = round(PRE + POST, 2)
        sheet = review_sheet(p, out, p['contact_time'])
        flag = '' if p.get('contact_verified') else (
            '  ← weak peak, check closely' if p['contact_strength'] < WEAK else '  (unverified)')
        print(f"  {p['batter']:24s} contact {p['contact_raw']:.3f}s → {os.path.relpath(sheet, ROOT)}{flag}")

        with open(DATA, 'w') as f:      # save as we go
            json.dump(plays, f, indent=2, ensure_ascii=False)

    todo = [p for p in plays if p.get('clip_file') and not p.get('contact_verified') and not p.get('exclude')]
    print(f"\n{len(todo)} clip(s) need review: open review/*.jpg, then mark each with "
          "`python scripts/review.py ok|bad|contact ...`")


if __name__ == '__main__':
    main()
