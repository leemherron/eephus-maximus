const TOTAL_GAMES    = 162;
const GAMES_PLAYED   = 72;
const WINS_TO_DATE   = 29;
const REMAINING      = TOTAL_GAMES - GAMES_PLAYED;          // 90
const CURRENT_RATE   = WINS_TO_DATE / GAMES_PLAYED;         // .403
const PLAYOFF_TARGET = 90;
const WINS_NEEDED    = PLAYOFF_TARGET - WINS_TO_DATE;       // 61

// Cumulative wins after each game (index 0 = pre-season, index 72 = after game 72)
const ACTUAL_WINS = [
  0,
  1,1,1,1,1,1,            // games 1–6   (1W 5L)
  2,2,2,2,                // games 7–10  (W LLL)
  3,4,4,                  // games 11–13 (WW L)
  5,6,                    // games 14–15 (WW)
  6,6,                    // games 16–17 (LL)
  7,8,                    // games 18–19 (WW)
  8,8,                    // games 20–21 (LL)
  9,9,9,9,9,              // games 22–26 (W LLLL)
  10,11,12,               // games 27–29 (WWW)
  12,12,                  // games 30–31 (LL)
  13,13,13,               // games 32–34 (W LL)
  14,15,16,               // games 35–37 (WWW)
  16,                     // game  38    (L)
  17,17,17,               // games 39–41 (W LL)
  18,18,18,               // games 42–44 (W LL)
  19,19,                  // games 45–46 (W L)
  20,21,22,               // games 47–49 (WWW)
  22,22,22,22,            // games 50–53 (LLLL)
  23,23,23,               // games 54–56 (W LL)
  24,25,                  // games 57–58 (WW)
  25,                     // game  59    (L)
  26,26,                  // games 60–61 (W L)
  27,27,27,27,27,         // games 62–66 (W LLLL)
  28,29,                  // games 67–68 (WW)
  29,29,29,29             // games 69–72 (LLLL)
];

// Sanity check
if (ACTUAL_WINS.length !== GAMES_PLAYED + 1 || ACTUAL_WINS[GAMES_PLAYED] !== WINS_TO_DATE) {
  console.error('Data mismatch', ACTUAL_WINS.length, ACTUAL_WINS[GAMES_PLAYED]);
}

// ── color tokens ─────────────────────────────────────────────────────────────
const C_CREAM  = '#f5f0e8';
const C_ACCENT = '#c8a84b';
const C_MUTED  = '#8a9e85';
const C_RED    = '#e53935';
const C_GREEN  = '#2d5a27';

// ── chart datasets ────────────────────────────────────────────────────────────
function actualDataset() {
  return {
    label: 'Actual',
    data: ACTUAL_WINS.map((w, i) => ({ x: i, y: w })),
    borderColor: C_CREAM,
    borderWidth: 2,
    pointRadius: 0,
    tension: 0.15,
    parsing: false,
    order: 1,
  };
}

function projectionDataset(projWins) {
  return {
    label: 'Your projection',
    data: [
      { x: GAMES_PLAYED, y: WINS_TO_DATE },
      { x: TOTAL_GAMES,  y: WINS_TO_DATE + projWins },
    ],
    borderColor: C_ACCENT,
    borderWidth: 2.5,
    borderDash: [7, 4],
    pointRadius: [4, 4],
    pointBackgroundColor: C_ACCENT,
    tension: 0,
    parsing: false,
    order: 0,
  };
}

function paceDataset() {
  const pacedWins = Math.round(REMAINING * CURRENT_RATE);
  return {
    label: 'Current pace',
    data: [
      { x: GAMES_PLAYED, y: WINS_TO_DATE },
      { x: TOTAL_GAMES,  y: WINS_TO_DATE + pacedWins },
    ],
    borderColor: C_MUTED,
    borderWidth: 1.5,
    borderDash: [3, 5],
    pointRadius: 0,
    tension: 0,
    parsing: false,
    order: 2,
  };
}

// ── chart init ────────────────────────────────────────────────────────────────
let chart;

function buildAnnotations() {
  return {
    line90: {
      type: 'line', yMin: 90, yMax: 90,
      borderColor: 'rgba(229,57,53,0.45)',
      borderWidth: 1, borderDash: [5, 4],
      label: {
        display: true, content: '90 wins',
        position: 'end', color: C_RED,
        font: { family: 'Georgia', size: 10 },
        backgroundColor: 'transparent', yAdjust: -10,
      },
    },
    line81: {
      type: 'line', yMin: 81, yMax: 81,
      borderColor: 'rgba(138,158,133,0.25)',
      borderWidth: 1, borderDash: [5, 4],
      label: {
        display: true, content: '.500',
        position: 'end', color: C_MUTED,
        font: { family: 'Georgia', size: 10 },
        backgroundColor: 'transparent', yAdjust: -10,
      },
    },
    today: {
      type: 'line', xMin: GAMES_PLAYED, xMax: GAMES_PLAYED,
      borderColor: 'rgba(138,158,133,0.2)',
      borderWidth: 1,
      label: {
        display: true, content: 'today',
        position: 'start', color: C_MUTED,
        font: { family: 'Georgia', size: 10 },
        backgroundColor: 'transparent', xAdjust: 6, yAdjust: 8,
      },
    },
  };
}

