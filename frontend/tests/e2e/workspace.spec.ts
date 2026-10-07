import { test, expect, type Page } from '@playwright/test';

async function mockWorkspace(page: Page, role = 'root', firstRating = 'r12') {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const groups = [{ id: 1, name: '原神', aliases: ['Genshin'], description: '', avatar_url: '/favicon.ico' }, { id: 2, name: '崩坏星穹铁道', aliases: [], description: '' }];
  const characters = [{ id: 1, name: '芙宁娜', group_id: 1, group_name: '原神', nicknames: ['水神'], feature_tags: [], feature_tag_ids: [] }];
  const cards = Array.from({ length: 41 }, (_, index) => ({ image_id: String(index + 1).padStart(10, 'A'), pid: `${10000 + index}_p0`, age_rating: index < 2 ? firstRating : 'r12', width: 800, height: 1000, characters, groups: [groups[0]] }));
  let description = '测试描述';
  const requested: string[] = [];
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    requested.push(path);
    if (!url.hostname.startsWith('127.')) { await route.abort(); return; }
    if (path.startsWith('/resource/')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1000"><defs><linearGradient id="g"><stop stop-color="#8aa9db"/><stop offset="1" stop-color="#d6c2df"/></linearGradient></defs><rect width="800" height="1000" fill="url(#g)"/><circle cx="400" cy="400" r="180" fill="#fff" opacity=".4"/></svg>' }); return;
    }
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown;
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role, nickname: '测试用户', avatar_url: '/favicon.ico' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/system/status') body = { total_images: 41, total_groups: 2, total_characters: 1, total_emojis: 0, temp_count: 0, store_count: 41 };
    else if (path === '/api/groups/popular') body = groups;
    else if (path === '/api/rankings') body = { contribution: [], recent_groups: [], recent_days: 30 };
    else if (path === '/api/groups/') body = groups;
    else if (path === '/api/characters/') body = characters;
    else if (path === '/api/feature-tags/') body = [{ id: 1, name: '蓝色', aliases: [] }];
    else if (path === '/api/images/search') {
      // Deliberately return old search later to exercise cancellation/latest result handling.
      if (url.searchParams.get('description') === '旧请求') await new Promise(resolve => setTimeout(resolve, 700));
      const rows = url.searchParams.get('description') === '新请求' ? cards.slice(0, 1) : cards;
      const offset = Number(url.searchParams.get('offset') || 0);
      body = { images: rows.slice(offset, offset + 20), total: rows.length, offset, limit: 20 };
    } else if (path.startsWith('/api/images/')) {
      const id = path.split('/')[3];
      if (route.request().method() === 'PUT') { description = route.request().postDataJSON().description; body = { status: 'success', message: '保存成功' }; }
      else body = { ...cards.find(row => row.image_id === id), description, file_extension: 'jpg', pixiv_tags: [{ name: '芙宁娜' }], feature_tags: [], local_verified: true, pixiv_verified: true };
    } else if (path === '/api/upload/temp-count') body = { count: 0 };
    else if (path === '/api/upload/temp-images') body = [];
    else if (path === '/api/pixiv-ol/tag-mappings') body = [];
    else if (path === '/api/pixiv-ol/account') body = { connected: false };
    else if (path === '/api/pixiv-ol/cart') body = { items: [] };
    else if (path === '/api/pixiv-ol/preferences') body = { groups: [], alpha: .5, ai: 'allow', include_r18: false, include_r18g: false };
    else if (path === '/api/pixiv-ol/account/login/pending') body = null;
    else if (path === '/api/pixiv-ol/jobs') body = [];
    else if (path === '/api/pixiv-ol/recommendations' || path === '/api/pixiv-ol/feed') body = { items: [], total: 0, has_more: false };
    else body = {};
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  return { errors, requested };
}

test('homepage is native and does not download legacy controllers or phonetic dictionary', async ({ page }) => {
  const { requested, errors } = await mockWorkspace(page);
  await page.goto('/');
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await expect(page.locator('.home-metric-card strong').first()).toHaveText('41');
  expect(requested.some(path => /\/static\/js\/(ui|auth|upload|pixiv-ol)\.js/.test(path))).toBe(false);
  expect(requested.some(path => /\/static\/vendor\/pinyin-pro/.test(path))).toBe(false);
  await page.getByRole('button', { name: '收起侧栏' }).click();
  await expect(page.locator('html')).toHaveClass(/sidebar-collapsed/);
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/sidebar-collapsed/);
  expect(errors).toEqual([]);
});

