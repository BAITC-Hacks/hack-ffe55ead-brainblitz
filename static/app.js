const $ = (id) => document.getElementById(id);
const demo = new URLSearchParams(location.search).get('demo') === '1';
const number = (value) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
const signed = (value) => `${value > 0 ? '+' : ''}${number(value)}`;
const versions = ['contract_version', 'dataset_version', 'rules_version'];
let config = null;
let revision = 0;
let controller = null;
let configController = null;
let configRevision = 0;
let busy = false;
let result = null;
const controls = new Map();

// Every dynamic string, including provider text and API errors, is a text node.
function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function option(value, label) {
  const element = node('option', label);
  element.value = value;
  return element;
}
function key(selections) {
  return JSON.stringify(selections.map(({ measure_id, district_id }) => ({ measure_id, district_id: district_id ?? null }))
    .sort((a, b) => a.measure_id.localeCompare(b.measure_id, 'en', { numeric: true })));
}
function matches(response, selections, reference) {
  return response && Array.isArray(response.selections) && key(response.selections) === key(selections)
    && versions.every((field) => response[field] === reference[field]);
}
async function request(url, { body, signal } = {}) {
  let response;
  try {
    response = await fetch(url, { signal, headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}) },
      ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error('Сетевая ошибка. Проверьте подключение и доступность сервера, затем повторите попытку.');
  }
  let data;
  try { data = await response.json(); } catch {
    throw new Error(`Сервер вернул ответ не в формате JSON (HTTP ${response.status}). Проверьте доступность API.`);
  }
  if (!response.ok) {
    const details = Array.isArray(data.detail) ? data.detail : [];
    const error = new Error(details.map((item) => item.message).filter(Boolean).join(' ') || `Ошибка сервера (HTTP ${response.status}). Повторите попытку.`);
    error.details = details;
    error.status = response.status;
    throw error;
  }
  return data;
}
const fixture = (name, signal) => request(`/static/demo/${name}.json`, { signal });
async function api(endpoint, body, signal) {
  if (!demo) return request(`/api/${endpoint}`, { body, signal });
  if (endpoint === 'config') return fixture('config', signal);
  const scenario = await fixture('scenario-b', signal);
  if (key(body.selections) !== key(scenario.selections)) {
    throw new Error('Для этого выбора нет полного демонстрационного ответа в API-контракте. Для примера B загрузите пример A и перенесите M7 из Есиля в Нуру. Остальные наборы требуют настоящего backend.');
  }
  return fixture(endpoint === 'simulate' ? 'simulation-b' : 'analysis-b', signal);
}
function validateConfig(data) {
  if (!data || data.contract_version !== '2.0' || data.dataset_version !== 'city-v1' || data.rules_version !== 'five-directions-v1'
    || !Number.isFinite(data.baseline_score) || !Number.isFinite(data.budget)
    || data.districts?.length !== 5 || data.measures?.length !== 14 || data.indicators?.length !== 10
    || data.required_categories?.length !== 5 || data.categories?.length !== 5) throw new Error('Конфигурация не соответствует контракту 2.0. Проверьте версию backend.');
  for (const district of data.districts) {
    if (!district.id || !district.name || !data.indicators.every((id) => Number.isFinite(district.indicators?.[id]) && typeof data.indicator_labels?.[id] === 'string')) throw new Error('Неполные исходные показатели в конфигурации.');
  }
  for (const measure of data.measures) {
    if (!measure.id || !measure.name || !data.required_categories.includes(measure.category) || !['city', 'district'].includes(measure.scope)
      || !Number.isFinite(measure.cost) || !Number.isFinite(measure.lag_quarters)) throw new Error('Некорректный каталог мероприятий.');
  }
  if (!data.required_categories.every((id) => data.categories.some((c) => c.id === id) && data.measures.some((m) => m.category === id))) throw new Error('В каталоге отсутствует обязательное направление.');
}
function renderBaseline() {
  $('budget-limit').textContent = config.budget;
  $('horizon').textContent = `Горизонт последствий: ${config.horizon_quarters} кварталов.`;
  $('baseline-score').textContent = number(config.baseline_score);
  $('versions').textContent = `Контракт ${config.contract_version} · ${config.dataset_version} · ${config.rules_version}`;
  const table = node('table');
  table.append(node('caption', 'Исходные данные. ! — критический показатель.'));
  const head = node('thead');
  const row = node('tr');
  for (const label of ['Район', ...config.indicators]) {
    const cell = node('th', label); cell.scope = 'col';
    if (config.indicator_labels[label]) cell.title = config.indicator_labels[label];
    row.append(cell);
  }
  head.append(row); table.append(head);
  const body = node('tbody');
  config.districts.forEach((district) => {
    const tr = node('tr'); const name = node('th', district.name); name.scope = 'row'; tr.append(name);
    config.indicators.forEach((id) => {
      const value = district.indicators[id];
      const cell = node('td', `${value}${value < 40 ? ' !' : ''}`, value < 40 ? 'critical' : '');
      cell.title = `${config.indicator_labels[id]}: ${value}${value < 40 ? ', критический' : ''}`; tr.append(cell);
    });
    body.append(tr);
  });
  table.append(body); $('baseline-table').replaceChildren(table);
  $('indicator-legend').replaceChildren(...config.indicators.flatMap((id) => [node('dt', id), node('dd', config.indicator_labels[id])]));
}
function updateCard(control) {
  const measure = config.measures.find((m) => m.id === control.measure.value);
  control.districtWrap.hidden = !measure || measure.scope === 'city';
  control.district.disabled = !measure || measure.scope === 'city';
  if (measure?.scope === 'city') control.district.value = '';
  control.info.textContent = measure ? `${measure.name}. ${measure.scope === 'city' ? 'Весь город' : 'Один район'} · ${measure.cost} ед. · лаг ${measure.lag_quarters} кв.` : 'Выберите мероприятие, чтобы увидеть стоимость и область действия.';
}
function renderChoices() {
  controls.clear(); $('decision-cards').replaceChildren();
  config.required_categories.forEach((categoryId, index) => {
    const category = config.categories.find((c) => c.id === categoryId);
    const field = node('fieldset', undefined, 'decision-card');
    field.append(node('legend', `${String(index + 1).padStart(2, '0')} / ${category.name}`));
    const label = node('label', 'Мероприятие'); label.htmlFor = `measure-${categoryId}`;
    const measure = node('select'); measure.id = label.htmlFor; measure.name = label.htmlFor;
    measure.append(option('', 'Выберите мероприятие'));
    config.measures.filter((m) => m.category === categoryId).forEach((m) => measure.append(option(m.id, `${m.id} · ${m.name} — ${m.cost} ед.`)));
    const districtWrap = node('div', undefined, 'district-control');
    const districtLabel = node('label', 'Район'); districtLabel.htmlFor = `district-${categoryId}`;
    const district = node('select'); district.id = districtLabel.htmlFor; district.name = districtLabel.htmlFor;
    district.append(option('', 'Выберите район'));
    config.districts.forEach((d) => district.append(option(d.id, d.name)));
    districtWrap.append(districtLabel, district);
    const info = node('p', undefined, 'measure-info');
    const control = { measure, district, districtWrap, info };
    controls.set(categoryId, control);
    measure.addEventListener('change', () => { updateCard(control); invalidate(); updateBudget(); });
    district.addEventListener('change', () => { invalidate(); updateBudget(); });
    field.append(label, measure, districtWrap, info); $('decision-cards').append(field); updateCard(control);
  });
}
function snapshot() {
  return [...controls.values()].filter((c) => c.measure.value).map((c) => ({ measure_id: c.measure.value,
    district_id: config.measures.find((m) => m.id === c.measure.value).scope === 'city' ? null : c.district.value || null }));
}
function updateBudget() {
  const selections = snapshot();
  const cost = selections.reduce((sum, s) => sum + config.measures.find((m) => m.id === s.measure_id).cost, 0);
  const complete = selections.filter((s) => s.district_id || config.measures.find((m) => m.id === s.measure_id).scope === 'city').length;
  $('total-cost').textContent = cost; $('remaining-budget').textContent = config.budget - cost;
  $('remaining-budget').closest('.budget-bar').classList.toggle('over-budget', cost > config.budget);
  $('selection-progress').textContent = cost > config.budget ? `Превышение бюджета: ${cost - config.budget} ед.` : `Готово ${complete} из ${config.required_selection_count} решений`;
  return { cost, complete };
}
function invalidate() {
  revision += 1; controller?.abort(); controller = null; busy = false;
  $('simulate').disabled = false;
  const hadResult = Boolean(result); result = null;
  $('result-content').hidden = true; $('result-content').replaceChildren(); $('ai-content').replaceChildren();
  $('simulation-status').textContent = hadResult ? 'Предыдущий результат устарел: решения изменены. Рассчитайте последствия заново.' : 'Решения изменены. Запустите расчёт для текущего выбора.';
  $('simulation-status').classList.toggle('stale', hadResult);
  $('ai-status').textContent = 'Разбор появится после нового расчёта.'; $('form-message').textContent = '';
  controls.forEach((c) => { c.measure.removeAttribute('aria-invalid'); c.district.removeAttribute('aria-invalid'); });
}
function validateSimulation(data, selections) {
  if (!matches(data, selections, config)) throw new Error('Ответ не соответствует выбору или версии конфигурации. Загрузите конфигурацию заново.');
  for (const field of ['baseline_score', 'final_score', 'score_delta', 'total_cost', 'remaining_budget']) {
    if (!Number.isFinite(data[field])) throw new Error('В ответе расчёта отсутствуют корректные числа.');
  }
  if (!Array.isArray(data.districts) || data.districts.length !== config.districts.length || !Array.isArray(data.critical_before) || !Array.isArray(data.critical_after)) throw new Error('Неполный ответ расчёта.');
  data.districts.forEach((district, index) => {
    if (district.id !== config.districts[index].id || !Number.isFinite(district.score_before) || !Number.isFinite(district.score_after)
      || !config.indicators.every((id) => ['before', 'after', 'changes'].every((field) => Number.isFinite(district[field]?.[id])))) throw new Error('Неполные районные показатели в ответе расчёта.');
  });
  for (const phase of ['before', 'after']) {
    const b = data.score_breakdown?.[phase];
    if (!b || !['city_average', 'weakest_district_score', 'critical_count'].every((f) => Number.isFinite(b[f])) || !config.districts.some((d) => d.id === b.weakest_district_id)) throw new Error('Неполное объяснение числового результата.');
  }
}
function renderResult(data) {
  const content = $('result-content'); content.replaceChildren();
  const metrics = node('div', undefined, 'score-grid');
  for (const [label, value, detail, featured] of [
    ['Исходный Score', number(data.baseline_score), 'До выбранных мер', false],
    ['Итоговый Score', number(data.final_score), `Изменение ${signed(data.score_delta)}`, true],
    ['Стоимость', data.total_cost, `Остаток ${data.remaining_budget} ед.`, false],
    ['Критические показатели', `${data.critical_before.length} → ${data.critical_after.length}`, 'Значения строго ниже 40', false]
  ]) { const metric = node('div', undefined, `metric${featured ? ' featured' : ''}`); metric.append(node('span', label), node('strong', value), node('small', detail)); metrics.append(metric); }
  content.append(metrics);
  const before = data.score_breakdown.before; const after = data.score_breakdown.after;
  content.append(node('p', `Средняя оценка города: ${number(before.city_average)} → ${number(after.city_average)}. Слабейший район после мер: ${config.districts.find((d) => d.id === after.weakest_district_id).name}, ${number(after.weakest_district_score)}.`, 'muted'));
  const districts = node('div', undefined, 'result-districts');
  data.districts.forEach((d) => {
    const block = node('article', undefined, 'district-result'); block.append(node('h3', d.name), node('p', `${number(d.score_before)} → ${number(d.score_after)}`));
    const changes = node('ul');
    config.indicators.filter((id) => d.changes[id] !== 0).forEach((id) => changes.append(node('li', `${config.indicator_labels[id]}: ${number(d.before[id])} → ${number(d.after[id])} (${signed(d.changes[id])})`)));
    if (!changes.children.length) changes.append(node('li', 'Показатели без изменений.'));
    block.append(changes); districts.append(block);
  });
  content.append(districts);
  const full = node('details'); full.append(node('summary', 'Все показатели до и после'));
  const scroll = node('div', undefined, 'table-scroll'); scroll.tabIndex = 0;
  const table = node('table'); table.append(node('caption', 'Для каждой пары: исходное → итоговое значение.'));
  const header = node('tr'); ['Район', ...config.indicators].forEach((id) => { const th = node('th', id); th.scope = 'col'; header.append(th); });
  const thead = node('thead'); thead.append(header); table.append(thead);
  const tbody = node('tbody');
  data.districts.forEach((d) => { const row = node('tr'); const th = node('th', d.name); th.scope = 'row'; row.append(th); config.indicators.forEach((id) => row.append(node('td', `${number(d.before[id])} → ${number(d.after[id])}${d.after[id] < 40 ? ' !' : ''}`, d.after[id] < 40 ? 'critical' : ''))); tbody.append(row); });
  table.append(tbody); scroll.append(table); full.append(scroll); content.append(full);
  content.append(node('h3', 'Критические показатели после решений'));
  const critical = node('ul', undefined, 'critical-list');
  data.critical_after.forEach((item) => critical.append(node('li', `${config.districts.find((d) => d.id === item.district_id)?.name || item.district_id} · ${config.indicator_labels[item.indicator] || item.indicator}: ${number(item.value)} — ниже 40.`)));
  if (!data.critical_after.length) critical.append(node('li', 'Критических показателей нет.'));
  content.append(critical, node('p', data.explanation, 'muted small'));
  content.hidden = false;
}
function validStatement(statement) {
  return statement && typeof statement.text === 'string' && Array.isArray(statement.evidence_paths) && statement.evidence_paths.length > 0
    && statement.evidence_paths.every((path) => {
      if (typeof path !== 'string' || !path.startsWith('/')) return false;
      let value = result;
      for (const part of path.slice(1).split('/').map((p) => p.replace(/~1/g, '/').replace(/~0/g, '~'))) {
        if (!value || !Object.hasOwn(value, part)) return false;
        value = value[part];
      }
      return true;
    });
}
function renderAnalysis(data, selections) {
  if (!matches(data, selections, result) || Math.abs(data.baseline_score - result.baseline_score) > 1e-8 || Math.abs(data.final_score - result.final_score) > 1e-8
    || !Number.isFinite(data.final_score) || !Number.isFinite(data.baseline_score)) throw new Error('AI-ответ относится к другому расчёту. Пересчитайте текущий выбор.');
  if (data.status === 'unavailable') {
    $('ai-status').textContent = `AI-разбор недоступен. ${data.message || 'Повторите расчёт позже.'} Числовой результат сохранён.`; return;
  }
  const a = data.analysis;
  if (data.status !== 'ok' || !a || !validStatement(a.summary) || !validStatement(a.tradeoff)
    || !Array.isArray(a.strengths) || !a.strengths.every(validStatement) || !Array.isArray(a.risks) || !a.risks.every(validStatement)
    || typeof a.reflection_question !== 'string' || !Array.isArray(a.limitations) || !a.limitations.every((s) => typeof s === 'string')) throw new Error('Некорректный формат AI-разбора. Числовой результат сохранён.');
  $('ai-status').textContent = demo ? 'Демонстрационный текст из API-контракта. Это не живой ответ AI.' : 'AI-разбор готов. Интерпретация может содержать ошибки; сверяйте её с показателями.';
  const content = $('ai-content'); content.replaceChildren(node('p', a.summary.text, 'ai-summary'));
  const grid = node('div', undefined, 'ai-grid');
  for (const [label, statements] of [['Сильные стороны', a.strengths], ['Риски', a.risks]]) {
    const section = node('div'); section.append(node('h3', label)); const list = node('ul');
    statements.forEach((s) => list.append(node('li', s.text)));
    if (!statements.length) list.append(node('li', 'В разборе не выделены.'));
    section.append(list); grid.append(section);
  }
  content.append(grid, node('h3', 'Компромисс'), node('p', a.tradeoff.text), node('h3', 'Вопрос для следующей попытки'), node('p', a.reflection_question, 'reflection'));
  a.limitations.forEach((text) => content.append(node('p', text, 'muted small')));
}
function showError(error, selections) {
  $('form-message').textContent = error.message;
  for (const detail of error.details || []) {
    if (detail.code === 'BUDGET_EXCEEDED') $('remaining-budget').closest('.budget-bar').classList.add('over-budget');
    const index = detail.path?.[1];
    if (detail.path?.[0] === 'selections' && Number.isInteger(index) && selections[index]) {
      const measure = config.measures.find((m) => m.id === selections[index].measure_id);
      const control = controls.get(measure?.category);
      if (control) (detail.path[2] === 'district_id' ? control.district : control.measure).setAttribute('aria-invalid', 'true');
    }
  }
}
async function simulate(event) {
  event.preventDefault(); if (!config || busy) return;
  invalidate();
  const { cost, complete } = updateBudget();
  if (complete !== config.required_selection_count) {
    $('form-message').textContent = 'Завершите все пять решений: выберите мероприятие и район для каждой локальной меры.';
    const first = [...controls.values()].find((c) => !c.measure.value || (!c.district.disabled && !c.district.value));
    (first?.measure.value ? first.district : first?.measure)?.focus(); return;
  }
  if (cost > config.budget) { $('form-message').textContent = `Стоимость ${cost} превышает бюджет ${config.budget}. Замените одно из мероприятий.`; return; }
  const selections = snapshot();
  const body = { selections }; // Same immutable snapshot for both POSTs; never send prices or scores.
  const attempt = revision;
  const attemptController = new AbortController(); controller = attemptController; const signal = attemptController.signal;
  busy = true; $('simulate').disabled = true;
  $('simulation-status').classList.remove('stale'); $('simulation-status').textContent = 'Рассчитываем последствия…';
  $('ai-status').textContent = 'Ожидаем числовой результат перед запросом AI.';
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; attemptController.abort(); }, 30000);
  try {
    const data = await api('simulate', body, signal);
    if (attempt !== revision) return;
    if (timedOut) throw new Error('Время ожидания расчёта истекло. Повторите попытку.');
    validateSimulation(data, selections); renderResult(data); result = data;
    $('simulation-status').textContent = demo ? 'Демонстрационный результат B из API-контракта. Backend не вызывался.' : 'Расчёт готов. Сервер проверил выбранный набор.';
  } catch (error) {
    if (attempt !== revision) return;
    result = null; $('result-content').hidden = true; $('result-content').replaceChildren();
    $('simulation-status').textContent = 'Расчёт не получен.';
    showError(timedOut ? new Error('Время ожидания расчёта истекло. Повторите попытку.') : error, selections);
    $('ai-status').textContent = 'AI-разбор не запрашивался: нет успешного расчёта.'; return;
  } finally {
    clearTimeout(timeout);
    if (attempt === revision && !result) { busy = false; $('simulate').disabled = false; }
  }
  if (attempt !== revision) return;
  $('ai-status').textContent = demo ? 'Загружаем пример AI-разбора из контракта…' : 'AI анализирует последствия… Числа уже доступны.';
  // Yield a rendering frame so numeric results paint before the independent AI request.
  await new Promise((resolve) => requestAnimationFrame(() => resolve()));
  if (attempt !== revision) return;
  timedOut = false;
  const aiTimeout = setTimeout(() => { timedOut = true; attemptController.abort(); }, 20000);
  try {
    const analysis = await api('analyze', body, signal);
    if (attempt !== revision) return;
    if (timedOut) throw new Error('AI не ответил вовремя.');
    renderAnalysis(analysis, selections);
  } catch (error) {
    if (attempt !== revision) return;
    $('ai-status').textContent = `AI-разбор недоступен. ${timedOut ? 'Время ожидания истекло.' : error.message} Числовой результат сохранён.`;
  } finally {
    clearTimeout(aiTimeout);
    if (attempt === revision) { busy = false; $('simulate').disabled = false; }
  }
}
async function loadExample() {
  let current = revision;
  try {
    const example = await fixture('scenario-a');
    if (current !== revision) return;
    invalidate();
    current = revision;
    for (const selection of example.selections) {
      const measure = config.measures.find((m) => m.id === selection.measure_id);
      if (!measure) throw new Error('Пример не соответствует каталогу.');
      const control = controls.get(measure.category); control.measure.value = measure.id;
      updateCard(control); control.district.value = selection.district_id ?? '';
    }
    updateBudget();
    $('simulation-status').textContent = 'Загружен сценарий A. Нажмите «Рассчитать последствия». Для B перенесите M7 из Есиля в Нуру.';
  } catch (error) { if (current === revision) $('form-message').textContent = `Не удалось загрузить пример. ${error.message}`; }
}
async function loadConfig() {
  const generation = ++configRevision;
  configController?.abort(); const loadingController = new AbortController(); configController = loadingController;
  invalidate(); config = null; $('workspace').hidden = true; $('retry-config').hidden = true;
  $('config-status').textContent = 'Загружаем районы и каталог мероприятий…';
  let timedOut = false;
  const timeout = setTimeout(() => { timedOut = true; loadingController.abort(); }, 15000);
  try {
    const data = await api('config', undefined, loadingController.signal);
    if (generation !== configRevision) return;
    validateConfig(data); config = data; renderBaseline(); renderChoices(); updateBudget();
    $('workspace').hidden = false; $('config-status').textContent = '';
    $('simulation-status').textContent = 'Выберите решения и запустите расчёт.';
  } catch (error) {
    if (generation !== configRevision) return;
    $('config-status').textContent = `Не удалось загрузить конфигурацию. ${timedOut ? 'Время ожидания истекло.' : error.message}`;
    $('retry-config').hidden = false;
  } finally { clearTimeout(timeout); }
}
if (demo) {
  $('mode-link').href = '?'; $('mode-link').textContent = 'Подключить реальный API';
  $('mode-notice').hidden = false;
  $('mode-notice').textContent = 'ДЕМОРЕЖИМ · Полные JSON-примеры API-контракта. Числовой ответ и запись AI доступны только для B: загрузите пример A, затем выберите Нуру для M7. Полного ответа A в документах нет. Другие наборы здесь не рассчитываются. Это не проверка backend или живого AI.';
}
$('retry-config').addEventListener('click', loadConfig);
$('load-example').addEventListener('click', loadExample);
$('decision-form').addEventListener('submit', simulate);
loadConfig();
