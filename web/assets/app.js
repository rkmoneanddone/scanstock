const $ = (id) => document.getElementById(id);
const state = { config:null, conditions:[], results:[], sortKey:'symbol', sortDirection:'asc', page:1, pageSize:25, category:'All', search:'', activeScan:'', activeTimeframe:'', activeTimeframeCode:'1D', chartCache:new Map() };

const optionList = (items, selected) => items.map(item => `<option value="${item.value}" ${item.value === selected ? 'selected' : ''}>${periodText(item.label)}</option>`).join('');
const number = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('en-IN', { maximumFractionDigits:digits });
const timeframeName = () => $('timeframe').selectedOptions[0]?.text || 'Daily';

function periodText(text) {
  const code = $('timeframe').value;
  const units = { '1D':'Day', '1W':'Week', '1M':'Month', '1Y':'Year' };
  if (units[code]) return text.replace(/(\d+)-Period/g, `$1-${units[code]}`).replace(/(\d+)-period/g, (_, n) => `${n}-${units[code].toLowerCase()}`);
  const unit = code === '3M' ? '3-Month' : '6-Month';
  return text.replace(/(\d+)-Period/g, `$1 × ${unit}`).replace(/(\d+)-period/g, (_, n) => `${n} selected ${unit.toLowerCase()} candles`);
}

function conditionSummary() {
  const fields = Object.fromEntries(state.config.fields.map(item => [item.value, item.label]));
  const operators = Object.fromEntries(state.config.operators.map(item => [item.value, item.label]));
  const parts = state.conditions.slice(0, 2).map(condition => {
    const right = condition.compare_mode === 'field' ? fields[condition.compare_field] : condition.compare_value;
    return `${periodText(fields[condition.field])} ${operators[condition.operator]} ${periodText(String(right))}`;
  });
  if (state.conditions.length > 2) parts.push(`+${state.conditions.length - 2} more`);
  return parts.join($('match-mode').value === 'all' ? ' AND ' : ' OR ');
}

async function loadApp() {
  const loaderStarted = performance.now();
  const configResponse = await fetch('/api/config');
  if (!configResponse.ok) throw new Error(`Scanner configuration failed (${configResponse.status})`);
  state.config = await configResponse.json();
  $('timeframe').innerHTML = optionList(state.config.timeframes, '1D');
  const remainingLoaderTime = 500 - (performance.now() - loaderStarted);
  if (remainingLoaderTime > 0) await new Promise(resolve => setTimeout(resolve, remainingLoaderTime));
  renderCategories(); renderPresets(); resetBuilder();
  loadDatabaseStatus();
}

async function loadDatabaseStatus() {
  try {
    const response = await fetch('/api/status');
    if (!response.ok) throw new Error(`Database status failed (${response.status})`);
    const status = await response.json();
    $('status').textContent = `${status.loaded_stocks}/${status.configured_stocks} stocks ready · ${status.total_candles.toLocaleString()} candles`;
  } catch (error) {
    $('status').textContent = 'Scanner ready · database status unavailable';
    console.error(error);
  }
}

function renderCategories() {
  const categories = ['All', ...new Set(state.config.presets.map(item => item.category))];
  $('category-tabs').innerHTML = categories.map(category => `<button class="category ${category === state.category ? 'active' : ''}" data-category="${category}" type="button">${periodText(category)}</button>`).join('');
  document.querySelectorAll('.category').forEach(button => button.addEventListener('click', () => {
    state.category = button.dataset.category; renderCategories(); renderPresets();
  }));
}

function renderPresets() {
  const presets = state.config.presets.filter(item => state.category === 'All' || item.category === state.category);
  $('preset-grid').innerHTML = presets.map(item => `<article class="preset-card" data-category="${item.category}">
    <div class="preset-topline"><span>${item.category}</span><button class="preset-button" data-name="${item.name}" type="button" aria-label="Use ${item.name}">Use scanner →</button></div><div class="preset-title"><h3>${periodText(item.name)}</h3></div><p>${periodText(item.description)}</p>
  </article>`).join('');
  document.querySelectorAll('.preset-button').forEach(button => button.addEventListener('click', () => applyPreset(button.dataset.name)));
}

