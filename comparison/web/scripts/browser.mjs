import { chromium } from 'playwright';
import { existsSync } from 'node:fs';

export function browserOptions() {
  const channel = process.env.COMPARISON_BROWSER;
  if (channel) return { channel };
  // Prefer installed Edge on Windows, keeping this demo free of another download.
  if (process.platform === 'win32' && existsSync('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe')) return { channel: 'msedge' };
  if (existsSync(chromium.executablePath())) return {};
  if (process.platform === 'win32' && existsSync('C:/Program Files/Google/Chrome/Application/chrome.exe')) return { channel: 'chrome' };
  throw new Error('No browser found. Install one with: npx playwright install chromium, or set COMPARISON_BROWSER=chrome or msedge.');
}
export { chromium };
