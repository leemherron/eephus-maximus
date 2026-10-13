// Small stats helpers shared by the game and the results page.
// Chance is exactly 1/3: every session is balanced across pull/center/oppo,
// so any guessing strategy that ignores the video averages one in three.
const Stats = (() => {
  const CHANCE = 1 / 3;

  function logChoose(n, k) {
    let s = 0;
    for (let i = 1; i <= k; i++) s += Math.log(n - k + i) - Math.log(i);
    return s;
  }

  // One-sided exact binomial test: P(X >= k) when each trial succeeds with p.
  function binomTail(k, n, p = CHANCE) {
    if (n === 0) return 1;
    let total = 0;
    for (let i = k; i <= n; i++) {
      total += Math.exp(logChoose(n, i) + i * Math.log(p) + (n - i) * Math.log(1 - p));
    }
    return Math.min(1, total);
  }

  // Wilson score interval (95% by default) for a proportion.
  function wilson(k, n, z = 1.96) {
    if (n === 0) return [0, 1];
    const ph = k / n, d = 1 + z * z / n;
    const c = (ph + z * z / (2 * n)) / d;
    const h = z * Math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, c - h), Math.min(1, c + h)];
  }

  function fmtP(p) {
    if (p < 0.001) return 'p < 0.001';
    return `p = ${p.toFixed(p < 0.01 ? 3 : 2)}`;
  }

  return { CHANCE, binomTail, wilson, fmtP };
})();
