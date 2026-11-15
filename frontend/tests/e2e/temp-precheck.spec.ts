import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

test('temp precheck follows visible cards, pauses offscreen and reuses completed results', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 400 });
  await page.setContent('<div id="temp-precheck-status"></div><div id="cards" style="height:280px;overflow:auto"></div>');
  const source = readFileSync(resolve('../static/js/upload.js'), 'utf8').replace('window.upload = new UploadManager();', 'window.UploadManager = UploadManager;');
  await page.addScriptTag({ content: source });
  await page.evaluate(() => {
    const w = window as any;
    w.ui = { currentPage: 'upload', currentTab: 'temp-upload' };
    w.checked = [];
    w.api = { request: async (url: string, options: any) => {
      if (url.endsWith('/start')) return { run_id: 'browser' };
      const name = JSON.parse(options.body).filename;
      w.checked.push(name);
      return { filename: name, status: 'ordinary' };
    }};
    w.UploadManager.prototype.initializeEventListeners = () => {};
    const upload = w.upload = new w.UploadManager();
    upload.tempActive = true; upload.tempAbort = new AbortController();
    upload.updateTempCard = () => {}; upload.stopTempRun = () => {};
    upload.tempNames = Array.from({length: 80}, (_, i) => `file-${i}`);
    document.getElementById('cards')!.innerHTML = upload.tempNames.map((name: string) => `<article data-image-name="${name}" style="height:140px">${name}</article>`).join('');
    upload.tempCards = new Map(Array.from(document.querySelectorAll('article'), card => [(card as HTMLElement).dataset.imageName, card]));
    upload.observeTempCards();
  });
  await expect.poll(() => page.evaluate(() => (window as any).checked.length)).toBeGreaterThan(0);
  const initial = await page.evaluate(() => (window as any).checked.slice());
  expect(initial.length).toBeLessThanOrEqual(3);
  await page.locator('#cards').evaluate(node => { node.scrollTop = 1400; });
  await expect.poll(() => page.evaluate(() => (window as any).checked.includes('file-10'))).toBe(true);
  const afterScroll = await page.evaluate(() => (window as any).checked.slice());
  expect(afterScroll).not.toContain('file-5');
  await page.locator('#cards').evaluate(node => { node.scrollTop = 0; });
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => (window as any).checked)).toEqual(afterScroll);
  await page.evaluate(() => (window as any).upload.suspendTemp());
});
