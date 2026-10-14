# Eephus Maximus

Baseball, slowly. Two projects:

- **Read the Swing** (`anticipation/`) — can people anticipate where a batted ball goes before it's hit?
- **The Long Haul** (`win-pace/`) — project the rest of a Red Sox season.

## Read the Swing: the experiment

Players watch a broadcast clip that freezes before bat-ball contact and call the ball
**pull**, **center** or **oppo**. The game is built so that beating 1 in 3 can only come from
reading the video:

| Design choice | Why |
|---|---|
| Every session has 6 pull, 6 center, 6 oppo | Any strategy that ignores the video averages exactly 1/3 |
| Clips freeze at one of three points: 24, 12 or 6 frames (0.4s, 0.2s, 0.1s at 60fps) before contact | **Release** is the control: the swing hasn't started. A rise toward **mid-swing** means the swing is being read |
| Freeze point balanced within each direction | Direction and freeze point are never confounded |
| Freeze lands on the last frame at or before the target | A late frame could show contact: trials more than half a frame late, or more than 3 frames early, are dropped from analysis |
| Sound off until the answer is in, one viewing, buttons locked until the freeze | Everyone gets the same information |
| Only hits 90–100 mph, 10–30°, at least 3° from a direction boundary | Clear-cut answers, comparable batted balls |
| 180 clips (60 per direction) from 142 batters, max 2 each, across the 2024 season | No single swing or park dominates; a player gets 10 rounds before any repeat |
| Every clip's contact time checked by eye; mid-swing freeze 6 frames before contact | Audio detection misfires on ~10% of clips, and broadcast audio can lag the picture by a frame or two |
| Clips a player has already seen are shown last and analyzed separately | Memory isn't anticipation |

### What counts as proof

Beating 1 in 3 isn't enough on its own. `scripts/baselines.py` scores strategies that never watch
the clip: knowing each hitter's 2024 spray tendencies and the pitch location gets about **48%** on
these clips, because inside pitches get pulled and hitters have habits. So the hypotheses, fixed
before collecting data along with the sample size (60 sessions), are:

1. **H1:** accuracy is above 1/3.
2. **H2:** accuracy is higher mid-swing than at release, i.e. information arriving during the pitch is
   being read. Pitch location is visible by mid-flight, so this covers pitch and swing.
3. **H3:** mid-swing accuracy beats the best no-video strategy. Sharpest form: on clips where that
   strategy points the wrong way, mid-swing accuracy still rises above release.

The primary tests are mixed models with crossed random effects for players and clips, so a "yes"
has to hold across people *and* generalize to other batted balls; one prolific player or a few
easy clips can't carry it. Simulated studies check the tests themselves:

| Simulated truth (release / flight / swing), 60 sessions, 180 clips varying in difficulty | H1 significant | H2 significant |
|---|---|---|
| Pure chance (false-positive rate; should be ≤5%) | ≈1% | ≈6% |
| Modest skill: 35% / 38% / 45% (power) | ≈89% | ≈83% |

Reproduce with `python3 scripts/analyze.py --simulate 0.35,0.38,0.45 --clip-sd 0.8`. (Simpler
alternatives were tried and rejected: a players-only test is too optimistic when clips vary, and
the crossed bootstrap and min F′ almost never fire at chance, which wastes power.)

Each trial is logged (player, clip, freeze point, guess, reaction time, the exact frame shown,
self-reported playing experience) to `data/trials.jsonl`.

`scripts/analyze.py` reports the three hypotheses, accuracy by freeze point and by experience,
learning within a session, the confusion matrix, and which individual pitches are readable
(Benjamini–Hochberg corrected).
The same headline numbers are on `anticipation/results.html`.

## Running it

```bash
python3 scripts/server.py
```

- Game: http://localhost:8080/anticipation/
- Results: http://localhost:8080/anticipation/results.html
- Clip review: http://localhost:8080/anticipation/editor.html

The server records trials and supports HTTP Range requests, which the videos need in order to seek.

## Adding clips

Requires `pip install pybaseball pandas yt-dlp imageio-ffmpeg numpy pillow scipy statsmodels`.

```bash
python3 scripts/fetch_plays.py --per-dir 30   # top up to N per direction; excluded plays are never re-fetched
python3 scripts/download_clips.py             # Savant video → raw_clips/ (gitignored)
python3 scripts/process_clips.py              # find contact from audio, trim, re-encode → anticipation/clips/
python3 scripts/review.py pages               # review sheets → review/pages/
python3 scripts/review.py ok|contact|bad ...  # or use the clip review page
python3 scripts/baselines.py                  # rescore the no-video strategies on the current clips
```

A clip enters the game only once it's marked verified. Video files are gitignored
(`anticipation/clips/`, `raw_clips/`); `data.json` records everything needed to rebuild them.
