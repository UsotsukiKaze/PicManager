import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page, options: { dark?: boolean; reduced?: boolean; empty?: boolean; hold?: boolean; zero?: boolean } = {}) {
  const errors: string[] = [], requests: string[] = [], rankingQueries: string[] = [];
  let fail = false, release!: () => void, revision = 0;
  const gate = new Promise<void>(resolve => { release = resolve; });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(options => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: options.dark ? 'dark' : 'light', reduced: options.reduced || false })), options);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), path = url.pathname; requests.push(path);
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 2, role: 'root', nickname: '雾海来信' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/rankings') {
      rankingQueries.push(url.search);
      if (options.hold) await gate;
      if (fail) { await route.fulfill({ status: 400, json: { detail: '榜单暂时不可用' } }); return; }
      const names = ['星河', '雾海来信', '白昼航行', '远山', '小小收藏家', '春日记录'];
      body = {
        contribution: options.empty ? [] : names.map((nickname, index) => ({ user_id: index + 1, nickname, score: options.zero ? 0 : 3280 - index * 317 + revision, avatar_url: '/favicon.ico' })),
        characters: options.empty ? [] : names.map((_name, index) => ({ character_id: index + 11, name: ['芙宁娜', '这是一个很长的角色名字用于检查榜单在窄屏下的换行与省略行为', '初音未来', '爱丽丝', '能天使', '流萤'][index], group_name: '角色所属分组', image_count: options.zero ? 0 : 1520 - index * 190, avatar_url: '/favicon.ico' })),
        groups: options.empty ? [] : names.map((_name, index) => ({ group_id: index + 21, name: ['原神', '明日方舟', '蔚蓝档案', '东方Project', '鸣潮', '绝区零'][index], image_count: options.zero ? 0 : 8000 - index * 790, character_count: 30 - index, avatar_url: '/favicon.ico' })),
        recent_groups: [], recent_days: 30,
      };
      const group = url.searchParams.get('group_id');
      if (group && !options.empty) (body as { characters: unknown[] }).characters = [{ character_id: group === '21' ? 91 : 92, name: group === '21' ? '分组内专属角色' : '能天使', group_name: group === '21' ? '原神' : '明日方舟', image_count: 1800, avatar_url: '/favicon.ico' }];
    } else if (path === '/api/groups/') body = [{ id: 21, name: '原神' }, { id: 22, name: '明日方舟' }];
    else if (/\/api\/(characters|feature-tags|emotion-tags)\/$/.test(path) || path === '/api/groups/popular') body = [];
    else if (path === '/api/images/search') body = { images: [], total: 0, offset: 0, limit: 20 };
    await route.fulfill({ json: body });
  });
  return { errors, requests, rankingQueries, release, fail(value: boolean) { fail = value; }, revise() { revision += 5; } };
}

async function chooseBoard(page: Page, name: string) {
  await expect(page.locator('.section-wheel')).toHaveClass('section-wheel is-idle');
  await page.locator('.section-wheel-trigger').click();
  await page.getByRole('dialog', { name: '榜单分类轮盘', exact: true }).getByRole('button', { name: `切换到${name}`, exact: true }).click();
}

