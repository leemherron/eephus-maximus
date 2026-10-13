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

  // Freeze points, in seconds before bat-ball contact. "release" is the control:
  // the pitch has barely left the hand, so it shows what a viewer can call from
  // the batter, count, fielders and pitcher alone. Any gain at "flight" and
  // "swing" comes from reading the pitch and the swing.
  // Keep in sync with LEADS in scripts/process_clips.py.
  // Whole frames at 60fps (24, 12, 4), so the freeze lands exactly on a frame.
  const LEADS = { release: 24 / 60, flight: 12 / 60, swing: 4 / 60 };
  const LEAD_LABELS = { release: 'at release', flight: 'mid-flight', swing: 'mid-swing' };
  const PER_DIRECTION = 6;                 // 18 trials per session
  const FRAME = 1 / 60;                    // processed clips are constant 60fps

  // Statcast hit-coordinate space (same frame the spray angle is computed in)
  const HOME_X = 125.42, HOME_Y = 198.27;
  const CENTER_HALF_WIDTH = 15;            // must match scripts/fetch_plays.py

  // ── identity + storage (all optional: the game works without it) ──────────
  const store = {
    get(k, fallback) { try { return JSON.parse(localStorage.getItem(k)) ?? fallback; } catch { return fallback; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };
  const playerId = store.get('rts.player', null) || (() => {
    const id = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
    store.set('rts.player', id);
    return id;
  })();

  // ── state ──────────────────────────────────────────────────────────────────
  let allPlays = [];
  let trials = [];       // [{play, lead}]
  let index = 0;
  let score = 0;
  let history = [];
  let sessionId = null;
  let frozen = false;
  let guessed = false;
  let frozenAt = null;
  let freezeClock = 0;

  const video = $('play-video');
  const preloader = document.createElement('video');
  preloader.preload = 'auto';
  preloader.muted = true;

  // ── load data ──────────────────────────────────────────────────────────────
  fetch('data.json')
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      // Only clips whose contact time was confirmed by eye — a wrong contact
      // time could freeze after the ball is hit and leak the answer.
      allPlays = data.filter(p => p.clip_file && p.contact_verified && p.contact_time != null && !p.exclude);
      if (allPlays.length === 0) throw new Error('no clips');
      if (!store.get('rts.exp', null)) $('intake').classList.remove('hidden');
      show('start');
    })
    .catch(() => {
      screens.start.querySelector('h1').textContent = 'Setup required';
      screens.start.querySelector('.subtitle').innerHTML =
        'Build the clips first — see <code>scripts/</code>:<br>' +
        '<code>fetch_plays.py</code> → <code>download_clips.py</code> → <code>process_clips.py</code>';
      $('start-btn').style.display = 'none';
      show('start');
    });

  // ── session ────────────────────────────────────────────────────────────────
  // Equal clips per direction, and within each direction an equal split of
  // freeze points, so direction and freeze point are never confounded.
  // Clips this player has already seen are used last.
  function buildSession() {
    const seen = new Set(store.get('rts.seen', []));
    const byDir = Object.fromEntries(DIRS.map(d => [d,
      shuffle(allPlays.filter(p => p.direction === d))
        .sort((a, b) => seen.has(a.play_id) - seen.has(b.play_id))]));
    const n = Math.min(PER_DIRECTION, ...DIRS.map(d => byDir[d].length));
    const leadNames = Object.keys(LEADS);
    const out = [];
    for (const d of DIRS) {
      const leads = shuffle(Array.from({ length: n }, (_, i) => leadNames[i % leadNames.length]));
      byDir[d].slice(0, n).forEach((play, i) =>
        out.push({ play, lead: leads[i], repeat: seen.has(play.play_id) }));
    }
    return shuffle(out);
  }

  function startGame() {
    const exp = document.querySelector('input[name="exp"]:checked');
    if (exp) store.set('rts.exp', exp.value);
    if (!store.get('rts.exp', null)) {
      $('intake').classList.add('needs-answer');
      return;
    }
    $('intake').classList.add('hidden');
    trials = buildSession();
    sessionId = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
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
    const { play } = trials[index];
    frozen = false;
    guessed = false;
    frozenAt = null;

    const total = trials.length;
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
    $('prompt').textContent = 'Watch…';
    buildGuessButtons(play.stand);
    setButtonsEnabled(false);

    $('tap-to-play').classList.add('hidden');
    video.muted = true;               // no audio until the answer is in
    video.src = play.clip_file;
    video.load();
    video.play().catch(() => $('tap-to-play').classList.remove('hidden'));

    const next = trials[index + 1];
    if (next) preloader.src = next.play.clip_file;
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

  function setButtonsEnabled(on) {
    document.querySelectorAll('.guess-btn').forEach(b => { b.disabled = !on; });
  }

  $('tap-to-play').addEventListener('click', () => {
    $('tap-to-play').classList.add('hidden');
    video.play();
  });

  // ── freeze ─────────────────────────────────────────────────────────────────
  // Stop on the last frame at or before the target, never after it: pause when
  // the *next* frame would cross the target. requestVideoFrameCallback reports
  // each presented frame's exact media time; a short timer backs it up when
  // frame callbacks stall (background tab, decoder hiccup).
  let backstop = null;

  function freeze() {
    if (frozen || guessed) return;
    frozen = true;
    clearTimeout(backstop);
    video.pause();
    frozenAt = video.currentTime;
    freezeClock = performance.now();
    $('freeze-tag').textContent = `Frozen ${LEAD_LABELS[trials[index].lead]}`;
    $('freeze-tag').classList.remove('hidden');
    $('prompt').textContent = 'Where will it go?';
    setButtonsEnabled(true);
  }

  function startFreezeMonitor() {
    const { play, lead } = trials[index];
    const target = play.contact_time - LEADS[lead];
    const useVFC = 'requestVideoFrameCallback' in video;

    const tick = (_now, meta) => {
      if (frozen || guessed) return;
      const t = meta ? meta.mediaTime : video.currentTime;
      if (t + FRAME > target + 0.002) return freeze();
      useVFC ? video.requestVideoFrameCallback(tick) : requestAnimationFrame(() => tick());
    };
    useVFC ? video.requestVideoFrameCallback(tick) : requestAnimationFrame(() => tick());

    clearTimeout(backstop);
    const poll = () => {
      if (frozen || guessed || video.paused) return;
      if (video.currentTime + FRAME > target + 0.002) return freeze();
      backstop = setTimeout(poll, 5);
    };
    poll();
  }

  video.addEventListener('play', () => {
    if (!frozen && !guessed) startFreezeMonitor();
  });

  // ── guess ──────────────────────────────────────────────────────────────────
  function guess(chosen) {
    if (guessed || !frozen) return;
    guessed = true;
    const { play, lead, repeat } = trials[index];
    const correct = play.direction;
    const isRight = chosen === correct;
    if (isRight) score++;
    history.push({ play, lead, chosen, isRight });
    logTrial({
      play_id: play.play_id, lead, lead_s: +LEADS[lead].toFixed(4), guess: chosen, direction: correct,
      correct: isRight, rt_ms: Math.round(performance.now() - freezeClock),
      frozen_at: +frozenAt.toFixed(3), contact_time: play.contact_time, repeat,
    });
    const seen = new Set(store.get('rts.seen', []));
    seen.add(play.play_id);
    store.set('rts.seen', [...seen]);

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

    // now show (and let them hear) what happened
    video.muted = false;
    video.play().catch(() => {});
  }

  // ── logging ────────────────────────────────────────────────────────────────
  // Trials go to the local server (scripts/server.py). Anything that fails to
  // send is queued in localStorage and retried on the next trial.
  function logTrial(t) {
    const queue = store.get('rts.queue', []);
    queue.push({
      ...t, player_id: playerId, session_id: sessionId, trial: index,
      experience: store.get('rts.exp', null), ts: new Date().toISOString(),
    });
    store.set('rts.queue', queue);
    flushQueue();
  }

  function flushQueue() {
    const queue = store.get('rts.queue', []);
    if (!queue.length) return;
    fetch('/api/trials', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ trials: queue }),
    }).then(r => {
      if (!r.ok) return;
      const sent = new Set(queue.map(q => q.session_id + ':' + q.trial));
      store.set('rts.queue', store.get('rts.queue', []).filter(q => !sent.has(q.session_id + ':' + q.trial)));
    }).catch(() => {});
  }
  flushQueue();

  // ── next ───────────────────────────────────────────────────────────────────
  function nextRound() {
    if (!guessed) return;
    index++;
    if (index >= trials.length) showComplete();
    else loadRound();
  }
  $('next-btn').addEventListener('click', nextRound);

  // ── keyboard ───────────────────────────────────────────────────────────────
  document.addEventListener('keydown', e => {
    if (screens.game.classList.contains('hidden')) {
      if (e.key === 'Enter' && !screens.start.classList.contains('hidden')) startGame();
      return;
    }
    const order = fieldOrder(trials[index].play.stand);
    const slot = { ArrowLeft: 0, ArrowDown: 1, ArrowUp: 1, ArrowRight: 2 }[e.key];
    if (slot !== undefined && frozen && !guessed) { e.preventDefault(); guess(order[slot]); }
    else if ((e.key === 'Enter' || e.key === ' ') && guessed) { e.preventDefault(); nextRound(); }
  });

  // ── spray chart ────────────────────────────────────────────────────────────
  function polar(angleDeg, r) {
    const a = angleDeg * Math.PI / 180;
    return [HOME_X + r * Math.sin(a), HOME_Y - r * Math.cos(a)];
  }

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
    svg.innerHTML = `
      <path d="${wedge([-45, 45], R)}" class="field"/>
      ${chosen !== play.direction ? `<path d="${wedge(sector(chosen, play.stand), R)}" class="zone-wrong"/>` : ''}
      <path d="${wedge(sector(play.direction, play.stand), R)}" class="zone-right"/>
      <path d="M${HOME_X},${HOME_Y} L${bases[0]} L${bases[1]} L${bases[2]} Z" class="infield"/>
      ${[-CENTER_HALF_WIDTH, CENTER_HALF_WIDTH].map(a => {
        const [x, y] = polar(a, R);
        return `<line x1="${HOME_X}" y1="${HOME_Y}" x2="${x}" y2="${y}" class="divider"/>`;
      }).join('')}
      ${bx != null ? `
        <line x1="${HOME_X}" y1="${HOME_Y}" x2="${bx}" y2="${by}" class="flight"/>
        <circle cx="${bx}" cy="${by}" r="5" class="ball"/>` : ''}
      ${DIRS.map(d => {
        const [a0, a1] = sector(d, play.stand);
        const [x, y] = polar((a0 + a1) / 2, 150);
        return `<text x="${x}" y="${y}" class="zone-label">${LABELS[d]}</text>`;
      }).join('')}
    `;
  }

  // ── complete ───────────────────────────────────────────────────────────────
  function showComplete() {
    $('progress-fill').style.width = '100%';
    const total = trials.length;
    $('final-score-display').textContent = `${score} / ${total}`;

    const p = Stats.binomTail(score, total);
    const expected = Math.round(total * Stats.CHANCE);
    $('verdict-line').textContent =
      `Blind guessing averages ${expected} / ${total}. ` +
      (p < 0.05 ? `You beat chance (${Stats.fmtP(p)}): you were reading something.`
                : `Over ${total} clips that's within the range of luck (${Stats.fmtP(p)}).`);

    $('emoji-line').textContent = history.map(h => h.isRight ? '🟩' : '🟥').join('');

    // Accuracy by freeze point is the point of the experiment
    $('breakdown-table').innerHTML = Object.keys(LEADS).map(l => {
      const rows = history.filter(h => h.lead === l);
      const hits = rows.filter(h => h.isRight).length;
      return `<div class="breakdown-row">
        <span class="dir">Frozen ${LEAD_LABELS[l]}</span>
        <span class="hits">${rows.length ? `${hits}/${rows.length}` : '—'}</span>
      </div>`;
    }).join('');

    $('history-list').innerHTML = history.map(h => `
      <div class="history-row ${h.isRight ? 'ok' : 'miss'}">
        <span>${h.isRight ? '✓' : '✗'} ${h.play.batter}</span>
        <span class="muted">${h.isRight ? LABELS[h.chosen] : `${LABELS[h.chosen]} → ${LABELS[h.play.direction]}`}
          · ${LEAD_LABELS[h.lead]}</span>
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
