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
