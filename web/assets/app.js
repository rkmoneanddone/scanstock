const $ = (id) => document.getElementById(id);
const state = { config:null, conditions:[], results:[], sortKey:'symbol', sortDirection:'asc', page:1, pageSize:25, category:'All', search:'', activeScan:'', activeTimeframe:'' };

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
  const [configResponse, statusResponse] = await Promise.all([fetch('/api/config'), fetch('/api/status')]);
  state.config = await configResponse.json();
  $('timeframe').innerHTML = optionList(state.config.timeframes, '1D');
  const status = await statusResponse.json();
  $('status').textContent = `${status.loaded_stocks}/${status.configured_stocks} stocks ready · ${status.total_candles.toLocaleString()} candles`;
  renderCategories(); renderPresets(); resetBuilder();
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
    <span>${item.category}</span><div class="preset-title"><h3>${periodText(item.name)}</h3><button class="preset-button" data-name="${item.name}" type="button" aria-label="Use ${item.name}">Use scanner →</button></div><p>${periodText(item.description)}</p>
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
  $('results-body').innerHTML = visible.map(row => { const tone = row.change_pct > 0 ? 'positive' : row.change_pct < 0 ? 'negative' : 'neutral'; return `<tr><td>${row.symbol}</td><td>${new Date(row.timestamp).toLocaleDateString('en-IN')}</td><td>${number(row.open)}</td><td>${number(row.high)}</td><td>${number(row.low)}</td><td class="${tone}">${number(row.close)}</td><td class="${tone}">${row.change_pct > 0 ? '+' : ''}${number(row.change_pct)}%</td><td>${number(row.rsi14,1)}</td><td>${number(row.volume,0)}</td><td><button class="detail-button" data-symbol="${row.symbol}" type="button" aria-label="View ${row.symbol} scan details">›</button></td></tr>`; }).join('');
  document.querySelectorAll('.detail-button').forEach(button => button.addEventListener('click', () => openDetails(button.dataset.symbol)));
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
loadApp().catch(() => { $('status').textContent = 'Database unavailable'; $('empty').textContent = 'Scanner configuration could not be loaded.'; });