test('gallery cancels obsolete searches, retains filters and supports browser history', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  expect(await page.locator('.modern-image-grid').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(5);
  const search = page.getByRole('textbox', { name: '搜索描述' });
  await search.fill('旧请求');
  await page.waitForRequest(request => request.url().includes('description=%E6%97%A7'));
  await search.fill('新请求');
  await expect(page.locator('.modern-image-card')).toHaveCount(1);
  await page.waitForTimeout(800);
  await expect(page.locator('.modern-image-card')).toHaveCount(1);
  await search.fill('');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await page.getByRole('combobox', { name: '搜索角色' }).fill('水神');
  await page.getByRole('option', { name: '芙宁娜' }).click();
  await expect(page).toHaveURL(/character_id=1/);
  await page.getByRole('navigation', { name: '图库页码' }).getByRole('button', { name: '2', exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await page.goBack();
  await expect(page.locator('.modern-pagination span')).toHaveText('2 / 3');
  await expect(page.getByRole('combobox', { name: '搜索角色' })).toHaveAttribute('placeholder', '芙宁娜');
  await page.locator('#workspace-scroll').evaluate(node => { node.scrollTop = 450; });
  const before = await page.locator('#workspace-scroll').evaluate(node => node.scrollTop);
  expect(before).toBeGreaterThan(100);
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await page.goBack();
  await expect.poll(() => page.locator('#workspace-scroll').evaluate(node => node.scrollTop)).toBe(before);
  expect(errors).toEqual([]);
});

test('detail uses independent cards, closes cleanly and falls back to original', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.route('**/resource/previews/**', route => route.fulfill({ status: 404 }));
  await page.goto('/#/gallery');
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '图片详情' });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.modern-reader-preview')).toHaveAttribute('src', /originals/);
  await expect(dialog.locator('.modern-reader-preview')).toHaveClass(/loaded/);
  await expect.poll(() => dialog.locator('.modern-reader-preview').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('detail.png') });
  await expect(dialog.getByText('本地已校验')).toBeVisible();
  await expect.poll(() => dialog.evaluate(node => Math.abs(node.querySelector('.modern-reader-media')!.getBoundingClientRect().top - node.querySelector('.modern-reader-info')!.getBoundingClientRect().top))).toBeLessThan(3);
  await expect.poll(() => dialog.locator('.modern-reader-media').evaluate(node => Math.abs((node.getBoundingClientRect().left + node.getBoundingClientRect().right) / 2 - innerWidth / 2))).toBeLessThan(3);
  await page.keyboard.press('ArrowRight');
  await expect(dialog.locator('h2')).toHaveText('10001_p0');
  await page.getByRole('button', { name: '关闭详情' }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.modern-image-card').first()).toHaveClass(/suppress-actions/);
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('legacy tag editor saves into the shared cache and feature routes remain usable', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await page.getByRole('button', { name: '编辑标签', exact: true }).click();
  await expect(page.locator('#edit-image-form')).toBeVisible();
  await page.locator('#edit-image-description').fill('响应式缓存已更新');
  await page.locator('#edit-image-form').getByRole('button', { name: '保存' }).click();
  await expect(page.locator('#edit-image-form')).not.toBeVisible();
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await expect(page.getByText('响应式缓存已更新', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: '分组', exact: true }).click();
  await expect(page.locator('#group-list')).toContainText('原神');
  await page.getByRole('link', { name: '上传资源', exact: true }).click();
  await expect(page.locator('#page-upload')).toBeVisible();
  await expect(page.locator('#page-upload')).not.toHaveAttribute('inert');
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await expect(page.locator('#pixiv-content')).toBeVisible();
  await expect(page.locator('#page-pixiv-ol')).not.toHaveAttribute('inert');
  expect(errors).toEqual([]);
});

test('mobile layout fits viewport and normal users cannot activate Pixiv routes', async ({ page }) => {
  const { errors } = await mockWorkspace(page, 'user');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.goto('/#/pixiv');
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  expect(errors).toEqual([]);
});

test('native phonetic search and legacy editors reuse one local dictionary', async ({ page }) => {
  const { requested, errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  expect(requested.some(path => path.includes('/pinyin-pro-'))).toBe(false);
  await page.getByRole('combobox', { name: '搜索角色' }).fill('fnn');
  await page.getByRole('option', { name: '芙宁娜' }).click();
  await expect(page).toHaveURL(/character_id=1/);
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await page.getByRole('button', { name: '编辑标签', exact: true }).click();
  await expect(page.locator('#edit-image-form')).toBeVisible();
  expect(requested.filter(path => path.includes('/pinyin-pro-'))).toHaveLength(1);
  expect(errors).toEqual([]);
});

test('profile retains nickname and admin tools after removal of obsolete password flows', async ({ page }) => {
  const { requested, errors } = await mockWorkspace(page);
  await page.route('**/auth/set-nickname', async route => {
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ message: '保存成功', user: { nickname: route.request().postDataJSON().nickname } }) });
  });
  await page.goto('/static/profile.html?embedded=1');
  await expect(page.locator('#user-nickname')).toHaveText('测试用户');
  await expect(page.locator('#admin-tab')).toBeVisible();
  await expect(page.locator('#root-tab')).toBeVisible();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.locator('#edit-nickname-btn').click();
  await page.locator('#new-nickname-input').fill('新的昵称');
  await page.locator('#edit-nickname-form').getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.locator('#user-nickname')).toHaveText('新的昵称');
  await expect(page.locator('#edit-nickname-form')).not.toBeVisible();
  expect(requested.some(path => path === '/auth/password' || path === '/auth/login')).toBe(false);
  expect(errors).toEqual([]);
});

test('restricted detail does not request media until revealed, including missing-preview placeholders', async ({ page }) => {
  const { errors, requested } = await mockWorkspace(page, 'root', 'r18');
  await page.route('**/resource/previews/**', route => route.fulfill({ status: 200, headers: { 'X-PicManager-Preview': 'missing' }, contentType: 'image/png', body: '' }));
  await page.goto('/#/gallery');
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).press('Enter');
  const dialog = page.getByRole('dialog', { name: '图片详情' });
  await expect(dialog).toBeVisible();
  expect(requested.some(path => path.startsWith('/resource/') && path.includes('AAAAAAAAA1'))).toBe(false);
  await dialog.getByRole('button', { name: '显示 R18 图片' }).click();
  await expect(dialog.locator('.modern-reader-preview')).toHaveAttribute('src', /originals/);
  await expect(dialog.locator('.modern-reader-preview')).toHaveClass(/loaded/);
  await page.keyboard.press('ArrowRight');
  await expect(dialog.locator('h2')).toHaveText('10001_p0');
  await expect(dialog.getByRole('button', { name: '显示 R18 图片' })).toBeVisible();
  expect(requested.some(path => path.startsWith('/resource/') && path.includes('AAAAAAAAA2'))).toBe(false);
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  expect(errors).toEqual([]);
});