function blankCondition() { return { field:'close', operator:'>', compare_mode:'field', compare_field:'open', compare_value:null }; }

function renderBuilder() {
  $('condition-list').innerHTML = state.conditions.map((condition, index) => `<div class="condition-row" data-index="${index}">
    <span class="condition-number">${index + 1}</span>
    <label><span>Metric</span><select data-property="field">${optionList(state.config.fields, condition.field)}</select></label>
    <label><span>Rule</span><select data-property="operator">${optionList(state.config.operators, condition.operator)}</select></label>
    <label><span>Compare with</span><select data-property="compare_mode"><option value="field" ${condition.compare_mode === 'field' ? 'selected' : ''}>Another metric</option><option value="value" ${condition.compare_mode === 'value' ? 'selected' : ''}>Fixed value</option></select></label>
    <label class="right-field" ${condition.compare_mode === 'value' ? 'hidden' : ''}><span>Metric</span><select data-property="compare_field">${optionList(state.config.fields, condition.compare_field)}</select></label>
    <label class="right-value" ${condition.compare_mode === 'field' ? 'hidden' : ''}><span>Value</span><input data-property="compare_value" type="number" step="any" value="${condition.compare_value ?? ''}" placeholder="Enter value"></label>
    <button class="remove-condition" type="button" aria-label="Remove condition" ${state.conditions.length === 1 ? 'disabled' : ''}>×</button>
  </div>`).join('');
  document.querySelectorAll('.condition-row').forEach(row => {
    const index = Number(row.dataset.index);
    row.querySelectorAll('[data-property]').forEach(control => control.addEventListener('change', () => {
      const property = control.dataset.property;
      state.conditions[index][property] = property === 'compare_value' ? (control.value === '' ? null : Number(control.value)) : control.value;
      if (property === 'compare_mode') renderBuilder();
    }));
    row.querySelector('.remove-condition').addEventListener('click', () => { state.conditions.splice(index, 1); renderBuilder(); });
  });
}

function resetBuilder() { state.conditions = [blankCondition()]; $('match-mode').value = 'all'; renderBuilder(); }

function applyPreset(name) {
  const preset = state.config.presets.find(item => item.name === name);
  state.conditions = structuredClone(preset.conditions); $('match-mode').value = 'all'; renderBuilder();
  runScan(periodText(preset.name), preset.category);
}

