# Eephus Maximus

Baseball, slowly. Two projects:

- **Read the Swing** (`anticipation/`) — can people anticipate where a batted ball goes before it's hit?
- **The Long Haul** (`win-pace/`) — project the rest of a Red Sox season.

## Read the Swing: the experiment

Players watch a broadcast clip that freezes **2 frames (1/30 s) before the bat meets the ball** and
call the ball **pull**, **center** or **oppo**. The game is built so that beating 1 in 3 can only
come from what's visible in the video:

| Design choice | Why |
|---|---|
| Every session has 6 pull, 6 center, 6 oppo | Any strategy that ignores the video averages exactly 1/3 |
| Every clip's contact frame was set frame by frame (`review.py strips`) | At 2 frames, a contact time off by 2 frames would show the ball being hit. The audio-based times weren't good enough: half the clips needed contact moved earlier, one in five by 3+ frames |
| Then every exact freeze frame passed a blind audit (`review.py leakcheck`): reviewers, told nothing about contact times, judged whether the ball had been hit | The direct test of what players see. Clips fail if the ball can't be found while the bat is at the hitting point (no-contact unverifiable) or no swing has started (freeze far too early) |
| A 3-clip warm-up for first-time players, not logged, with reserved clips | Pull/oppo swap field sides for lefties; early mistakes from learning the controls aren't anticipation failures |
| Freeze lands on the last frame at or before the target | A late frame could show contact: trials more than half a frame late, or more than 3 frames early, are dropped from analysis |
| Sound off until the answer is in, one viewing, buttons locked until the freeze | Everyone gets the same information |
| Only hits 90–100 mph, 10–30°, at least 3° from a direction boundary | Clear-cut answers, comparable batted balls |
| 138 scored clips (46 pull / 42 center / 50 oppo) from 117 batters, max 2 each, across the 2024 season | No single swing or park dominates; sessions draw 6 per direction, so chance stays exactly 1/3 |
| Clips a player has already seen are shown last and analyzed separately | Memory isn't anticipation |
| Only complete 18-clip rounds count; answers under 0.25 s are dropped | Chance is exactly 1/3 only over a full balanced round; instant taps aren't a read |

### What counts as proof

Beating 1 in 3 isn't enough on its own. `scripts/baselines.py` scores a "scouting report" that never
watches the clip: knowing each hitter's 2024 spray tendencies and the pitch location gets about
**46%** on these clips, because inside pitches get pulled and hitters have habits. The hypotheses,
fixed before collecting data along with the sample size (60 sessions):

1. **H1 (primary):** accuracy is above 1/3.
2. **H3 (primary):** on clips where the scouting report points the wrong way, accuracy is still above
   1/3. Someone going on hitter and location priors alone scores *below* 1/3 there, so this is the
   clearest evidence of reading the swing itself.
3. **H2 (descriptive):** people vs the scouting report trial by trial. Too noisy to be a primary test.

The primary tests are mixed models with crossed random effects for players and clips, so a "yes"
has to hold across people *and* generalize to other batted balls; one prolific player or a few
easy clips can't carry it. Simulated 60-session studies (clips varying in difficulty) check the
tests themselves:

| Simulated players | H1 | H3 |
|---|---|---|
| Guessing (false-positive rate; should be ≤5%) | ≈3% | ≈3% |
| Know hitter + location priors perfectly, read nothing from the video | 100% | 0% |
| Read swings moderately (55% where the report is right, 42% where it's wrong) | 100% | ≈85% |

The middle row is why H1 alone proves little and H3 is the key test. Reproduce with
`python3 scripts/analyze.py --simulate 0.55,0.42 --clip-sd 0.8`.

Each trial is logged (player, clip, guess, reaction time, the exact frame shown, self-reported
playing experience) to `data/trials.jsonl`.

`scripts/analyze.py` reports the hypotheses, accuracy by experience,
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
python3 scripts/review.py strips              # frame-by-frame strips → find each clip's exact contact frame
python3 scripts/review.py frame-ok|shift ...  # record it
python3 scripts/review.py leakcheck           # exact freeze frames → review/leak/ for a blind audit
python3 scripts/review.py leak-ok ...         # mark passed (the game only uses audited clips)
python3 scripts/baselines.py                  # rescore the no-video strategies on the current clips
```

A clip enters the game only once it's marked verified. Video files are gitignored
(`anticipation/clips/`, `raw_clips/`); `data.json` records everything needed to rebuild them.
