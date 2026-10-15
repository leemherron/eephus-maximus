#!/usr/bin/env python3
"""
Mark clips after looking at their review sheets (review/<play_id>.jpg) — the
command-line twin of anticipation/editor.html. A clip only enters the game once
it is verified, because a wrong contact time could freeze after the ball is hit.

  python scripts/review.py list                    unreviewed clips
  python scripts/review.py pages [N]               stack unreviewed sheets N per image → review/pages/
  python scripts/review.py ok ID [ID ...]          contact time is right, camera is the CF view
  python scripts/review.py contact ID SECONDS      contact is actually at SECONDS in the game clip (then verified)
  python scripts/review.py bad ID "reason"         exclude (also blocks it from being re-fetched)
  python scripts/review.py strips [ID ...]         frame-by-frame strips around contact → review/strips/
  python scripts/review.py frame-ok ID [ID ...]    strip checked: recorded contact is the true contact frame
  python scripts/review.py shift ID FRAMES         strip checked: true contact is FRAMES away (e.g. -2 = 2 earlier)
  python scripts/review.py leakcheck [ID ...]      the exact frame the game freezes on (plus the 2 before it,
                                                   nothing after) → review/leak/, for a blind "has it been hit?" audit
  python scripts/review.py leak-ok ID [ID ...]     freeze frame audited: ball clearly not yet hit (required by the game)

The game freezes 2 frames before contact, so it only uses clips whose contact frame
was checked on a strip (contact_frame_checked) and whose exact freeze frame then passed
a blind leak audit (leak_audit = passed). Clips where the ball can't be seen while the
bat is at the hitting point, or where no swing has started at the freeze, fail it.

IDs can be any unique prefix of the play_id.
"""
import json
import os
import sys

from PIL import Image

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
DATA = os.path.join(ROOT, 'anticipation', 'data.json')
REVIEW = os.path.join(ROOT, 'review')


def load():
    with open(DATA) as f:
        return json.load(f)


def save(plays):
    with open(DATA, 'w') as f:
        json.dump(plays, f, indent=2, ensure_ascii=False)


def find(plays, prefix):
    hits = [p for p in plays if p['play_id'].startswith(prefix)]
    if len(hits) != 1:
        sys.exit(f"'{prefix}' matches {len(hits)} plays")
    return hits[0]


def unreviewed(plays):
    return [p for p in plays if p.get('clip_file') and not p.get('contact_verified') and not p.get('exclude')]


STRIP_OFFSETS = list(range(-8, 4))     # frames around the recorded contact


def strips(plays, prefixes):
    """One image per clip: the 12 frames from 8 before to 3 after the recorded contact,
    zoomed on the batter, from the processed clip players actually see."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from PIL import ImageDraw
    from process_clips import frame
    out_dir = os.path.join(REVIEW, 'strips')
    os.makedirs(out_dir, exist_ok=True)
    todo = [p for p in plays if p.get('clip_file') and not p.get('exclude')
            and (not prefixes or any(p['play_id'].startswith(x) for x in prefixes))]
    W, H = 400, 300
    for n, p in enumerate(todo, 1):
        sheet = Image.new('RGB', (W * 6, (H + 18) * 2 + 24))
        g = ImageDraw.Draw(sheet)
        g.text((6, 6), f"#{n:03d} {p['play_id'][:8]}  {p['batter']} ({p['stand']})", fill=(255, 255, 0))
        for i, off in enumerate(STRIP_OFFSETS):
            img = frame(os.path.join(ROOT, 'anticipation', p['clip_file']), p['contact_time'] + off / 60,
                        # righties stand on the far (right) side of the plate in the center-field view
                        crop='480:360:560:30' if p['stand'] == 'R' else '480:360:360:30').resize((W, H))
            x, y = (i % 6) * W, 24 + (i // 6) * (H + 18)
            sheet.paste(img, (x, y + 18))
            g.text((x + 6, y + 3), f"{off:+d}f" + ('  <- recorded contact' if off == 0 else ''), fill=(255, 255, 0))
        name = os.path.join(out_dir, f"{n:03d}_{p['play_id'][:8]}.jpg")
        sheet.save(name, quality=85)
    print(f"{len(todo)} strips → review/strips/")


def leakcheck(plays, prefixes):
    """For each playable clip: the freeze frame the game shows, zoomed, after the two frames
    before it — so a reviewer can tell the moving ball from the strike-zone graphic — and
    nothing later. Reviewers aren't told anything about contact times."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from PIL import ImageDraw
    from process_clips import frame
    out_dir = os.path.join(REVIEW, 'leak')
    os.makedirs(out_dir, exist_ok=True)
    todo = [p for p in plays if p.get('clip_file') and p.get('contact_frame_checked') and not p.get('exclude')
            and (not prefixes or any(p['play_id'].startswith(x) for x in prefixes))]
    W, H = 640, 480
    for n, p in enumerate(todo, 1):
        freeze = p['contact_time'] - 2 / 60
        crop = '480:360:560:30' if p['stand'] == 'R' else '480:360:360:30'
        path = os.path.join(ROOT, 'anticipation', p['clip_file'])
        sheet = Image.new('RGB', (W * 3, H + 24))
        g = ImageDraw.Draw(sheet)
        g.text((6, 6), f"#{n:03d} {p['play_id'][:8]}  ({p['stand']}HB)", fill=(255, 255, 0))
        for i, (off, label) in enumerate([(-2, 'two frames earlier'), (-1, 'one frame earlier'), (0, 'FREEZE FRAME')]):
            img = frame(path, freeze + off / 60, crop=crop).resize((W, H))
            sheet.paste(img, (i * W, 24))
            g.text((i * W + 6, 28), label, fill=(255, 255, 0))
        sheet.save(os.path.join(out_dir, f"{n:03d}_{p['play_id'][:8]}.jpg"), quality=88)
    print(f"{len(todo)} leak-check sheets → review/leak/")


