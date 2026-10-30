(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '—').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('en-IN', {maximumFractionDigits: digits});
  const stat = (name, data) => `<div class="trading-stat"><span>${escape(name)}</span><strong>${fmt(data.complete,0)} trades</strong><small>Wins: ${fmt(data.wins,0)} · Win rate: ${fmt(data.win_rate)}% · Mean net R: ${fmt(data.mean_r,3)}</small></div>`;
  el('trading-research-form').addEventListener('submit', async event => {
    event.preventDefault();
    const symbol = el('trading-symbol').value.trim().toUpperCase();
    const split = el('trading-split').value;
    if (!/^[A-Z0-9&.-]{1,24}$/.test(symbol)) { el('trading-message').textContent = 'Enter a valid stock symbol.'; return; }
    const button = el('trading-run');
    button.disabled = true;
    el('trading-results').hidden = true;
    el('trading-message').textContent = 'Running historical research…';
    try {
      const response = await fetch(`/api/trading/research/${encodeURIComponent(symbol)}?split_at=${encodeURIComponent(split)}`);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Research failed');
      el('trading-stats').innerHTML = stat('Training', data.summary.train) + stat('Unseen', data.summary.unseen);
      el('trading-trades').innerHTML = data.recent_trades.map(r => `<tr>
        <td>${escape((r.signal_at || '').slice(0,10))}</td><td>${escape(r.status)}</td>
        <td>${fmt(r.entry)}</td><td>${fmt(r.stop)}</td><td>${fmt(r.target)}</td>
        <td>${escape(r.outcome || r.reason)}</td><td>${fmt(r.r_multiple,3)}</td></tr>`).join('') || '<tr><td colspan="7">No signals found</td></tr>';
      el('trading-message').textContent = `${symbol} · Daily RSI/EMA · 10 bps each side · Research only`;
      el('trading-results').hidden = false;
    } catch (error) {
      el('trading-message').textContent = error.message;
    } finally { button.disabled = false; }
  });
})();
