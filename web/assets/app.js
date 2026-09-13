const $ = (id) => document.getElementById(id);
const state = { config:null, conditions:[], results:[], sortKey:'symbol', sortDirection:'asc', page:1, pageSize:25, category:'All' };

const optionList = (items, selected) => items.map(item => `<option value="${item.value}" ${item.value === selected ? 'selected' : ''}>${item.label}</option>`).join('');
const number = (value, digits=2) => value == null ? '—' : Number(value).toLocaleString('en-IN', { maximumFractionDigits:digits });

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
  $('category-tabs').innerHTML = categories.map(category => `<button class="category ${category === state.category ? 'active' : ''}" data-category="${category}" type="button">${category}</button>`).join('');
  document.querySelectorAll('.category').forEach(button => button.addEventListener('click', () => {
    state.category = button.dataset.category; renderCategories(); renderPresets();
  }));
}

function renderPresets() {
  const presets = state.config.presets.filter(item => state.category === 'All' || item.category === state.category);
  $('preset-grid').innerHTML = presets.map(item => `<article class="preset-card" data-category="${item.category}">
    <span>${item.category}</span><h3>${item.name}</h3><p>${item.description}</p>
    <button class="preset-button" data-name="${item.name}" type="button">Use scanner <b>→</b></button>
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
  runScan(preset.name);
}

async function runScan(name='Custom scanner') {
  const missingValue = state.conditions.some(condition => condition.compare_mode === 'value' && (condition.compare_value === null || condition.compare_value === ''));
  if (missingValue) { $('builder-message').textContent = 'Enter a fixed value for every value-based condition.'; return; }
  $('result-count').textContent = 'Scanning…'; $('active-scan').textContent = name;
  $('loading-detail').textContent = `${$('timeframe').selectedOptions[0].text} · ${name}`;
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
  state.results = data.matches; state.page = 1;
  $('result-count').textContent = `${data.match_count} matching stocks`;
  $('empty').textContent = data.match_count ? '' : 'No stocks matched this scanner.';
  $('empty').hidden = data.match_count > 0; $('results-content').hidden = data.match_count === 0;
  renderResults();
}

function renderResults() {
  const direction = state.sortDirection === 'asc' ? 1 : -1;
  const rows = [...state.results].sort((a,b) => {
    const av = a[state.sortKey], bv = b[state.sortKey];
    if (av == null) return 1; if (bv == null) return -1;
    return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * direction;
  });
  const pages = Math.max(1, Math.ceil(rows.length / state.pageSize)); state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.pageSize, visible = rows.slice(start, start + state.pageSize);
  $('results-body').innerHTML = visible.map(row => { const tone = row.change_pct > 0 ? 'positive' : row.change_pct < 0 ? 'negative' : 'neutral'; return `<tr><td>${row.symbol}</td><td>${new Date(row.timestamp).toLocaleDateString('en-IN')}</td><td>${number(row.open)}</td><td>${number(row.high)}</td><td>${number(row.low)}</td><td class="${tone}">${number(row.close)}</td><td class="${tone}">${row.change_pct > 0 ? '+' : ''}${number(row.change_pct)}%</td><td>${number(row.rsi14,1)}</td><td>${number(row.volume,0)}</td></tr>`; }).join('');
  $('page-range').textContent = rows.length ? `${start + 1}–${Math.min(start + state.pageSize, rows.length)} of ${rows.length}` : '';
  $('page-number').textContent = `Page ${state.page} of ${pages}`;
  $('previous-page').disabled = state.page === 1; $('next-page').disabled = state.page === pages;
  document.querySelectorAll('.sort').forEach(button => {
    button.classList.toggle('active', button.dataset.key === state.sortKey);
    button.dataset.direction = button.dataset.key === state.sortKey ? state.sortDirection : '';
  });
}

$('scanner-form').addEventListener('submit', event => { event.preventDefault(); runScan(); });
$('reset').addEventListener('click', resetBuilder);
$('add-condition').addEventListener('click', () => { if (state.conditions.length < 12) { state.conditions.push(blankCondition()); renderBuilder(); } });
$('page-size').addEventListener('change', event => { state.pageSize = Number(event.target.value); state.page = 1; renderResults(); });
$('previous-page').addEventListener('click', () => { state.page -= 1; renderResults(); });
$('next-page').addEventListener('click', () => { state.page += 1; renderResults(); });
document.querySelectorAll('.sort').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.key; state.sortDirection = state.sortKey === key && state.sortDirection === 'asc' ? 'desc' : 'asc'; state.sortKey = key; state.page = 1; renderResults();
}));
loadApp().catch(() => { $('status').textContent = 'Database unavailable'; $('empty').textContent = 'Scanner configuration could not be loaded.'; });