async function runScan(name=null, category='Custom Scanner') {
  const missingValue = state.conditions.some(condition => condition.compare_mode === 'value' && (condition.compare_value === null || condition.compare_value === ''));
  if (missingValue) { $('builder-message').textContent = 'Enter a fixed value for every value-based condition.'; return; }
  name = name || conditionSummary();
  state.activeScan = name; state.activeTimeframe = timeframeName();
  state.activeTimeframeCode = $('timeframe').value;
  $('result-count').textContent = 'Scanning…';
  $('active-scan').textContent = name;
  $('active-scan').dataset.category = category;
  $('result-timeframe').textContent = `${timeframeName()} timeframe`;
  $('loading-detail').textContent = `${timeframeName()} · ${name}`;
  $('loading').hidden = false;
  const payload = { timeframe:$('timeframe').value, match_mode:$('match-mode').value, conditions:state.conditions };
  let response, data;
  try {
    response = await fetch('/api/scan', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
    data = await response.json();
  } catch (error) {
    $('result-count').textContent = 'Scan failed'; $('empty').textContent = 'Unable to reach the scanner.'; $('empty').hidden = false; return;
  } finally { $('loading').hidden = true; }
  if (!response.ok) { $('result-count').textContent = 'Scan failed'; $('empty').textContent = data.detail || 'Unable to run scan.'; $('empty').hidden = false; return; }
  state.results = data.matches; state.page = 1; state.search = ''; $('result-search').value = '';
  $('result-count').textContent = `${data.match_count} matching stocks`;
  $('empty').textContent = data.match_count ? '' : 'No stocks matched this scanner.';
  $('empty').hidden = data.match_count > 0; $('results-content').hidden = data.match_count === 0;
  renderResults();
}

function renderResults() {
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  const rows = state.results.filter(row => row.symbol.toLowerCase().includes(state.search)).sort((a,b) => {
    const av = a[state.sortKey], bv = b[state.sortKey];
    if (av == null) return 1; if (bv == null) return -1;
    return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * direction;
  });
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize)); state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.pageSize, visible = rows.slice(start, start + state.pageSize);
  $('results-body').innerHTML = visible.map(row => { const tone = row.change_pct > 0 ? 'positive' : row.change_pct < 0 ? 'negative' : 'neutral'; return `<tr><td><button class="stock-link" data-symbol="${row.symbol}" type="button">${row.symbol}</button></td><td>${new Date(row.timestamp).toLocaleDateString('en-IN')}</td><td>${number(row.open)}</td><td>${number(row.high)}</td><td>${number(row.low)}</td><td class="${tone}">${number(row.close)}</td><td class="${tone}">${row.change_pct > 0 ? '+' : ''}${number(row.change_pct)}%</td><td>${number(row.rsi14,1)}</td><td>${number(row.volume,0)}</td><td><button class="detail-button" data-symbol="${row.symbol}" type="button" aria-label="View ${row.symbol} scan details">›</button></td></tr>`; }).join('');
  document.querySelectorAll('.detail-button,.stock-link').forEach(button => button.addEventListener('click', () => openDetails(button.dataset.symbol)));
  $('page-range').textContent = rows.length ? `${start + 1}–${Math.min(start + state.pageSize, rows.length)} of ${rows.length}` : '';
  $('result-count').textContent = state.search ? `${rows.length} shown · ${state.results.length} matched` : `${state.results.length} matching stocks`;
  $('page-number').textContent = `Page ${state.page} of ${pages}`;
  $('previous-page').disabled = state.page === 1; $('next-page').disabled = state.page === pages;
  document.querySelectorAll('.sort').forEach(button => {
    button.classList.toggle('active', button.dataset.key === state.sortKey);
    button.dataset.direction = button.dataset.key === state.sortKey ? state.sortDirection : '';
  });
}

function openDetails(symbol) {
  const row = state.results.find(item => item.symbol === symbol);
  if (!row) return;
  $('detail-title').textContent = row.symbol;
  $('detail-meta').textContent = `${state.activeScan} · ${row.details.timeframe} · ${new Date(row.timestamp).toLocaleDateString('en-IN')}`;
  $('detail-checks').innerHTML = row.details.checks.map(check => `<div class="detail-check ${check.passed ? 'passed' : 'failed'}"><span>${check.metric}</span><span>${number(check.actual)} ${check.operator} ${check.comparison === 'Fixed value' ? '' : check.comparison + ' '}${number(check.target)}</span><strong>${check.passed ? 'Passed' : 'Not passed'}</strong></div>`).join('');
  const measurements = Array.isArray(row.details.vcp) ? row.details.vcp : row.details.measurements;
  const hasMeasurements = Array.isArray(measurements) && measurements.length > 0;
  $('measurement-details').hidden = !hasMeasurements;
  $('measurement-title').textContent = Array.isArray(row.details.vcp) ? 'VCP measurements' : 'Scanner measurements';
  $('measurement-metrics').innerHTML = hasMeasurements ? measurements.map(item => `<div><span>${item.metric}</span><strong>${number(item.value)}</strong></div>`).join('') : '';
  $('detail-modal').hidden = false;
  document.body.classList.add('modal-open');
  loadChart(row, state.activeTimeframeCode);
}

