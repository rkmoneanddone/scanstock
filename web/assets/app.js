const $ = (id) => document.getElementById(id);
const labels = { open:"Open", high:"High", low:"Low", close:"Close", volume:"Volume" };
const relationships = { ">":"is above", ">=":"is at least", "<":"is below", "<=":"is at most", "=":"equals", "!=":"does not equal" };

async function loadStatus() {
  const response = await fetch('/api/status');
  const data = await response.json();
  $('status').textContent = `${data.loaded_stocks}/${data.configured_stocks} stocks ready · ${data.total_candles.toLocaleString()} candles`;
}

function updateMode() {
  const valueMode = $('compare-mode').value === 'value';
  $('value-box').hidden = !valueMode;
  $('field-box').hidden = valueMode;
  updatePreview();
}

function updatePreview() {
  const field = $('field').value;
  const right = $('compare-mode').value === 'field' ? `Daily ${labels[$('compare-field').value]}` : ($('compare-value').value || 'a number');
  $('preview').textContent = `Daily ${labels[field]} ${relationships[$('operator').value]} ${right}`;
  if ($('compare-mode').value === 'field' && field === 'close' && $('compare-field').value === 'open' && $('operator').value === '>') {
    $('explanation').textContent = 'Finds stocks whose latest Daily candle is green.';
  } else if ($('compare-mode').value === 'value') {
    $('explanation').textContent = `Checks the latest Daily ${labels[field].toLowerCase()} against your number.`;
  } else {
    $('explanation').textContent = 'Compares two values from each stock’s latest Daily candle.';
  }
}

function applyExample(name) {
  $('timeframe').value = '1D';
  $('operator').value = '>';
  if (name === 'green') {
    $('field').value = 'close'; $('compare-mode').value = 'field'; $('compare-field').value = 'open';
  } else if (name === 'price') {
    $('field').value = 'close'; $('compare-mode').value = 'value'; $('compare-value').value = '1000';
  } else if (name === 'volume') {
    $('field').value = 'volume'; $('compare-mode').value = 'value'; $('compare-value').value = '1000000';
  }
  updateMode();
}

function number(value) { return Number(value).toLocaleString('en-IN', { maximumFractionDigits:2 }); }

$('scanner-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = {
    timeframe:$('timeframe').value, field:$('field').value, operator:$('operator').value,
    compare_mode:$('compare-mode').value,
    compare_field:$('compare-mode').value === 'field' ? $('compare-field').value : null,
    compare_value:$('compare-mode').value === 'value' ? $('compare-value').value : null
  };
  if (payload.compare_mode === 'value' && payload.compare_value === '') { $('compare-value').focus(); return; }
  $('result-count').textContent = 'Scanning…';
  const response = await fetch('/api/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
  const data = await response.json();
  if (!response.ok) { $('result-count').textContent = data.detail || 'Scan failed'; return; }
  $('result-count').textContent = `${data.match_count} matching stocks`;
  $('results-body').innerHTML = data.matches.map(row => `<tr><td>${row.symbol}</td><td>${new Date(row.timestamp).toLocaleDateString('en-IN')}</td><td>${number(row.open)}</td><td>${number(row.high)}</td><td>${number(row.low)}</td><td>${number(row.close)}</td><td>${number(row.volume)}</td></tr>`).join('');
  $('empty').hidden = data.match_count > 0;
  $('empty').textContent = 'No stocks matched this condition.';
  $('table-wrap').hidden = data.match_count === 0;
});

$('reset').addEventListener('click', () => { $('scanner-form').reset(); updateMode(); });
document.querySelectorAll('.example').forEach(button => button.addEventListener('click', () => applyExample(button.dataset.example)));
['field','operator','compare-mode','compare-field','compare-value'].forEach(id => $(id).addEventListener('input', id === 'compare-mode' ? updateMode : updatePreview));
updateMode();
loadStatus().catch(() => { $('status').textContent = 'Database status unavailable'; });
