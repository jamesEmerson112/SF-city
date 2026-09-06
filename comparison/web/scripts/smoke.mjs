import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import { preview } from 'vite';
import { chromium, browserOptions } from './browser.mjs';
import { sampleResident, sampleGait, canWalk } from '../src/common.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const fixture = JSON.parse(await readFile(resolve(root, '../shared/scene.json'), 'utf8'));
const artifacts = resolve(root, '../artifacts');
await mkdir(artifacts, { recursive: true });
const names = process.env.COMPARISON_ENGINES?.split(',') || ['three', 'babylon', 'deck', 'cesium'];
let server, browser;
const results = [];
try {
  const base = process.env.COMPARISON_URL || 'http://127.0.0.1:5175';
  if (!process.env.COMPARISON_URL) server = await preview({ configFile: resolve(root, 'vite.config.js'), preview: { port: 5175 } });
  browser = await chromium.launch({ ...browserOptions(), headless: !process.argv.includes('--headed') });
  for (const name of names) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
    const errors = [], remote = new Set();
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('request', request => {
      const url = new URL(request.url());
      if (['http:', 'https:'].includes(url.protocol) && url.origin !== new URL(base).origin) remote.add(url.origin);
    });
    try {
      await page.goto(`${base}/?engine=${name}`, { waitUntil: 'domcontentloaded' });
      await page.waitForFunction(() => window.comparison?.ready || window.comparison?.error, null, { timeout: 60000 });
      assert.equal(await page.evaluate(() => window.comparison.error), undefined);
      await page.evaluate(() => { window.comparison.setPaused(true); window.comparison.setTime(17); });
      await page.waitForTimeout(500);
      const state = await page.evaluate(() => window.comparison.getState());
      assert.equal(state.primitiveCount, fixture.primitives.length);
      assert.equal(state.residentCount, fixture.residents.length);
      assert.equal(state.assetLoaded, true, `${name} did not import the Blender asset`);
      const expected = sampleResident(fixture, fixture.residents[0], 17).position;
      assert.ok(Math.hypot(...expected.map((v, i) => v - state.sampleResidentPosition[i])) < 0.001, `${name} incorrect resident position`);
      await page.screenshot({ path: resolve(artifacts, `${name}.png`) });
      await page.waitForTimeout(200);
      assert.equal((await page.evaluate(() => window.comparison.getState())).simulationTime, 17);
      await page.keyboard.press('Space');
      await page.waitForFunction(() => window.comparison.getState().simulationTime > 17.05);
      await page.keyboard.press('Space');
      await page.keyboard.press('KeyT');
      assert.equal((await page.evaluate(() => window.comparison.getState())).speed, 4);
      await page.keyboard.press('KeyT');
      // Click the rendered landmark; fixture cameras aim just below its dome.
      const stage = await page.locator('#stage').boundingBox();
      let selection = null;
      for (const [x, y] of [[0.5, 0.4], [0.5, 0.45], [0.48, 0.5], [0.52, 0.35], [0.5, 0.5]]) {
        await page.mouse.click(stage.x + stage.width * x, stage.y + stage.height * y);
        selection = (await page.evaluate(() => window.comparison.getState())).selection;
        if (selection?.type === 'building') break;
      }
      assert.ok(selection?.id, `${name} picking did not select geometry`);
      await page.keyboard.press('Digit2');
      const start = await page.evaluate(() => window.comparison.getState());
      assert.equal(start.mode, 'walk');
      await page.keyboard.down('KeyW');
      await page.waitForTimeout(700);
      await page.keyboard.up('KeyW');
      const moved = await page.evaluate(() => window.comparison.getState());
      assert.ok(Math.hypot(...moved.cameraPosition.map((v, i) => v - start.cameraPosition[i])) > 0.1, `${name} WASD did not move camera`);
      assert.ok(canWalk(fixture, ...moved.cameraPosition.slice(0, 2)), `${name} walked inside obstacle`);
      await page.screenshot({ path: resolve(artifacts, `${name}-walk.png`) });
      // Exercise the actual UI and rendered state at every crowd workload.
      await page.evaluate(() => { window.comparison.setMode('walk'); window.comparison.setTime(17); });
      const walkCamera = (await page.evaluate(() => window.comparison.getState())).cameraPosition;
      const populations = [];
      for (const count of [1000, 5000, 200]) {
        await page.selectOption('#population', String(count));
        await page.waitForFunction(count => {
          const state = window.comparison.getState();
          return !state.populationBusy && state.residentCount === count;
        }, count, { timeout: 60000 });
        const crowd = await page.evaluate(() => window.comparison.getState());
        const links = await page.locator('#engines a').evaluateAll(items => items.map(item => item.href));
        for (const link of links) {
          assert.equal(new URL(link).searchParams.get('population'), String(count));
          assert.equal(new URL(link).searchParams.get('mode'), 'walk');
        }
        assert.equal(crowd.simulationTime, 17);
        assert.deepEqual(crowd.cameraPosition, walkCamera, `${name} changed camera when population changed`);
        assert.equal(crowd.assetLoaded, true);
        assert.ok(crowd.visibleResidentCount > 0 && crowd.visibleResidentCount <= count);
        assert.ok(crowd.animatedResidentCount > 0 && crowd.animatedResidentCount <= Math.min(count, fixture.character.max_animated));
        assert.ok(Math.hypot(...expected.map((v, i) => v - crowd.sampleResidentPosition[i])) < 0.001);
        const sampleIndex = Number(crowd.sampleAnimatedResidentId?.slice('resident-'.length));
        assert.ok(Number.isInteger(sampleIndex) && sampleIndex >= 0 && sampleIndex < count);
        const resident = { phase: (sampleIndex * 0.61803398875) % 1 };
        assert.ok(Math.abs(crowd.sampleGaitAngle - sampleGait(resident, 17)) < 0.001, `${name} rendered gait differs from shared animation`);
        await page.evaluate(() => window.comparison.setTime(17.1));
        const stepped = await page.evaluate(() => window.comparison.getState());
        assert.ok(Math.abs(stepped.sampleGaitAngle - crowd.sampleGaitAngle) > 0.001, `${name} limbs did not animate`);
        await page.evaluate(() => window.comparison.setTime(17));
        populations.push({ count, visible: crowd.visibleResidentCount, animated: crowd.animatedResidentCount });
        if (count === 5000) await page.screenshot({ path: resolve(artifacts, `${name}-5000-walk.png`) });
      }
      await page.locator('#population').blur();
      await page.keyboard.press('Digit3');
      assert.equal((await page.evaluate(() => window.comparison.getState())).mode, 'follow');
      await page.evaluate(() => window.comparison.setTime(25));
      const followA = await page.evaluate(() => window.comparison.getState());
      await page.evaluate(() => window.comparison.setTime(30));
      const followB = await page.evaluate(() => window.comparison.getState());
      assert.notDeepEqual(followA.cameraPosition, followB.cameraPosition, `${name} follow camera did not follow`);
      await page.screenshot({ path: resolve(artifacts, `${name}-follow.png`) });
      await page.keyboard.press('KeyR');
      assert.equal((await page.evaluate(() => window.comparison.getState())).simulationTime, 0);
      await page.keyboard.press('Digit1');
      assert.equal((await page.evaluate(() => window.comparison.getState())).mode, 'orbit');
      await page.setViewportSize({ width: 1100, height: 760 });
      await page.waitForTimeout(250);
      assert.equal(await page.locator('#loading').isVisible(), false);
      assert.deepEqual(errors, [], `${name} browser errors`);
      assert.equal(remote.size, 0, `${name} fetched external content: ${[...remote]}`);
      results.push({ engine: name, ok: true, selected: selection, initialState: state, populations });
      console.log(`PASS ${name}: Blender import, 200/1000/5000 crowds, gait, movement, pause, picking, 3 cameras, WASD, reset, resize, local-only assets`);
    } catch (error) {
      await page.screenshot({ path: resolve(artifacts, `${name}-failure.png`) }).catch(() => {});
      results.push({ engine: name, ok: false, error: error.stack, browserErrors: errors });
      console.error(`FAIL ${name}: ${error.message}`);
    } finally { await page.close(); }
  }
} finally {
  await browser?.close();
  await server?.close();
  await writeFile(resolve(artifacts, 'web-smoke-results.json'), JSON.stringify(results, null, 2));
}
if (results.some(result => !result.ok)) process.exitCode = 1;