async function loadChart(row, timeframe) {
  const slot = $('detail-chart-slot');
  const symbol = row.symbol;
  const cacheKey = `${symbol}:${timeframe}`;
  slot.innerHTML = '<div class="chart-loading"><span class="spinner"></span><span>Loading chart…</span></div>';
  $('chart-period').textContent = `${state.activeTimeframe} · loading history`;
  try {
    let data = state.chartCache.get(cacheKey);
    if (!data) {
      const response = await fetch(`/api/chart/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}&limit=250`);
      data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Chart request failed');
      state.chartCache.set(cacheKey, data);
    }
    slot.innerHTML = candlestickSvg(data.candles, row);
    $('chart-period').textContent = `${data.timeframe} · ${data.candles.length} periods`;
  } catch (error) {
    slot.innerHTML = `<div class="chart-error">${error.message || 'Chart could not be loaded.'}</div>`;
  }
}

function candlestickSvg(candles, row) {
  if (!candles.length) return '<div class="chart-error">No chart data available.</div>';
  const width = 920, height = 410, left = 58, right = 14, top = 16, priceBottom = 230;
  const volumeTop = 244, volumeBottom = 292, rsiTop = 310, rsiBottom = 382, bottom = volumeBottom;
  const innerWidth = width - left - right, priceHeight = priceBottom - top, volumeHeight = bottom - volumeTop;
  const highest = Math.max(...candles.map(c => c.high)), lowest = Math.min(...candles.map(c => c.low));
  const priceSpan = highest - lowest || 1, maxVolume = Math.max(...candles.map(c => c.volume)) || 1;
  const step = innerWidth / candles.length, bodyWidth = Math.max(1.5, Math.min(7, step * .62));
  const x = index => left + step * index + step / 2;
  const y = value => top + (highest - value) / priceSpan * priceHeight;
  const grid = Array.from({length:5}, (_, index) => {
    const value = highest - priceSpan * index / 4, lineY = y(value);
    return `<line x1="${left}" y1="${lineY}" x2="${width-right}" y2="${lineY}"/><text x="${left-7}" y="${lineY+4}" text-anchor="end">${number(value)}</text>`;
  }).join('');
  const marks = candles.map((candle, index) => {
    const candleX = x(index), openY = y(candle.open), closeY = y(candle.close), highY = y(candle.high), lowY = y(candle.low);
    const bullish = candle.close >= candle.open, tone = bullish ? '#16a34a' : '#dc2626';
    const bodyY = Math.min(openY, closeY), bodyHeight = Math.max(1.5, Math.abs(closeY-openY));
    const volumeHeightValue = candle.volume / maxVolume * volumeHeight;
    const date = new Date(candle.timestamp).toLocaleDateString('en-IN');
    return `<g><title>${date} · O ${number(candle.open)} · H ${number(candle.high)} · L ${number(candle.low)} · C ${number(candle.close)} · Vol ${number(candle.volume,0)}</title><line class="candle-wick" stroke="${tone}" x1="${candleX}" y1="${highY}" x2="${candleX}" y2="${lowY}"/><rect fill="${tone}" x="${candleX-bodyWidth/2}" y="${bodyY}" width="${bodyWidth}" height="${bodyHeight}"/><rect fill="${tone}" opacity=".36" x="${candleX-bodyWidth/2}" y="${bottom-volumeHeightValue}" width="${bodyWidth}" height="${volumeHeightValue}"/></g>`;
  }).join('');
  const maColors = {9:'#2563eb',21:'#16a34a',50:'#f59e0b',200:'#dc2626'};
  const maType = state.activeScan.includes('WMA') ? 'WMA' : state.activeScan.includes('SMA') ? 'SMA' : 'EMA';
  const closes = candles.map(candle => candle.close);
  const maSeries = Object.fromEntries(Object.keys(maColors).map(period => [period, movingAverageSeries(closes, Number(period), maType)]));
  const overlays = Object.entries(maColors).map(([period, color]) => {
    const values = maSeries[period];
    const points = values.map((value, index) => value == null ? null : `${x(index)},${y(value)}`).filter(Boolean);
    return points.length > 1 ? `<polyline class="ema-line" stroke="${color}" points="${points.join(' ')}"/>` : '';
  }).join('');
  const evidence = [...(row.details.vcp || []), ...(row.details.measurements || [])];
  const evidenceValue = label => evidence.find(item => item.metric === label)?.value;
  const levels = [
    ['VCP Pivot Price', evidenceValue('VCP Pivot Price'), '#0d9488'],
    ['Pivot 1', evidenceValue('First Pivot'), '#7c3aed'],
    ['Pivot 2', evidenceValue('Second Pivot'), '#7c3aed'],
    ['Neckline', evidenceValue('Pattern Neckline'), '#dc2626'],
    ['Previous ATH', evidenceValue('Previous All-Time High'), '#e11d48'],
  ].filter(([, value]) => Number.isFinite(value) && value >= lowest && value <= highest);
  const annotations = levels.map(([label, value, color]) => `<g class="chart-level"><line stroke="${color}" x1="${left}" y1="${y(value)}" x2="${width-right}" y2="${y(value)}"/><text fill="${color}" x="${width-right-3}" y="${y(value)-4}" text-anchor="end">${label} ${number(value)}</text></g>`).join('');
  let markerIndex = candles.length - 1;
  let markerLabel = state.activeScan;
  if (/Bullish (EMA|SMA|WMA) Alignment \+ Close Above 9/.test(state.activeScan)) {
    const fullyAligned = index => {
      const ma9 = maSeries['9'][index], ma21 = maSeries['21'][index];
      const ma50 = maSeries['50'][index], ma200 = maSeries['200'][index];
      return [ma9, ma21, ma50, ma200].every(Number.isFinite)
        && ma9 > ma21 && ma21 > ma50 && ma50 > ma200
        && candles[index].close > ma9;
    };
    // The selected stock qualifies now. Walk back through this same uninterrupted
    // fully-aligned regime and mark its first qualifying candle—only after every
    // 9/21/50/200 crossover has completed.
    if (fullyAligned(candles.length - 1)) {
      markerIndex = candles.length - 1;
      while (markerIndex > 0 && fullyAligned(markerIndex - 1)) markerIndex -= 1;
      markerLabel = `First candle after full ${maType} alignment`;
    } else {
      markerLabel = `${maType} alignment current`;
    }
  }
  const markerX = x(markerIndex), markerY = y(candles[markerIndex].low);
  const markerTextX = Math.min(width-right-4, Math.max(left+130, markerX+9));
  const scanMarker = `<g class="scan-marker crossover-marker"><path d="M ${markerX} ${Math.min(priceBottom-4,markerY+4)} l -6 10 h 12 z"/><text x="${markerTextX}" y="${Math.min(priceBottom-8,markerY+25)}" text-anchor="end">${escapeXml(markerLabel)}</text></g>`;
  const firstDate = new Date(candles[0].timestamp).toLocaleDateString('en-IN');
  const lastDate = new Date(candles[candles.length-1].timestamp).toLocaleDateString('en-IN');
  const legend = Object.entries(maColors).map(([period,color], index) => `<g transform="translate(${left+index*82},${top+2})"><line stroke="${color}" stroke-width="2" x1="0" y1="0" x2="16" y2="0"/><text x="20" y="4">${maType} ${period}</text></g>`).join('');
  const rsiValues = rsiSeries(closes, 14);
  const rsiY = value => rsiTop + (100 - value) / 100 * (rsiBottom - rsiTop);
  const rsiPoints = rsiValues.map((value, index) => value == null ? null : `${x(index)},${rsiY(value)}`).filter(Boolean);
  const rsiGuides = [70,50,30].map(value => `<line class="rsi-guide ${value === 50 ? 'middle' : ''}" x1="${left}" y1="${rsiY(value)}" x2="${width-right}" y2="${rsiY(value)}"/><text x="${left-7}" y="${rsiY(value)+4}" text-anchor="end">${value}</text>`).join('');
  const rsiChart = `<g class="rsi-panel">${rsiGuides}<text x="${left-7}" y="${rsiTop+10}" text-anchor="end">RSI</text>${rsiPoints.length > 1 ? `<polyline class="rsi-line" points="${rsiPoints.join(' ')}"/>` : ''}</g>`;
  return `<svg class="stock-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Candlestick, volume and RSI chart"><g class="chart-grid">${grid}<line x1="${left}" y1="${priceBottom}" x2="${width-right}" y2="${priceBottom}"/></g>${marks}${overlays}${annotations}${scanMarker}<g class="chart-legend">${legend}</g>${rsiChart}<g class="chart-dates"><text x="${left}" y="${height-7}">${firstDate}</text><text x="${width-right}" y="${height-7}" text-anchor="end">${lastDate}</text><text x="${left-7}" y="${volumeTop+12}" text-anchor="end">VOL</text></g></svg>`;
}