function initChart(projWins) {
  const ctx = document.getElementById('chart').getContext('2d');

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      datasets: [actualDataset(), projectionDataset(projWins), paceDataset()],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      animation: { duration: 150 },
      scales: {
        x: {
          type: 'linear',
          min: 0,
          max: TOTAL_GAMES,
          title: {
            display: true, text: 'Game',
            color: C_MUTED, font: { family: 'Georgia', size: 11 },
          },
          ticks: {
            color: C_MUTED, font: { family: 'Georgia', size: 10 },
            stepSize: 27, maxRotation: 0,
          },
          grid: { color: 'rgba(45,90,39,0.18)' },
          border: { color: C_GREEN },
        },
        y: {
          min: 0,
          max: 105,
          title: {
            display: true, text: 'Wins',
            color: C_MUTED, font: { family: 'Georgia', size: 11 },
          },
          ticks: {
            color: C_MUTED, font: { family: 'Georgia', size: 10 },
            stepSize: 20,
          },
          grid: { color: 'rgba(45,90,39,0.18)' },
          border: { color: C_GREEN },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: C_MUTED,
            font: { family: 'Georgia', size: 11 },
            boxWidth: 22,
            padding: 16,
          },
        },
        tooltip: {
          callbacks: {
            title: (items) => `Game ${items[0].parsed.x}`,
            label: (item) => `${item.dataset.label}: ${item.parsed.y} wins`,
          },
          backgroundColor: '#162116',
          borderColor: C_GREEN,
          borderWidth: 1,
          titleColor: C_MUTED,
          bodyColor: C_CREAM,
          titleFont: { family: 'Georgia' },
          bodyFont: { family: 'Georgia' },
        },
        annotation: { annotations: buildAnnotations() },
      },
    },
  });
}

// ── stat updates ──────────────────────────────────────────────────────────────
function updateStats(projWins) {
  const totalWins   = WINS_TO_DATE + projWins;
  const totalLosses = TOTAL_GAMES - totalWins;
  const finalWpct   = totalWins / TOTAL_GAMES;
  const vs500       = totalWins - 81;
  const vs90        = projWins - WINS_NEEDED;    // how far from 61 remaining wins needed

  document.getElementById('stat-final').textContent = `${totalWins}–${totalLosses}`;
  document.getElementById('stat-wpct').textContent  = finalWpct.toFixed(3).replace('0.', '.');

  const vs500El = document.getElementById('stat-vs500');
  vs500El.textContent = vs500 >= 0 ? `+${vs500}` : `−${Math.abs(vs500)}`;
  vs500El.className   = 'stat-value ' + (vs500 >= 0 ? 'pos' : 'neg');

  const vs90El = document.getElementById('stat-vs90');
  vs90El.textContent = vs90 >= 0 ? `+${vs90}` : `−${Math.abs(vs90)}`;
  vs90El.className   = 'stat-value ' + (vs90 >= 0 ? 'pos' : 'neg');

  const note = document.getElementById('footnote');
  if (totalWins >= 90) {
    const pct = (projWins / REMAINING * 100).toFixed(0);
    note.textContent = `Going ${projWins}–${REMAINING - projWins} (${pct}%) the rest of the way gets them to ${totalWins} wins — legitimate playoff territory.`;
  } else if (totalWins >= 85) {
    note.textContent = `${totalWins} wins puts them on the fringe. They'd need some help, and a hot September.`;
  } else if (totalWins >= 81) {
    note.textContent = `A .500 finish — respectable recovery, but the math probably doesn't work for October.`;
  } else {
    note.textContent = `${totalWins} wins. A long look in the mirror, a lot of "building for the future," and an early flight home.`;
  }
}

// ── projection update ─────────────────────────────────────────────────────────
function updateProjection(projWins) {
  const projLosses = REMAINING - projWins;
  const projWpct   = projWins / REMAINING;

  document.getElementById('proj-wl').textContent  = `${projWins}–${projLosses}`;
  document.getElementById('proj-wpct').textContent = projWpct.toFixed(3).replace('0.', '.');

  // Update y-axis ceiling so the projection line always fits
  const totalWins = WINS_TO_DATE + projWins;
  chart.options.scales.y.max = Math.max(105, totalWins + 8);

  chart.data.datasets[1] = projectionDataset(projWins);
  chart.update();

  updateStats(projWins);
}

// ── boot ──────────────────────────────────────────────────────────────────────
const slider = document.getElementById('proj-slider');
const DEFAULT = 45;

initChart(DEFAULT);
updateProjection(DEFAULT);

slider.addEventListener('input', () => updateProjection(parseInt(slider.value, 10)));
