import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: 'light', reduced: false })));
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: 'root', nickname: '测试用户' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/groups/') body = [{ id: 1, name: '测试分组', aliases: [], description: '' }];
    else if (path === '/api/characters/') body = [{ id: 1, name: '测试角色', group_id: 1, nicknames: [], feature_tags: [] }];
    else if (path === '/api/feature-tags/') body = [{ id: 1, name: '测试特征', aliases: [] }];
    else if (path === '/api/emotion-tags/') body = [{ id: 1, name: '开心', aliases: [] }];
    else if (path === '/api/emojis/characters') body = [];
    else if (path === '/api/emojis/search') body = { emojis: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/images/search') body = { images: [], total: 0, limit: 20, offset: 0 };
    await route.fulfill({ json: body });
  });
  return errors;
}
async function settled(page: Page) {
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await expect(page.locator('.section-wheel')).toHaveClass(/is-idle/);
  await expect(page.locator('.section-wheel-dialog[open]')).toHaveCount(0);
}
async function choose(page: Page, name: string) {
  await page.locator('.section-wheel-trigger').click();
  const wheel = page.getByRole('dialog', { name: /分类轮盘/ });
  await expect(wheel).toBeVisible();
  await wheel.getByRole('button', { name: `切换到${name}`, exact: true }).click();
}

test('compact section buttons unfold with a moving marquee and dock without a layout jump', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/#/gallery');
  const rail = page.locator('.section-wheel-intro');
  await expect(rail).toBeVisible();
  await expect(rail.locator('button')).toHaveText(['图片', '分组', '角色', '特征']);
  const sample = async (time: number) => rail.evaluate(async (element, milliseconds) => {
    element.getAnimations({ subtree: true }).forEach(animation => { animation.pause(); animation.currentTime = milliseconds; });
    await new Promise(requestAnimationFrame);
    const rect = (node: Element) => { const box = node.getBoundingClientRect(); return { x: box.x, width: box.width, center: box.x + box.width / 2 }; };
    return {
      overflow: document.getElementById('workspace-scroll')!.scrollWidth > document.getElementById('workspace-scroll')!.clientWidth,
      background: rect(element.querySelector('.section-wheel-intro-backdrop')!),
      first: rect(element.querySelectorAll('.section-wheel-intro-indicator')[0]!),
      second: rect(element.querySelectorAll('.section-wheel-intro-indicator')[1]!),
      target: rect(element.querySelector('button')!),
    };
  }, time);
  const early = await sample(120), unfolded = await sample(280);
  expect(unfolded.background.width).toBeGreaterThan(early.background.width + 10);
  expect(unfolded.first.x).toBeGreaterThan(early.first.x + 10);
  await page.screenshot({ path: info.outputPath('section-marquee-unfold.png') });
  const docked = await sample(650);
  expect(Math.abs(docked.second.center - docked.target.center)).toBeLessThan(1);
  const almostClosed = await sample(900);
  expect(almostClosed.background.width).toBeLessThan(108);
  expect([early, unfolded, docked, almostClosed].every(frame => !frame.overflow)).toBe(true);
  await rail.evaluate(element => element.getAnimations({ subtree: true }).forEach(animation => animation.finish()));
  await settled(page);
  const trigger = await page.locator('.section-wheel-trigger').boundingBox();
  expect(trigger!.width).toBe(96);
  expect(errors).toEqual([]);
});

