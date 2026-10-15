import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: 'light', reduced: false })));
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown = [];
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: 'root', nickname: '测试用户' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/upload/capabilities') body = { max_file_size: 52428800, extensions: ['png', 'jpg'] };
    else if (path === '/api/images/search') body = { images: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/emojis/search') body = { emojis: [], total: 0, limit: 20, offset: 0 };
    await route.fulfill({ json: body });
  });
  return errors;
}
async function sample(page: Page, progress: number) {
  return page.locator('.section-film-strip').evaluate(async (element, progress) => {
    const animation = element.getAnimations()[0]!;
    animation.pause(); animation.currentTime = Number(animation.effect!.getTiming().duration) * progress;
    await new Promise(requestAnimationFrame);
    const height = element.children[0]!.getBoundingClientRect().height;
    const y = new DOMMatrixReadOnly(getComputedStyle(element).transform).m42;
    const end = -(element.children.length - 1) * height;
    const index = Math.max(0, Math.min(element.children.length - 1, Math.floor(-y / height)));
    return { displacement: y - end, y, offset: y + index * height, visible: element.children[index]!.textContent, titles: Array.from(element.children, child => child.textContent), filter: getComputedStyle(element).filter, duration: animation.effect!.getTiming().duration };
  }, progress);
}
async function finish(page: Page) {
  await page.locator('.section-heading').evaluate(element => element.getAnimations({ subtree: true }).forEach(animation => animation.finish()));
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await expect(page.locator('.section-wheel')).toHaveClass(/is-idle/);
}

test('title makes one shared revolution and seats with two diminishing rebounds', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.goto('/#/gallery');
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'true');
  const start = await sample(page, 0);
  expect(start.titles).toEqual(['图片管理', '表情包库', '上传资源', '设置', '我的', '榜上有名', '图片管理']);
  const fast = await sample(page, .25), slowing = await sample(page, .60);
  expect(fast.y).toBeLessThan(start.y); expect(slowing.y).toBeLessThan(fast.y);
  expect(fast.filter).not.toBe('blur(0px)');
  for (const [time, displacement] of [[.70, -4], [.80, 2], [.88, -.9], [.95, .35], [1, 0]]) {
    const frame = await sample(page, time!);
    expect(frame.displacement).toBeCloseTo(displacement!, 2);
    expect(frame.filter).toBe('blur(0px)');
    if (time === .80) await page.locator('.section-heading').screenshot({ path: info.outputPath('title-first-rebound.png') });
  }
  await finish(page);
  await expect(page.locator('.section-film-frame')).toHaveText(['图片管理']);
  expect(errors).toEqual([]);
});

test('all three workspaces share a continuous reel and the same navigation clock', async ({ page }) => {
  const errors = await fixture(page);
  await page.goto('/#/gallery');
  await finish(page);
  const width = await page.locator('.section-film-title').evaluate(element => element.getBoundingClientRect().width);
  let previous = '图片管理';
  for (const title of ['表情包库', '上传资源', '图片管理']) {
    await page.locator('.modern-nav-link').filter({ hasText: title }).click();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    const clocks = await page.locator('.section-heading').evaluate(element => {
      const title = element.querySelector('.section-film-strip')!.getAnimations()[0]!;
      const rail = element.querySelector('.section-wheel-intro-backdrop')!.getAnimations()[0]!;
      return { title: title.startTime, rail: rail.startTime };
    });
    expect(typeof clocks.rail).toBe('number');
    expect(Math.abs(Number(clocks.title) - Number(clocks.rail))).toBeLessThan(1);
    const frame = await sample(page, 0);
    expect(frame.titles[0]).toBe(previous); expect(frame.titles.at(-1)).toBe(title);
    expect(frame.titles.length).toBeGreaterThanOrEqual(4); expect(frame.titles.length).toBeLessThanOrEqual(9);
    expect(frame.titles.every((name, i) => i === 0 || name !== frame.titles[i - 1])).toBe(true);
    expect(await page.locator('.section-film-title').evaluate(element => element.getBoundingClientRect().width)).toBeCloseTo(width, 1);
    await finish(page); previous = title;
  }
  expect(errors).toEqual([]);
});

test('interrupted reel retains its visible title and position, mobile motion is smaller', async ({ page }) => {
  const errors = await fixture(page);
  await page.goto('/#/gallery'); await finish(page);
  await page.locator('.modern-nav-link').filter({ hasText: '表情包库' }).click();
  const before = await sample(page, .30);
  await page.locator('.modern-nav-link').filter({ hasText: '上传资源' }).click();
  const after = await sample(page, 0);
  expect(after.visible).toBe(before.visible); expect(after.offset).toBeCloseTo(before.offset, 2);
  const forward = await sample(page, .02);
  expect(forward.y).toBeLessThan(after.y);
  await finish(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.modern-nav-link').filter({ hasText: '图片管理' }).click();
  expect((await sample(page, .70)).displacement).toBeCloseTo(-3, 2);
  expect((await sample(page, .80)).displacement).toBeCloseTo(1.5, 2);
  await finish(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.locator('.modern-nav-link').filter({ hasText: '表情包库' }).click();
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await expect(page.locator('.section-film-frame')).toHaveText(['表情包库']);
  expect(errors).toEqual([]);
});
