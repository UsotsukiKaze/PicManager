import { test, expect, type Page } from '@playwright/test';

const character = { id: 1, name: '芙宁娜', group_id: 1 };
async function fixture(page: Page) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), path = url.pathname;
    if (path.startsWith('/resource/')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="500"><rect width="400" height="500" fill="#88a8dc"/><circle cx="200" cy="190" r="110" fill="#e5b7d0"/></svg>' }); return;
    }
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    const filtered = url.searchParams.get('age_rating') || url.searchParams.get('character_id') || url.searchParams.get('description') || 'initial';
    const cards = Array.from({ length: 20 }, (_, index) => ({ image_id: `${filtered}-${index}`, pid: `${filtered}-${index}`, age_rating: 'all', characters: [character], groups: [] }));
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: 'root', nickname: '动效测试' } };
    else if (path === '/api/characters/') body = [character];
    else if (path === '/api/emojis/characters') body = [{ ...character, emoji_count: 20 }];
    else if (path === '/api/groups/' || path === '/api/feature-tags/' || path === '/api/emotion-tags/') body = [];
    else if (path === '/api/images/search') body = { images: filtered === 'none' ? [] : cards, total: filtered === 'none' ? 0 : 20, offset: 0, limit: 20 };
    else if (path === '/api/emojis/search') body = { emojis: filtered === 'none' ? [] : cards.map(card => ({ emoji_id: card.image_id, file_path: `resource/${card.image_id}.png`, file_extension: 'png', characters: [character], groups: [], emotions: [] })), total: filtered === 'none' ? 0 : 20, offset: 0, limit: 20 };
    await route.fulfill({ json: body });
  });
  return errors;
}

test('age filters slide and turn old images to opaque backs before revealing new images', async ({ page }, info) => {
  const errors = await fixture(page);
  let release!: () => void;
  const response = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/images/search?*', async route => {
    if (new URL(route.request().url()).searchParams.get('age_rating') === 'r12') await response;
    await route.fallback();
  });
  await page.goto('/#/gallery');
  const grid = page.locator('.wave-results'), cards = grid.locator('.modern-image-card');
  await expect(cards).toHaveCount(20);
  const before = (await grid.boundingBox())!;
  await page.getByRole('group', { name: '年龄分级' }).getByRole('button', { name: 'R12', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'cover');
  await expect(grid).toHaveAttribute('data-wave-phase', 'blank');
  expect((await grid.boundingBox())!.height).toBeCloseTo(before.height, 1);
  await expect(cards.first().getByRole('button', { name: '查看图片 initial-0', includeHidden: true })).toHaveCount(1);
  expect(await grid.locator('.wave-turner').evaluateAll(nodes => nodes.slice(0, 5).map(node => Number((node as HTMLElement).dataset.waveDelay)))).toEqual([189, 141, 94, 47, 0]);
  const active = page.getByRole('group', { name: '年龄分级' }).getByRole('button', { name: 'R12', exact: true });
  const indicator = page.locator('.gallery-tab-indicator');
  await expect.poll(async () => Math.abs((await active.boundingBox())!.x - (await indicator.boundingBox())!.x)).toBeLessThan(1);
  await page.screenshot({ path: info.outputPath('gallery-wave-blank.png') });
  release();
  await expect(grid).toHaveAttribute('data-wave-phase', 'reveal');
  await page.waitForTimeout(250); // Capture the diagonal mid-turn, rather than its first frame.
  await page.screenshot({ path: info.outputPath('gallery-wave-reveal.png') });
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await expect(cards.first().getByRole('button', { name: '查看图片 r12-0', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('gallery-wave-complete.png') });
  await active.click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  expect(errors).toEqual([]);
});

test('rapid gallery changes interrupt the reveal and search can finish with no results', async ({ page }) => {
  const errors = await fixture(page);
  await page.goto('/#/gallery');
  const grid = page.locator('.wave-results'), ratings = page.getByRole('group', { name: '年龄分级' });
  await expect(grid.locator('.modern-image-card')).toHaveCount(20);
  await ratings.getByRole('button', { name: 'R12', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'reveal');
  await ratings.getByRole('button', { name: 'R16', exact: true }).click();
  await ratings.getByRole('button', { name: 'R18', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await expect(grid.locator('.modern-image-open').first()).toHaveAttribute('aria-label', '查看图片 r18-0');
  await ratings.getByRole('button', { name: '不限', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await page.getByRole('textbox', { name: '搜索描述' }).fill('none');
  await expect(grid).toHaveAttribute('data-wave-phase', 'cover');
  await expect(grid.locator('.modern-gallery-empty')).toBeVisible();
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await expect(grid.locator('.modern-image-card')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('emoji roles and search share the wave, including two-column mobile grids', async ({ page }, info) => {
  const errors = await fixture(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/emoji');
  const grid = page.locator('#modern-emoji-grid');
  await expect(grid.locator('.modern-emoji-card')).toHaveCount(20);
  await page.getByRole('group', { name: '按角色筛选表情包' }).getByRole('button', { name: '芙宁娜', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'reveal');
  const delays = await grid.locator('.wave-turner').evaluateAll(nodes => nodes.slice(0, 4).map(node => Number((node as HTMLElement).dataset.waveDelay)));
  expect(delays).toEqual([33, 0, 66, 33]);
  await page.screenshot({ path: info.outputPath('emoji-wave-mobile.png') });
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await expect(grid.locator('.modern-image-open').first()).toHaveAttribute('aria-label', '查看表情包 1-0 的详情');
  await page.getByRole('group', { name: '按角色筛选表情包' }).getByRole('button', { name: '不限', exact: true }).click();
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await page.getByRole('button', { name: '搜索与筛选表情包' }).click();
  await page.getByRole('textbox', { name: '搜索备注' }).fill('happy');
  await expect(grid).toHaveAttribute('data-wave-phase', 'cover');
  await expect(grid).toHaveAttribute('data-wave-phase', 'idle');
  await expect(grid.locator('.modern-image-open').first()).toHaveAttribute('aria-label', '查看表情包 happy-0 的详情');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]);
});

test('reduced motion immediately updates both pages without turning cards', async ({ page }) => {
  const errors = await fixture(page);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await page.getByRole('group', { name: '年龄分级' }).getByRole('button', { name: 'R12', exact: true }).click();
  await expect(page.locator('.modern-image-open').first()).toHaveAttribute('aria-label', '查看图片 r12-0');
  await expect(page.locator('.wave-results')).toHaveAttribute('data-wave-phase', 'idle');
  await page.goto('/#/emoji');
  await expect(page.locator('.modern-emoji-card')).toHaveCount(20);
  await page.getByRole('group', { name: '按角色筛选表情包' }).getByRole('button', { name: '芙宁娜', exact: true }).click();
  await expect(page.locator('.modern-image-open').first()).toHaveAttribute('aria-label', '查看表情包 1-0 的详情');
  await expect(page.locator('.wave-results')).toHaveAttribute('data-wave-phase', 'idle');
  expect(errors).toEqual([]);
});
