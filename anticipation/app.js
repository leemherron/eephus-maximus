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

  // ── state ──────────────────────────────────────────────────────────────────
  let plays = [];
  let index = 0;
  let score = 0;
  let breakdown = { pull: [0,0], center: [0,0], oppo: [0,0] };
  let pauseFired = false;
  let guessed = false;

  const video = $('play-video');

  // ── load data ──────────────────────────────────────────────────────────────
  fetch('data.json')
    .then(r => r.ok ? r.json() : Promise.reject())
    .then(data => {
      plays = data.filter(p => p.clip_file && p.pause_time);
      if (plays.length === 0) throw new Error('no clips');
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
  $('start-btn').addEventListener('click', () => {
    plays = shuffle([...plays]);
    index = 0;
    score = 0;
    breakdown = { pull: [0,0], center: [0,0], oppo: [0,0] };
    show('game');
    loadRound();
  });

  $('replay-btn').addEventListener('click', () => {
    plays = shuffle([...plays]);
    index = 0;
    score = 0;
    breakdown = { pull: [0,0], center: [0,0], oppo: [0,0] };
    show('game');
    loadRound();
  });

  // ── round ──────────────────────────────────────────────────────────────────
  function loadRound() {
    const play = plays[index];
    pauseFired = false;
    guessed = false;

    // header
    const total = plays.length;
    $('progress-fill').style.width = `${(index / total) * 100}%`;
    $('progress-text').textContent = `${index + 1} / ${total}`;
    $('score-display').textContent = `${score} / ${index}`;

    // batter info
    $('batter-name').textContent = play.batter;
    $('game-date').textContent = play.game_date;

    // reset action area
    $('guess-section').classList.remove('hidden');
    $('reveal-section').classList.add('hidden');
    document.querySelectorAll('.guess-btn').forEach(b => {
      b.disabled = false;
      b.className = 'guess-btn';
    });

    // video
    $('tap-to-play').classList.add('hidden');
    video.src = play.clip_file;
    video.load();
    video.play().catch(() => {
      $('tap-to-play').classList.remove('hidden');
    });
  }

  // tap-to-play for mobile autoplay restrictions
  $('tap-to-play').addEventListener('click', () => {
    $('tap-to-play').classList.add('hidden');
    video.play();
  });

  // pause at contact point
  video.addEventListener('timeupdate', () => {
    const play = plays[index];
    if (!pauseFired && !guessed && video.currentTime >= play.pause_time) {
      pauseFired = true;
      video.pause();
    }
  });

  // if clip ends before pause_time fires (very short clip), still show buttons
  video.addEventListener('ended', () => {
    if (!guessed) showGuessButtons();
  });

  function showGuessButtons() {
    // already visible from loadRound, nothing extra needed
  }

  // ── guess ──────────────────────────────────────────────────────────────────
  document.querySelectorAll('.guess-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      if (guessed) return;
      guessed = true;
      const chosen = btn.dataset.dir;
      const play = plays[index];
      const correct = play.direction;
      const isRight = chosen === correct;

      // disable all buttons, style them
      document.querySelectorAll('.guess-btn').forEach(b => {
        b.disabled = true;
        if (b.dataset.dir === correct) {
          b.classList.add(b === btn ? 'correct' : 'correct-answer');
        } else if (b === btn) {
          b.classList.add('wrong');
        }
      });

      if (isRight) score++;
      breakdown[correct][1]++;
      if (isRight) breakdown[correct][0]++;

      // reveal
      $('result-line').textContent = isRight ? '✓ Correct' : `✗ Wrong — it was ${correct}`;
      $('result-line').className = isRight ? 'correct' : 'wrong';
      $('detail-line').textContent =
        `${play.launch_speed} mph · ${play.launch_angle}° · ${fmt(play.events)}`;

      $('guess-section').classList.add('hidden');
      $('reveal-section').classList.remove('hidden');

      // resume video to show where the ball went
      video.play().catch(() => {});
    });
  });

  // ── next ───────────────────────────────────────────────────────────────────
  $('next-btn').addEventListener('click', () => {
    index++;
    if (index >= plays.length) {
      showComplete();
    } else {
      loadRound();
    }
  });

  // ── complete ───────────────────────────────────────────────────────────────
  function showComplete() {
    $('progress-fill').style.width = '100%';
    const total = plays.length;
    const pct = Math.round((score / total) * 100);
    $('final-score-display').textContent = `${score} / ${total}`;

    const dirs = ['pull', 'center', 'oppo'];
    const labels = { pull: 'Pull', center: 'Center', oppo: 'Oppo' };
    $('breakdown-table').innerHTML = dirs.map(d => {
      const [hits, attempts] = breakdown[d];
      return `<div class="breakdown-row">
        <span class="dir">${labels[d]}</span>
        <span class="hits">${attempts ? `${hits}/${attempts}` : '—'}</span>
      </div>`;
    }).join('');

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