function rsiSeries(values, period=14) {
  const result = Array(values.length).fill(null);
  if (values.length <= period) return result;
  for (let index = period; index < values.length; index += 1) {
    let gains = 0, losses = 0;
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) {
      const change = values[cursor] - values[cursor - 1];
      if (change >= 0) gains += change; else losses -= change;
    }
    const averageGain = gains / period, averageLoss = losses / period;
    result[index] = averageLoss === 0 ? 100 : 100 - 100 / (1 + averageGain / averageLoss);
  }
  return result;
}

function movingAverageSeries(values, period, method) {
  const result = Array(values.length).fill(null);
  if (values.length < period) return result;
  if (method === 'SMA' || method === 'WMA') {
    const denominator = period * (period + 1) / 2;
    for (let index = period - 1; index < values.length; index += 1) {
      const window = values.slice(index - period + 1, index + 1);
      result[index] = method === 'SMA'
        ? window.reduce((sum, value) => sum + value, 0) / period
        : window.reduce((sum, value, offset) => sum + value * (offset + 1), 0) / denominator;
    }
    return result;
  }
  let ema = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  result[period-1] = ema;
  const multiplier = 2 / (period + 1);
  for (let index = period; index < values.length; index += 1) {
    ema = (values[index] - ema) * multiplier + ema;
    result[index] = ema;
  }
  return result;
}

