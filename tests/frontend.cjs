// Browser contract tests. Uses an existing Playwright installation; no production dependencies.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '..');
const read = (name) => JSON.parse(fs.readFileSync(path.join(root, 'static/demo', `${name}.json`), 'utf8'));
const clone = (v) => structuredClone(v);
const config = read('config'), b = read('simulation-b'), ai = read('analysis-b'), aRequest = read('scenario-a');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const file = path.resolve(root, '.' + (url.pathname === '/' ? '/static/index.html' : url.pathname));
  if (!file.startsWith(root + path.sep)) { res.writeHead(403); res.end(); return; }
  fs.readFile(file, (err, data) => { if (err) { res.writeHead(404); res.end(); return; }
    res.setHeader('Content-Type', ({ '.html': 'text/html; charset=utf-8', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json' })[path.extname(file)] || 'text/plain'); res.end(data); });
});
let browser;
async function main() {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const examples = [...fs.readFileSync(path.join(root, 'docs/api-contract.md'), 'utf8').matchAll(/```json\n([\s\S]*?)\n```/g)].map((m) => JSON.parse(m[1]));
  for (const file of fs.readdirSync(path.join(root, 'static/demo'))) {
    const value = read(file.replace('.json', ''));
    assert.ok(examples.some((example) => { try { assert.deepEqual(value, example); return true; } catch { return false; } }), `${file} must exactly match a complete contract example`);
  }
  console.log('PASS all demo JSON files match complete contract examples');
  browser = await chromium.launch({ headless: true, ...(process.env.BROWSER_PATH ? { executablePath: process.env.BROWSER_PATH } : { channel: 'msedge' }) });
  let passed = 0;
  async function test(name, run) {
    const page = await browser.newPage(); const errors = []; page.on('pageerror', (e) => errors.push(e.message));
    try { await run(page); assert.deepEqual(errors, []); console.log(`PASS ${name}`); passed++; } finally { await page.close(); }
  }
  async function setup(page, overrides = {}) {
    const calls = [];
    await page.route('**/api/**', async (route) => {
      const endpoint = new URL(route.request().url()).pathname.split('/').pop();
      const body = route.request().method() === 'POST' ? route.request().postDataJSON() : undefined;
      calls.push({ endpoint, body });
      if (overrides[endpoint]) return overrides[endpoint](route, body);
      await route.fulfill({ json: endpoint === 'config' ? config : endpoint === 'simulate' ? b : ai });
    });
    await page.goto(origin); await page.locator('#workspace').waitFor({ state: 'visible' }); return calls;
  }
  async function example(page, useB = true) {
    await page.getByRole('button', { name: 'Загрузить пример', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('#measure-social').value === 'M7');
    if (useB) await page.locator('#district-social').selectOption('nura');
  }
  async function submit(page) { await page.locator('#simulate').click(); }
  async function ready(page) { await page.waitForFunction(() => !document.querySelector('#result-content').hidden); }
  await test('explicit demo: A selected, M7 moved to Nura, complete B fixture displayed', async (page) => {
    const calls = []; page.on('request', (r) => { if (r.url().includes('/api/')) calls.push(r.url()); });
    await page.goto(`${origin}/?demo=1`); await example(page, false);
    assert.equal(await page.locator('#total-cost').innerText(), '83');
    await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('нет полного'));
    assert.equal(await page.locator('#result-content').isVisible(), false);
    await page.locator('#district-social').selectOption('nura'); assert.equal(await page.locator('#total-cost').innerText(), '83');
    await submit(page); await ready(page); await page.waitForFunction(() => document.querySelector('#ai-content').textContent.includes('Школа'));
    assert.match(await page.locator('#result-content').innerText(), /55,07/); assert.match(await page.locator('#ai-status').innerText(), /не живой/); assert.deepEqual(calls, []);
    const out = process.env.SCREENSHOT_DIR;
    if (out) { fs.mkdirSync(out, { recursive: true }); await page.screenshot({ path: path.join(out, 'frontend-desktop.png'), fullPage: true });
      await page.setViewportSize({ width: 390, height: 844 }); assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: path.join(out, 'frontend-mobile.png'), fullPage: true }); }
  });
  await test('config network failure stays real; retry loads config', async (page) => {
    let fail = true; await page.route('**/api/config', (route) => fail ? route.abort() : route.fulfill({ json: config }));
    await page.goto(origin); await page.locator('#retry-config').waitFor({ state: 'visible' });
    assert.match(await page.locator('#config-status').innerText(), /Сетевая ошибка/); assert.equal(await page.locator('#mode-notice').isVisible(), false);
    fail = false; await page.locator('#retry-config').click(); await page.locator('#workspace').waitFor({ state: 'visible' });
  });
  await test('incomplete selection, local district requirement, budget 107 blocked', async (page) => {
    const calls = await setup(page); await submit(page); assert.match(await page.locator('#form-message').innerText(), /пять решений/);
    await example(page); await page.locator('#district-social').selectOption(''); await submit(page); assert.match(await page.locator('#form-message').innerText(), /район/);
    await page.locator('#district-social').selectOption('nura'); await page.locator('#measure-transport').selectOption('M3'); await page.locator('#measure-environment').selectOption('M5'); await page.locator('#measure-services').selectOption('M14');
    await submit(page); assert.match(await page.locator('#form-message').innerText(), /107/); assert.equal(calls.filter((c) => c.endpoint !== 'config').length, 0);
  });
  await test('same snapshot, exact POST fields, city null, numbers visible before AI', async (page) => {
    let release; const gate = new Promise((resolve) => { release = resolve; });
    const calls = await setup(page, { analyze: async (route) => { await gate; await route.fulfill({ json: ai }); } });
    await example(page); assert.equal(await page.locator('#district-services').isVisible(), false); await submit(page); await ready(page);
    await page.waitForFunction(() => document.querySelector('#ai-status').textContent.includes('анализирует'));
    assert.match(await page.locator('#result-content').innerText(), /55,07/);
    await sleep(80); assert.deepEqual(calls.filter((c) => c.body).map((c) => c.body), [read('scenario-b'), read('scenario-b')]);
    release(); await page.waitForFunction(() => document.querySelector('#ai-content').textContent.length > 0);
  });
  await test('scenario A is submitted unchanged to real endpoint, never replaced by B', async (page) => {
    const calls = await setup(page, { simulate: (route) => route.fulfill({ status: 503, json: { detail: [{ message: 'Тестовый backend недоступен.' }] } }) });
    await example(page, false); await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('Тестовый'));
    assert.deepEqual(calls[1].body, aRequest); assert.equal(calls.length, 2);
  });
  await test('server 422 detail shown; analyze not called; budget 100 sent to server', async (page) => {
    const calls = await setup(page, { simulate: (route) => route.fulfill({ status: 422, json: read('error-conflict') }) });
    await example(page); await page.locator('#measure-transport').selectOption('M3');
    await page.locator('#measure-environment').selectOption('M6'); assert.equal(await page.locator('#total-cost').innerText(), '100');
    // Server response deliberately injected to test 422 handling, not model validity.
    await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('M4 и M7'));
    assert.equal(calls.filter((c) => c.endpoint === 'analyze').length, 0);
  });
  await test('AI unavailable and network error both preserve numeric results', async (page) => {
    let network = false; await setup(page, { analyze: (route) => network ? route.abort() : route.fulfill({ json: read('analysis-unavailable-b') }) });
    await example(page); await submit(page); await page.waitForFunction(() => document.querySelector('#ai-status').textContent.includes('недоступен'));
    assert.equal(await page.locator('#result-content').isVisible(), true);
    network = true; await submit(page); await page.waitForFunction(() => document.querySelector('#ai-status').textContent.includes('Сетевая ошибка'));
    assert.equal(await page.locator('#result-content').isVisible(), true);
  });
  await test('late simulation ignored even after selection restored', async (page) => {
    let release; const gate = new Promise((resolve) => { release = resolve; });
    // Ignore AbortSignal deliberately: revision guard must work even if transport cannot cancel.
    await page.addInitScript(() => { const original = window.fetch; window.fetch = (url, options = {}) => { const { signal, ...rest } = options; return original(url, rest); }; });
    const calls = await setup(page, { simulate: async (route) => { await gate; await route.fulfill({ json: b }).catch(() => {}); } });
    await example(page); await submit(page); await sleep(60);
    await page.locator('#district-social').selectOption('esil'); await page.locator('#district-social').selectOption('nura'); release(); await sleep(150);
    assert.equal(await page.locator('#result-content').isVisible(), false); assert.equal(calls.filter((c) => c.endpoint === 'analyze').length, 0);
  });
  await test('late AI ignored; new attempt completes independently', async (page) => {
    let release; let count = 0; const gate = new Promise((resolve) => { release = resolve; });
    await page.addInitScript(() => { const original = window.fetch; window.fetch = (url, options = {}) => { const { signal, ...rest } = options; return original(url, rest); }; });
    await setup(page, { analyze: async (route) => { if (++count === 1) await gate; await route.fulfill({ json: ai }).catch(() => {}); } });
    await example(page); await submit(page); await ready(page); await sleep(80);
    await page.locator('#district-social').selectOption('esil'); await page.locator('#district-social').selectOption('nura');
    assert.equal(await page.locator('#result-content').isVisible(), false); release(); await sleep(100); assert.equal(await page.locator('#ai-content').innerText(), '');
    await submit(page); await ready(page); await page.waitForFunction(() => document.querySelector('#ai-content').textContent.length > 0);
  });
  await test('selection/version mismatch rejected, AI text is inert', async (page) => {
    let mismatch = true; const unsafe = clone(ai); unsafe.analysis.summary.text = '<img src=x onerror="window.pwned=1">';
    await setup(page, { analyze: (route) => route.fulfill({ json: mismatch ? { ...ai, dataset_version: 'wrong' } : unsafe }) });
    await example(page); await submit(page); await page.waitForFunction(() => document.querySelector('#ai-status').textContent.includes('другому расчёту'));
    assert.equal(await page.locator('#result-content').isVisible(), true); mismatch = false; await submit(page);
    await page.waitForFunction(() => document.querySelector('#ai-content').textContent.includes('<img'));
    assert.equal(await page.locator('#ai-content img').count(), 0); assert.equal(await page.evaluate(() => window.pwned), undefined);
  });
  await test('simulation network failure and mismatched response produce no result or AI', async (page) => {
    let network = true;
    const calls = await setup(page, { simulate: (route) => network ? route.abort() : route.fulfill({ json: { ...b, selections: aRequest.selections } }) });
    await example(page); await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('Сетевая ошибка'));
    network = false; await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('не соответствует'));
    assert.equal(await page.locator('#result-content').isVisible(), false); assert.equal(calls.filter((c) => c.endpoint === 'analyze').length, 0);
    assert.equal(await page.locator('#simulate').isEnabled(), true);
  });
  await test('server BUDGET_EXCEEDED detail is displayed without deriving a Score', async (page) => {
    await setup(page, { simulate: (route) => route.fulfill({ status: 422, json: read('error-budget') }) });
    await example(page); await submit(page); await page.waitForFunction(() => document.querySelector('#form-message').textContent.includes('107'));
    assert.equal(await page.locator('#result-content').isVisible(), false);
  });
  console.log(`${passed} browser tests passed. All API responses are mocked; no backend integration claimed.`);
}
main().catch((error) => { console.error(error); process.exitCode = 1; }).finally(async () => { await browser?.close(); server.close(); });