test('native rankings share one request, preserve board history and link to the matching gallery', async ({ page }, info) => {
  const mock = await fixture(page);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto('/#/rankings');
  await expect(page.getByRole('heading', { name: '榜上有名', exact: true })).toBeVisible();
  await expect(page.locator('.rank-leader')).toHaveCount(3);
  await expect(page.locator('.rank-row')).toHaveCount(3);
  await expect(page.locator('.rank-you')).toHaveText('你');
  await expect(page.locator('.rank-leader').first()).toContainText('3,280');
  await expect(page.locator('.rank-row .rank-position')).toHaveText(['04', '05', '06']);
  expect(mock.requests.filter(path => path === '/static/index.html' || path === '/static/js/ui.js')).toEqual([]);
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await page.screenshot({ path: info.outputPath('rankings-desktop-light.png') });
  await chooseBoard(page, '角色榜');
  await expect(page.getByRole('region', { name: '角色榜', exact: true })).toBeVisible();
  await expect(page.locator('.rank-leader').first()).toContainText('1,520');
  await chooseBoard(page, '分组榜');
  await expect(page.getByRole('region', { name: '分组榜', exact: true })).toBeVisible();
  expect(mock.requests.filter(path => path === '/api/rankings')).toHaveLength(1);
  await page.goBack();
  await expect(page.locator('.section-wheel-trigger')).toContainText('角色榜');
  await expect(page.getByRole('region', { name: '角色榜', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '浏览芙宁娜的图片', exact: true }).click();
  await expect(page).toHaveURL(/character_id=11/);
  await page.goBack();
  await expect(page.locator('.section-wheel-trigger')).toContainText('角色榜');
  expect(mock.errors).toEqual([]);
});

test('refresh retains the board on failure and updates scores on successful retry', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/rankings'); await expect(page.locator('.rank-leader')).toHaveCount(3);
  mock.fail(true); await page.getByRole('button', { name: '刷新榜单', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('保留当前榜单');
  await expect(page.locator('.rank-leader')).toHaveCount(3);
  await expect(page.locator('.rank-leader').first()).toContainText('3,280');
  mock.fail(false); mock.revise(); await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('.rank-feedback')).toHaveText('榜单已更新');
  await expect(page.locator('.rank-leader').first()).toContainText('3,285');
  expect(mock.errors).toEqual([]);
});

test('loading transitions to an honest empty board with a working upload entry', async ({ page }) => {
  const mock = await fixture(page, { hold: true, empty: true });
  await page.goto('/#/rankings');
  await expect(page.getByRole('status', { name: '正在读取榜单' })).toBeVisible();
  await expect(page.locator('.rank-leader')).toHaveCount(0);
  mock.release();
  await expect(page.getByRole('heading', { name: '还没有贡献记录', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '上传资源', exact: true }).last()).toHaveAttribute('href', '#/upload');
  await chooseBoard(page, '分组榜');
  await expect(page.getByRole('heading', { name: '还没有分组记录', exact: true })).toBeVisible();
  expect(mock.errors).toEqual([]);
});

test('an initial failure shows retry rather than an empty ranking', async ({ page }) => {
  const mock = await fixture(page); mock.fail(true);
  await page.goto('/#/rankings');
  await expect(page.getByRole('heading', { name: '榜单暂时无法加载', exact: true })).toBeVisible();
  await expect(page.locator('.rank-leader')).toHaveCount(0);
  mock.fail(false); await page.getByRole('button', { name: '重新加载', exact: true }).click();
  await expect(page.locator('.rank-leader')).toHaveCount(3);
  expect(mock.errors).toEqual([]);
});

test('mobile dark board fits long names and zero values while reduced motion keeps keyboard navigation', async ({ page }, info) => {
  const mock = await fixture(page, { dark: true, reduced: true, zero: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/rankings?board=characters');
  await expect(page.locator('.rank-leader')).toHaveCount(3);
  await expect(page.locator('.rank-leader-score .rank-value')).toHaveText(['0', '0', '0']);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  expect(await page.locator('.rankings-workspace').evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0);
  await page.screenshot({ path: info.outputPath('rankings-mobile-dark.png') });
  await page.locator('.section-wheel-trigger').focus(); await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog', { name: '榜单分类轮盘', exact: true });
  await dialog.getByRole('button', { name: '切换到分组榜', exact: true }).focus(); await page.keyboard.press('Enter');
  await expect(page.getByRole('region', { name: '分组榜', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await page.setViewportSize({ width: 320, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  const account = await page.getByRole('navigation', { name: '账户', exact: true }).boundingBox();
  expect(account!.x + account!.width).toBeLessThanOrEqual(320);
  expect(mock.errors).toEqual([]);
});

test('rankings entry precedes appearance and the wheel animates all three boards with the title', async ({ page }, info) => {
  const mock = await fixture(page);
  await page.goto('/#/gallery');
  const entry = page.getByRole('navigation', { name: '账户', exact: true }).getByRole('link', { name: '榜上有名', exact: true });
  expect(await entry.evaluate(element => Boolean(element.compareDocumentPosition(document.querySelector('.modern-appearance')!) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await entry.click(); await expect(entry).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('.section-wheel-intro button')).toHaveText(['贡献榜', '角色榜', '分组榜']);
  await chooseBoard(page, '角色榜');
  await expect(page.getByRole('heading', { name: '角色榜', exact: true })).toBeVisible();
  await expect(page.locator('.section-wheel')).toHaveClass('section-wheel is-idle');
  await page.locator('.section-wheel-trigger').hover();
  await expect(page.locator('.section-wheel')).toHaveClass(/is-hover/);
  await expect(page.locator('.section-wheel-peek').getByRole('button', { name: '切换到分组榜', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('rankings-wheel-peek.png') });
  await page.locator('.section-wheel-peek').getByRole('button', { name: '切换到分组榜', exact: true }).click();
  await expect(page.getByRole('region', { name: '分组榜', exact: true })).toBeVisible();
  expect(mock.requests.filter(path => path === '/api/rankings')).toHaveLength(1);
  expect(mock.errors).toEqual([]);
});

test('character rankings restore searchable group filtering, server ranking and history', async ({ page }, info) => {
  const mock = await fixture(page);
  await page.goto('/#/rankings?board=characters&group_id=21');
  const picker = page.getByRole('combobox', { name: '搜索分组', exact: true });
  await expect(picker).toHaveValue('原神');
  await expect(page.locator('.rank-leader')).toHaveCount(1);
  await expect(page.locator('.rank-leader')).toContainText('分组内专属角色');
  expect(mock.rankingQueries.some(query => new URLSearchParams(query).get('group_id') === '21')).toBe(true);
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
  await picker.fill('明日'); await page.getByRole('option', { name: '明日方舟', exact: true }).click();
  await expect(page).toHaveURL(/group_id=22/);
  await expect(page.locator('.rank-leader')).toContainText('能天使');
  await page.getByRole('button', { name: '清除分组', exact: true }).click();
  await expect(page.locator('.rank-leader')).toHaveCount(3);
  await page.goBack();
  await expect(picker).toHaveValue('明日方舟');
  await expect(page.locator('.rank-leader')).toContainText('能天使');
  const before = (await page.locator('.rank-podium').boundingBox())!.height;
  await page.locator('.rank-leader').hover();
  await expect.poll(() => page.locator('.rank-leader-line').evaluate(element => getComputedStyle(element).opacity)).toBe('1');
  expect((await page.locator('.rank-podium').boundingBox())!.height).toBeCloseTo(before, 1);
  await page.screenshot({ path: info.outputPath('rankings-character-hover.png') });
  await chooseBoard(page, '分组榜');
  await expect(page.getByRole('region', { name: '分组榜', exact: true })).toBeVisible();
  await expect(picker).toHaveCount(0);
  await chooseBoard(page, '角色榜');
  await expect(picker).toHaveValue('明日方舟');
  await expect(page.getByRole('region', { name: '角色榜', exact: true })).toBeVisible();
  await expect(page.locator('.rank-leader')).toHaveCount(1);
  await expect(page.locator('.rank-leader')).toContainText('能天使');
  expect(mock.errors).toEqual([]);
});
