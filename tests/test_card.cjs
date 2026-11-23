// Run with NODE_PATH=/tmp/govee-card-test/node_modules node tests/test_card.cjs
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { chromium } = require('playwright');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.GOVEE_TEST_BROWSER || undefined });
  try {
    const page = await browser.newPage({ viewport: { width: 480, height: 1300 } });
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.setContent(`<style>body{margin:16px;font-family:system-ui;--primary-text-color:#222;--secondary-text-color:#555;--card-background-color:white;--divider-color:#ccc;--primary-color:#087abf}ha-card{display:block;background:white;border:1px solid #ddd;border-radius:14px}govee-backlight-card{display:block}ha-card::before{content:attr(header);display:block;padding:16px 16px 0;font-size:20px;font-weight:600}</style>`);
    await page.addScriptTag({ path: path.resolve('custom_components/govee_lan/govee-scene-card.js') });
    const scenes = JSON.parse(execFileSync('python3', ['-c',
      'import runpy,json; print(json.dumps(runpy.run_path("custom_components/govee_lan/h60a1_scenes.py")["H60A1_SCENES"]))'
    ], { encoding: 'utf8' }));
    await page.evaluate((scenes) => {
      window.calls = [];
      window.failNext = false;
      window.hass = {
        states: { 'light.ceiling': { state: 'on', attributes: {
          effect_list: scenes.map((scene) => scene.name), backlight_segment_count: 13,
          backlight_scene_presets: {},
        } } },
        async callService(domain, service, data) {
          window.calls.push({ domain, service, data });
          await new Promise((resolve) => setTimeout(resolve, 25));
          if (window.failNext) { window.failNext = false; throw new Error('Network unavailable'); }
          const attrs = this.states['light.ceiling'].attributes;
          if (service === 'save_backlight_scene') attrs.backlight_scene_presets[data.name] = { colors: data.colors };
          if (service === 'delete_backlight_scene') delete attrs.backlight_scene_presets[data.name];
          window.card.hass = this;
        },
      };
      window.card = document.createElement('govee-backlight-card');
      window.card.setConfig({ entity: 'light.ceiling' });
      window.card.hass = window.hass;
      document.body.append(window.card);
    }, scenes);
    const card = page.locator('govee-backlight-card');
    assert.equal(await card.locator('#preset option').count(), 80);
    assert.equal(await card.locator('.segment input').count(), 13);
    assert.equal(await card.locator('svg.ring path').count(), 13);
    await card.locator('#preset').selectOption('Rainbow');
    await card.locator('#activate').click();
    await card.locator('#status').filter({ hasText: 'Preset sent' }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.calls[0]), {
      domain: 'light', service: 'turn_on', data: { entity_id: 'light.ceiling', effect: 'Rainbow' },
    });
    await card.getByLabel('Segment 1 color', { exact: true }).fill('#123456');
    assert.equal(await card.locator('svg.ring path').first().getAttribute('fill'), '#123456');
    // HA state updates must not erase unsaved edits or change the selection.
    await page.evaluate(() => { window.card.hass = window.hass; });
    assert.equal(await card.getByLabel('Segment 1 color', { exact: true }).inputValue(), '#123456');
    assert.equal(await card.locator('#preset').inputValue(), 'Rainbow');
    const name = '<img src=x onerror=alert(1)>';
    await card.locator('#name').fill(name);
    await card.locator('#save').click();
    await card.locator('#status').filter({ hasText: 'Scene saved' }).waitFor();
    assert.equal(await card.locator('#saved').inputValue(), name);
    assert.equal(await card.locator('img').count(), 0);
    assert.equal(await page.evaluate(() => window.calls.at(-1).data.colors.length), 13);
    await card.locator('#clear').click();
    await card.locator('#apply').click();
    await card.locator('#status').filter({ hasText: 'Rear colors sent' }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.calls.at(-1)), {
      domain: 'govee_lan', service: 'set_segment_colors', data: {
        entity_id: 'light.ceiling', groups: [{ color: [0, 0, 0], segments: Array.from({ length: 13 }, (_, i) => i + 1) }],
      },
    });
    const beforeEdit = await page.evaluate(() => window.calls.length);
    await card.locator('#load').click();
    assert.equal(await card.getByLabel('Segment 1 color', { exact: true }).inputValue(), '#123456');
    assert.equal(await page.evaluate(() => window.calls.length), beforeEdit);
    await card.locator('#name').fill('Evening');
    await card.locator('#save-apply').click();
    await card.locator('#status').filter({ hasText: 'Scene saved and colors sent' }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.calls.slice(-2).map((call) => call.service)), ['save_backlight_scene', 'set_segment_colors']);
    await card.locator('#saved').selectOption('Evening');
    await page.screenshot({ path: '/tmp/govee-card-desktop.png', fullPage: true });
    await page.setViewportSize({ width: 320, height: 1350 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: '/tmp/govee-card-mobile.png', fullPage: true });
    await page.evaluate(() => { window.failNext = true; });
    await card.locator('#apply').click();
    await card.locator('#status').filter({ hasText: 'Network unavailable' }).waitFor();
    assert.equal(await card.locator('#apply').isDisabled(), false);
    await card.locator('#name').fill('');
    const beforeInvalid = await page.evaluate(() => window.calls.length);
    await card.locator('#save').click();
    await card.locator('#status').filter({ hasText: 'Enter a custom scene name' }).waitFor();
    assert.equal(await page.evaluate(() => window.calls.length), beforeInvalid);
    await card.locator('#saved').selectOption(name);
    await card.locator('#delete').click();
    await card.locator('#status').filter({ hasText: 'Scene deleted' }).waitFor();
    assert(!(await card.locator('#saved option').allTextContents()).includes(name));
    await page.evaluate(() => { window.hass.states['light.ceiling'].state = 'unavailable'; window.card.hass = window.hass; });
    assert(await card.locator('#apply').isDisabled());
    await page.evaluate(() => {
      window.hass.states['light.lamp'] = { state: 'on', attributes: { effect_list: ['SG: Breathe'] } };
      window.card.setConfig({ entity: 'light.lamp' }); window.card.hass = window.hass;
    });
    assert(await card.locator('#apply').isDisabled());
    assert.deepEqual(errors, []);
    console.log('Card browser checks passed: 79 presets, segment editing, save/apply/load/delete, safe names, errors, model guard, mobile layout');
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
