import { createServer } from 'vite';
import { mkdir, mkdtemp, realpath, rm } from 'node:fs/promises';
import { resolve, dirname, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, browserOptions } from './browser.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const engine = process.argv.find(arg => ['three', 'babylon', 'deck', 'cesium'].includes(arg)) || 'three';
const smoke = process.argv.includes('--smoke-test');
const population = process.argv.includes('--population') ? Number(process.argv[process.argv.indexOf('--population') + 1]) : 200;
const mode = process.argv.includes('--mode') ? process.argv[process.argv.indexOf('--mode') + 1] : 'orbit';
if (![200, 1000, 5000].includes(population) || !['orbit', 'walk', 'follow'].includes(mode)) throw new Error('Invalid population or camera mode');
let server, context, profile;
const profiles = resolve(root, '../.tools/browser-profiles');
try {
  server = await createServer({ configFile: resolve(root, 'vite.config.js'), server: { port: 0, strictPort: false } });
  await server.listen();
  const address = server.httpServer.address();
  const url = `http://127.0.0.1:${address.port}/?engine=${engine}&population=${population}&mode=${mode}`;
  await mkdir(profiles, { recursive: true });
  // Each launch owns a separate profile and closes its own local server on exit.
  profile = await mkdtemp(resolve(profiles, `${engine}-`));
  context = await chromium.launchPersistentContext(profile, {
    ...browserOptions(), headless: false, viewport: null,
    args: [`--app=${url}`, '--window-size=1440,1000'],
    ignoreDefaultArgs: ['--enable-automation'],
  });
  let page = context.pages().find(p => p.url().includes(`engine=${engine}`)) || context.pages()[0];
  if (!page) page = await context.waitForEvent('page');
  if (!page.url().includes(`engine=${engine}`)) await page.goto(url);
  await page.waitForFunction(() => window.comparison?.ready || window.comparison?.error, null, { timeout: 60000 });
  const error = await page.evaluate(() => window.comparison.error);
  if (error) throw new Error(error);
  console.log(`${engine} desktop window ready. Close the window to stop its local server.`);
  if (smoke) {
    console.log(JSON.stringify({ ...(await page.evaluate(() => window.comparison.getState())), windowCount: context.pages().length }));
  } else {
    process.on('SIGINT', () => context.close().catch(() => {}));
    await Promise.race([page.waitForEvent('close', { timeout: 0 }), context.waitForEvent('close', { timeout: 0 })]);
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
} finally {
  await context?.close();
  await server?.close();
  if (profile) {
    // Delete only this launch's generated profile, after resolving and checking
    // the exact absolute target stays inside this workspace's profile directory.
    const parent = await realpath(profiles);
    const target = await realpath(profile);
    if (!target.startsWith(parent + sep) || target === parent) throw new Error('Refusing to remove a profile outside the comparison cache');
    await rm(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
  }
}