function escapeXml(value) {
  return String(value).replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}[character]));
}

function closeDetails() { $('detail-modal').hidden = true; document.body.classList.remove('modal-open'); }

$('scanner-form').addEventListener('submit', event => { event.preventDefault(); runScan(); });
$('reset').addEventListener('click', resetBuilder);
$('add-condition').addEventListener('click', () => { if (state.conditions.length < 12) { state.conditions.push(blankCondition()); renderBuilder(); } });
$('timeframe').addEventListener('change', () => { renderCategories(); renderPresets(); renderBuilder(); });
$('result-search').addEventListener('input', event => { state.search = event.target.value.trim().toLowerCase(); state.page = 1; renderResults(); });
$('page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; renderResults(); });
$('previous-page').addEventListener('click', () => { state.page -= 1; renderResults(); });
$('next-page').addEventListener('click', () => { state.page += 1; renderResults(); });
document.querySelectorAll('.sort').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.key; state.sortDirection = state.sortKey === key && state.sortDirection === 'asc' ? 'desc' : 'asc'; state.sortKey = key; state.page = 1; renderResults();
}));
function setupCollapse(buttonId, bodyId) {
  $(buttonId).addEventListener('click', () => {
    const expanded = $(buttonId).getAttribute('aria-expanded') === 'true';
    $(buttonId).setAttribute('aria-expanded', String(!expanded));
    $(buttonId).textContent = expanded ? '+' : '−';
    $(bodyId).hidden = expanded;
  });
}
setupCollapse('toggle-presets', 'preset-body');
setupCollapse('toggle-custom', 'custom-body');
$('detail-close').addEventListener('click', closeDetails);
$('detail-modal').addEventListener('click', event => { if (event.target === $('detail-modal')) closeDetails(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('detail-modal').hidden) closeDetails(); });
loadApp().catch(error => {
  $('status').textContent = 'Scanner configuration unavailable';
  $('preset-grid').innerHTML = '<div class="preset-load-error">Scanner cards could not be loaded. Restart ScanStock and refresh this page.</div>';
  $('empty').textContent = 'Scanner configuration could not be loaded.';
  console.error(error);
});
