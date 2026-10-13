(() => {
  const $ = id => document.getElementById(id);

  const screens = {
    start:    $('start-screen'),
    game:     $('game-screen'),
    complete: $('complete-screen'),
  };

  function show(name) {
    Object.values(screens).forEach(s => s.classList.add('hidden'));
    screens[name].classList.remove('hidden');
  }

  const DIRS   = ['pull', 'center', 'oppo'];
  const LABELS = { pull: 'Pull', center: 'Center', oppo: 'Oppo' };

  // Statcast hit-coordinate space (same frame the spray angle is computed in)
  const HOME_X = 125.42, HOME_Y = 198.27;
  const CENTER_HALF_WIDTH = 15;   // must match scripts/fetch_plays.py

  // ── state ──────────────────────────────────────────────────────────────────
  let allPlays = [];
  let plays = [];
  let index = 0;
  let score = 0;
  let history = [];
  let pauseFired = false;
  let guessed = false;
  let replayUsed = false;

  const video = $('play-video');
  const preloader = document.createElement('video');
  preloader.preload = 'auto';
  preloader.muted = true;

  // ── load data ──────────────────────────────────────────────────────────────
  fetch('data.json')
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      allPlays = data.filter(p => p.clip_file && p.pause_time && !p.exclude);
      if (allPlays.length === 0) throw new Error('no clips');
      $('progress-text').textContent = `1 / ${allPlays.length}`;
      show('start');
    })
    .catch(() => {
      screens.start.querySelector('h1').textContent = 'Setup required';
      screens.start.querySelector('.subtitle').innerHTML =
        'Run the Python scripts first:<br><code>cd scripts && pip install -r requirements.txt</code><br>' +
        '<code>python fetch_plays.py</code><br><code>python download_clips.py</code><br><br>' +
        'Then serve with: <code>python -m http.server 8080</code>';
      $('start-btn').style.display = 'none';
      show('start');
    });

  // ── start ──────────────────────────────────────────────────────────────────
  function startGame() {
    plays = shuffle([...allPlays]);
    index = 0;
    score = 0;
    history = [];
    show('game');
    loadRound();
  }
  $('start-btn').addEventListener('click', startGame);
  $('replay-btn').addEventListener('click', startGame);

  // ── round ──────────────────────────────────────────────────────────────────
  function loadRound() {
    const play = plays[index];
    pauseFired = false;
    guessed = false;
    replayUsed = false;

    const total = plays.length;
    $('progress-fill').style.width = `${(index / total) * 100}%`;
    $('progress-text').textContent = `${index + 1} / ${total}`;
    $('score-display').textContent = `${score} / ${index}`;

    $('batter-name').textContent = play.batter;
    $('batter-hand').textContent = play.stand === 'L' ? 'LHB' : 'RHB';
    $('matchup').textContent = [play.pitcher && `vs ${play.pitcher}`, play.game_date]
      .filter(Boolean).join(' · ');

    $('guess-section').classList.remove('hidden');
    $('reveal-section').classList.add('hidden');
    $('freeze-tag').classList.add('hidden');
    buildGuessButtons(play.stand);
    $('watch-again-btn').disabled = false;

    $('tap-to-play').classList.add('hidden');
    video.playbackRate = 1;
    video.src = play.clip_file;
    video.load();
    video.play().catch(() => {
      $('tap-to-play').classList.remove('hidden');
    });

    // warm the cache for the next clip while this one plays
    const next = plays[index + 1];
    if (next) preloader.src = next.clip_file;
  }

  // Buttons are ordered left field → right field, so pull/oppo swap sides for lefties.
  function fieldOrder(stand) {
    return stand === 'L' ? ['oppo', 'center', 'pull'] : ['pull', 'center', 'oppo'];
  }

  function buildGuessButtons(stand) {
    const sideLabel = ['to left', 'up the middle', 'to right'];
    $('guess-buttons').innerHTML = fieldOrder(stand).map((d, i) => `
      <button class="guess-btn" data-dir="${d}">
        ${LABELS[d]}<span class="side">${sideLabel[i]}</span>
      </button>`).join('');
    $('guess-buttons').querySelectorAll('.guess-btn').forEach(btn =>
      btn.addEventListener('click', () => guess(btn.dataset.dir)));
  }

  $('tap-to-play').addEventListener('click', () => {
    $('tap-to-play').classList.add('hidden');
    video.play();
  });

  // ── precise pause monitor ──────────────────────────────────────────────────
  // requestVideoFrameCallback fires once per rendered frame and reports the
  // frame's exact media time, so the freeze lands within a frame of pause_time.
  // (These Savant clips seek unreliably, so we always freeze during playback
  // rather than seeking straight to pause_time.)
  let backstop = null;

  function freeze() {
    if (pauseFired || guessed) return;
    pauseFired = true;
    clearTimeout(backstop);
    video.pause();
    $('freeze-tag').classList.remove('hidden');
  }

  function startPauseMonitor() {
    const target = plays[index].pause_time;
    const useVFC = 'requestVideoFrameCallback' in video;

    const tick = (_now, meta) => {
      if (pauseFired || guessed) return;
      const t = meta ? meta.mediaTime : video.currentTime;
      if (t >= target) return freeze();
      useVFC ? video.requestVideoFrameCallback(tick) : requestAnimationFrame(() => tick());
    };
    useVFC ? video.requestVideoFrameCallback(tick) : requestAnimationFrame(() => tick());

    // Backstop: frame callbacks can stall (background tab, decoder hiccup), so
    // also poll the media clock on a short timer. Whichever fires first wins.
    clearTimeout(backstop);
    const poll = () => {
      if (pauseFired || guessed || video.paused) return;
      if (video.currentTime >= target) return freeze();
      backstop = setTimeout(poll, 10);
    };
    poll();
  }

  video.addEventListener('play', () => {
    if (!pauseFired && !guessed) startPauseMonitor();
  });

  video.addEventListener('ended', () => {
    if (!guessed) pauseFired = true;
  });

  // ── guess ──────────────────────────────────────────────────────────────────
  function guess(chosen) {
    if (guessed) return;
    guessed = true;
    const play = plays[index];
    const correct = play.direction;
    const isRight = chosen === correct;
    if (isRight) score++;
    history.push({ play, chosen, isRight });

    document.querySelectorAll('.guess-btn').forEach(b => {
      b.disabled = true;
      if (b.dataset.dir === correct) {
        b.classList.add(b.dataset.dir === chosen ? 'correct' : 'correct-answer');
      } else if (b.dataset.dir === chosen) {
        b.classList.add('wrong');
      }
    });

    $('result-line').textContent = isRight ? '✓ Correct' : `✗ It went ${LABELS[correct].toLowerCase()}`;
    $('result-line').className = isRight ? 'correct' : 'wrong';
    $('detail-line').textContent = [
      `${play.launch_speed} mph`,
      `${play.launch_angle}°`,
      play.spray_angle != null && `spray ${Math.abs(play.spray_angle).toFixed(0)}° ${play.spray_angle < 0 ? 'L' : 'R'}`,
      fmt(play.events),
    ].filter(Boolean).join(' · ');
    $('desc-line').textContent = [
      play.description,
      play.pitch_type && `${play.pitch_speed ? Math.round(play.pitch_speed) + ' mph ' : ''}${play.pitch_type.toLowerCase()}`,
    ].filter(Boolean).join(' — ');
    drawSpray($('spray'), play, chosen);

    $('score-display').textContent = `${score} / ${index + 1}`;
    $('freeze-tag').classList.add('hidden');
    $('guess-section').classList.add('hidden');
    $('reveal-section').classList.remove('hidden');

    // resume to show where the ball actually went
    video.playbackRate = 1;
    video.play().catch(() => {});
  }

  // ── watch again ────────────────────────────────────────────────────────────
  // Plays from 0 at half speed (seeking is unreliable on these clips, so we
  // never jump to pause_time directly).
  function watchAgain() {
    if (replayUsed || guessed) return;
    replayUsed = true;
    $('watch-again-btn').disabled = true;
    $('freeze-tag').classList.add('hidden');
    pauseFired = false;
    video.currentTime = 0;
    video.playbackRate = 0.5;
    video.play().catch(() => {});
  }
  $('watch-again-btn').addEventListener('click', watchAgain);

  // ── next ───────────────────────────────────────────────────────────────────
  function nextRound() {
    if (!guessed) return;
    index++;
    if (index >= plays.length) showComplete();
    else loadRound();
  }
  $('next-btn').addEventListener('click', nextRound);

  // ── keyboard ───────────────────────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (screens.game.classList.contains('hidden')) {
      if (e.key === 'Enter' && !screens.start.classList.contains('hidden')) startGame();
      return;
    }
    const order = fieldOrder(plays[index].stand);
    const slot = { ArrowLeft: 0, ArrowDown: 1, ArrowUp: 1, ArrowRight: 2 }[e.key];
    if (slot !== undefined && !guessed) { e.preventDefault(); guess(order[slot]); }
    else if ((e.key === 'r' || e.key === 'R') && !guessed) watchAgain();
    else if ((e.key === 'Enter' || e.key === ' ') && guessed) { e.preventDefault(); nextRound(); }
  });

  // ── spray chart ────────────────────────────────────────────────────────────
  function polar(angleDeg, r) {
    const a = angleDeg * Math.PI / 180;
    return [HOME_X + r * Math.sin(a), HOME_Y - r * Math.cos(a)];
  }

  // which side of the field (in spray angle) each direction covers
  function sector(dir, stand) {
    if (dir === 'center') return [-CENTER_HALF_WIDTH, CENTER_HALF_WIDTH];
    const left = (dir === 'pull') === (stand === 'R');
    return left ? [-45, -CENTER_HALF_WIDTH] : [CENTER_HALF_WIDTH, 45];
  }

  function wedge([a0, a1], r) {
    const [x0, y0] = polar(a0, r), [x1, y1] = polar(a1, r);
    return `M${HOME_X},${HOME_Y} L${x0},${y0} A${r},${r} 0 0 1 ${x1},${y1} Z`;
  }

  function drawSpray(svg, play, chosen) {
    const R = 165;
    const bases = [polar(45, 36), polar(0, 51), polar(-45, 36)];
    const [bx, by] = [play.hc_x, play.hc_y];
    const correctSector = sector(play.direction, play.stand);
    svg.innerHTML = `
      <path d="${wedge([-45, 45], R)}" class="field"/>
      ${chosen !== play.direction ? `<path d="${wedge(sector(chosen, play.stand), R)}" class="zone-wrong"/>` : ''}
      <path d="${wedge(correctSector, R)}" class="zone-right"/>
      <path d="M${HOME_X},${HOME_Y} L${bases[0]} L${bases[1]} L${bases[2]} Z" class="infield"/>
      ${[-CENTER_HALF_WIDTH, CENTER_HALF_WIDTH].map(a => {
        const [x, y] = polar(a, R);
        return `<line x1="${HOME_X}" y1="${HOME_Y}" x2="${x}" y2="${y}" class="divider"/>`;
      }).join('')}
      ${bx != null ? `
        <line x1="${HOME_X}" y1="${HOME_Y}" x2="${bx}" y2="${by}" class="flight"/>
        <circle cx="${bx}" cy="${by}" r="5" class="ball"/>` : ''}
      ${sectorLabels(play.stand)}
    `;
  }

  function sectorLabels(stand) {
    return DIRS.map(d => {
      const [a0, a1] = sector(d, stand);
      const [x, y] = polar((a0 + a1) / 2, 150);
      return `<text x="${x}" y="${y}" class="zone-label">${LABELS[d]}</text>`;
    }).join('');
  }

  // ── complete ───────────────────────────────────────────────────────────────
  function showComplete() {
    $('progress-fill').style.width = '100%';
    const total = plays.length;
    $('final-score-display').textContent = `${score} / ${total}`;

    // The fair comparison isn't 33%: a player who always guessed the most
    // common direction in this set would score this well without watching.
    const counts = DIRS.map(d => plays.filter(p => p.direction === d).length);
    const best = Math.max(...counts);
    const bestDir = DIRS[counts.indexOf(best)];
    const tied = counts.every(c => c === best);
    $('baseline-line').textContent =
      (tied ? `Guessing the same direction every time would score ${best} / ${total}. `
            : `Always guessing “${LABELS[bestDir]}” would score ${best} / ${total}. `) +
      (score > best ? 'You beat it.' : score === best ? 'You tied it.' : 'The swing fooled you.');

    $('emoji-line').textContent = history.map(h => h.isRight ? '🟩' : '🟥').join('');

    $('breakdown-table').innerHTML = DIRS.map(d => {
      const rows = history.filter(h => h.play.direction === d);
      const hits = rows.filter(h => h.isRight).length;
      return `<div class="breakdown-row">
        <span class="dir">${LABELS[d]}</span>
        <span class="hits">${rows.length ? `${hits}/${rows.length}` : '—'}</span>
      </div>`;
    }).join('');

    $('history-list').innerHTML = history.map(h => `
      <div class="history-row ${h.isRight ? 'ok' : 'miss'}">
        <span>${h.isRight ? '✓' : '✗'} ${h.play.batter}</span>
        <span class="muted">${h.isRight ? LABELS[h.chosen] : `${LABELS[h.chosen]} → ${LABELS[h.play.direction]}`}</span>
      </div>`).join('');

    show('complete');
  }

  // ── utils ──────────────────────────────────────────────────────────────────
  function shuffle(arr) {
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [arr[i], arr[j]] = [arr[j], arr[i]];
    }
    return arr;
  }

  function fmt(event) {
    return (event || 'unknown')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
  }
})();