test('section wheel shares the heading, switches all image pages and preserves layout', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.goto('/#/gallery');
  await settled(page);
  const top = await page.locator('.modern-gallery-toolbar').evaluate(element => element.getBoundingClientRect().top);
  await page.locator('.section-wheel-trigger').hover();
  await expect(page.locator('.section-wheel-peek-item')).toHaveCount(3);
  await expect(page.locator('.section-wheel')).toHaveClass(/is-hover/);
  expect(await page.locator('.modern-gallery-toolbar').evaluate(element => element.getBoundingClientRect().top)).toBe(top);
  const triggerBox = await page.locator('.section-wheel-trigger').boundingBox();
  const choiceBox = await page.locator('.section-wheel-peek-item').first().boundingBox();
  expect(choiceBox!.x).toBeGreaterThan(triggerBox!.x);
  expect(choiceBox!.x + choiceBox!.width).toBeLessThanOrEqual(1920);
  await expect(page.locator('.section-wheel-mark')).toHaveCount(0);
  await expect(page.locator('.section-content')).toHaveCSS('filter', 'blur(2px)');
  await page.screenshot({ path: info.outputPath('section-wheel-hover.png') });
  await page.locator('.section-wheel-peek-item').getByText('分组', { exact: true }).locator('..').click();
  await expect(page).toHaveURL(/manage\/groups/);
  await expect(page.getByRole('heading', { name: '分组管理', exact: true })).toBeVisible();
  await settled(page);
  await choose(page, '角色');
  await expect(page).toHaveURL(/manage\/characters/);
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'true');
  await settled(page);
  await choose(page, '特征');
  await expect(page).toHaveURL(/manage\/features/);
  await settled(page);
  await choose(page, '图片');
  await expect(page).toHaveURL(/gallery/);
  await settled(page);
  await page.locator('.section-wheel-trigger').click();
  await expect(page.locator('.section-wheel-dialog[open]')).toHaveAttribute('data-mode', 'open');
  await expect(page.getByRole('button', { name: '关闭切换轮盘' })).toHaveCount(0);
  await page.locator('.section-wheel-choice').first().hover();
  await page.screenshot({ path: info.outputPath('section-wheel-center.png') });
  await page.keyboard.press('Escape');
  await expect(page.locator('.section-wheel-dialog[open]')).toHaveCount(0);
  await expect(page.locator('.section-wheel-trigger')).toBeFocused();
  expect(errors).toEqual([]);
});

test('emoji reel switches categories, preserves filters and does not replay on search', async ({ page }) => {
  const errors = await fixture(page);
  await page.goto('/#/emoji?description=开心');
  await settled(page);
  await choose(page, '情绪 / 功能');
  await expect(page.getByRole('heading', { name: '情绪与功能', exact: true })).toBeVisible();
  await expect(page.locator('.modern-emoji-tags')).toBeVisible();
  await settled(page);
  await choose(page, '全部表情');
  await expect(page).toHaveURL(/description=.*开心|description=%E5%BC%80%E5%BF%83/);
  await expect(page.getByRole('button', { name: '移除备注：开心' })).toBeVisible();
  await settled(page);
  await page.getByRole('button', { name: '搜索与筛选表情包' }).click();
  await page.getByRole('textbox', { name: '搜索备注' }).fill('新条件');
  await expect(page.getByRole('button', { name: '移除备注：新条件' })).toBeVisible();
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await page.goBack();
  await expect(page.getByRole('heading', { name: '情绪与功能', exact: true })).toBeVisible();
  await settled(page);
  expect(errors).toEqual([]);
});

test('wheel can be interrupted during return, supports keyboard and reduced mobile motion', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.goto('/#/emoji');
  await settled(page);
  await choose(page, '情绪 / 功能');
  await page.locator('.section-wheel-trigger').click();
  await expect(page.locator('.section-wheel-dialog[open]')).toHaveAttribute('data-mode', 'open');
  await page.getByRole('dialog').getByRole('button', { name: '切换到全部表情', exact: true }).click();
  await settled(page);
  await expect(page.getByRole('heading', { name: '表情包库', exact: true })).toBeVisible();
  await page.locator('.section-wheel-trigger').focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.locator('.section-wheel-peek-item')).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(page.locator('.section-wheel-trigger')).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.reload();
  await settled(page);
  await page.locator('.section-wheel-trigger').click();
  await expect(page.getByRole('dialog')).toBeVisible();
  const box = await page.locator('.section-wheel-hub').boundingBox();
  expect(box!.y).toBeGreaterThan(0); expect(box!.y + box!.height).toBeLessThan(844);
  await page.screenshot({ path: info.outputPath('section-wheel-mobile.png') });
  await page.getByRole('dialog').getByRole('button', { name: '切换到情绪 / 功能', exact: true }).click();
  await settled(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  expect(errors).toEqual([]);
});