def main(argv):
    if not argv:
        sys.exit(__doc__)
    cmd, args = argv[0], argv[1:]
    plays = load()

    if cmd == 'list':
        for p in unreviewed(plays):
            print(f"{p['play_id'][:8]}  {p['batter']:24s} {p['direction']:6s} "
                  f"contact {p['contact_time']:.3f}  strength {p.get('contact_strength')}")
    elif cmd == 'pages':
        per = int(args[0]) if args else 2
        todo = unreviewed(plays)
        out_dir = os.path.join(REVIEW, 'pages')
        os.makedirs(out_dir, exist_ok=True)
        for f in os.listdir(out_dir):
            os.remove(os.path.join(out_dir, f))
        for n in range(0, len(todo), per):
            sheets = [Image.open(os.path.join(REVIEW, f"{p['play_id']}.jpg")) for p in todo[n:n + per]]
            page = Image.new('RGB', (sheets[0].width, sum(s.height for s in sheets)))
            y = 0
            for s in sheets:
                page.paste(s, (0, y))
                y += s.height
            name = os.path.join(out_dir, f"page{n // per + 1:02d}.jpg")
            page.save(name, quality=85)
            print(name, ' '.join(p['play_id'][:8] for p in todo[n:n + per]))
    elif cmd == 'ok':
        for prefix in args:
            find(plays, prefix)['contact_verified'] = True
        save(plays)
    elif cmd == 'contact':
        p = find(plays, args[0])
        t = round(round(float(args[1]) * 60) / 60, 3)          # snap to the 60fps frame grid
        p['contact_raw'] = round(p['contact_raw'] + t - p['contact_time'], 3)
        p['contact_time'] = t
        p['contact_verified'] = True
        save(plays)
        print(f"{p['batter']}: contact {t:.3f}s — rerun process_clips.py --force --only {p['play_id']} "
              "to refresh its sheet")
    elif cmd == 'strips':
        strips(plays, args)
    elif cmd == 'leakcheck':
        leakcheck(plays, args)
    elif cmd == 'leak-ok':
        for prefix in args:
            find(plays, prefix)['leak_audit'] = 'passed'
        save(plays)
    elif cmd == 'frame-ok':
        for prefix in args:
            find(plays, prefix)['contact_frame_checked'] = True
        save(plays)
    elif cmd == 'shift':
        p = find(plays, args[0])
        k = int(args[1])
        p['contact_time'] = round(p['contact_time'] + k / 60, 3)
        p['contact_raw'] = round(p['contact_raw'] + k / 60, 3)
        p['contact_frame_checked'] = True
        save(plays)
        print(f"{p['batter']}: contact moved {k:+d} frames → {p['contact_time']:.3f}s")
    elif cmd == 'bad':
        p = find(plays, args[0])
        p['exclude'] = True
        p['exclude_reason'] = args[1] if len(args) > 1 else 'failed review'
        p.pop('contact_verified', None)
        save(plays)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
