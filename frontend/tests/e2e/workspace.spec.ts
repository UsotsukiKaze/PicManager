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
    else if (path === '/api/groups/popular') body = [...groups, { id: 3, name: '明日方舟' }, { id: 4, name: '东方Project' }, { id: 5, name: '蔚蓝档案' }, { id: 6, name: '碧蓝航线' }, { id: 7, name: '鸣潮' }, { id: 8, name: '绝区零' }].map((group, index) => ({ ...group, image_count: 41 - index * 5 }));
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
      else body = { ...cards.find(row => row.image_id === id), description, file_extension: 'jpg', pixiv_tags: [{ name: '芙宁娜' }], feature_tags: [{ id: 1, name: '蓝色' }], local_verified: true, pixiv_verified: true };
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

test('Pixiv switches three independent recommendation modes and restores each reading state', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  const modes: string[] = [];
  await page.route('**/api/pixiv-ol/**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/account')) {
      await route.fulfill({ json: { connected: true, user_id: '7', name: '测试画友', media_revision: 'test' } });
    } else if (url.pathname.endsWith('/recommendations')) {
      const mode = url.searchParams.get('mode')!;
      modes.push(mode);
      const offset = Number(url.searchParams.get('offset') || 0);
      await route.fulfill({ json: { batch_id: `${mode}-batch`, total: 40, next_offset: offset + 20, has_more: offset < 20,
        items: Array.from({ length: 20 }, (_, n) => ({ pid: String(1000 + offset + n), title: `${mode}作品${n}`, author: '测试画师', author_id: '9',
          page_count: 1, preview_url: '/static/icon/Pic.png', author_avatar_url: '/static/icon/Pic.png', imported_pages: [] })) } });
    } else if (url.pathname.endsWith('/similarity')) {
      await route.fulfill({ json: { items: [] } });
    } else {
      await route.fallback();
    }
  });
  await page.goto('/#/pixiv');
  const selector = page.getByRole('combobox', { name: '推荐方式' });
  await expect(selector).toHaveValue('personal');
  await expect(selector.locator('option')).toHaveText(['猜你喜欢', '进货模式', 'Pixiv 发现']);
  await expect(page.locator('.px-card')).toHaveCount(20);
  await selector.selectOption('stock');
  await expect(page.locator('.px-card')).toHaveCount(20);
  await expect(page.locator('.px-gallery')).toContainText('stock作品');
  await selector.selectOption('discovery');
  await expect(page.locator('.px-gallery')).toContainText('discovery作品');
  await selector.selectOption('personal');
  await expect(page.locator('.px-gallery')).toContainText('personal作品');
  expect(modes).toEqual(['personal', 'stock', 'discovery']);
  expect(errors).toEqual([]);
});

test('homepage is native and does not download legacy controllers or phonetic dictionary', async ({ page }) => {
  const { requested, errors } = await mockWorkspace(page);
  await page.goto('/');
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await expect(page.locator('.modern-brand img')).toHaveAttribute('src', '/static/icon/Pic.png');
  await expect.poll(() => page.locator('.modern-brand img').evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(256);
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/static/icon/Pic.png');
  await expect(page.getByRole('link', { name: 'Pixiv-ol', exact: true }).locator('img')).toHaveAttribute('src', '/static/icon/pixiv-ol.svg');
  await expect.poll(() => page.locator('.modern-pixiv-nav-icon').evaluate(node => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  expect((await page.locator('.modern-pixiv-nav-icon').boundingBox())!.width).toBe(24);
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
  await page.getByRole('button', { name: '打开图片查询' }).click();
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
  await expect.poll(() => page.locator('#modal-overlay').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('tag-editor.png') });
  await page.locator('#edit-image-description').fill('响应式缓存已更新');
  await page.locator('#edit-image-form').getByRole('button', { name: '保存' }).click();
  await expect(page.locator('#edit-image-form')).not.toBeVisible();
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await expect(page.getByText('响应式缓存已更新', { exact: true })).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: '分组', exact: true }).click();
  await expect(page.locator('#group-list')).toContainText('原神');
  await expect.poll(() => page.locator('#page-management').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('groups.png') });
  await page.getByRole('link', { name: '上传资源', exact: true }).click();
  await expect(page.locator('#page-upload')).toBeVisible();
  await expect(page.locator('#page-upload')).not.toHaveAttribute('inert');
  await expect(page.locator('#upload-queue-dock')).not.toBeVisible();
  await expect.poll(() => page.locator('#page-upload').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('upload.png') });
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await expect(page.locator('#pixiv-content')).toBeVisible();
  await expect(page.locator('#page-pixiv-ol')).not.toHaveAttribute('inert');
  await page.screenshot({ path: test.info().outputPath('pixiv.png') });
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
  await page.getByRole('button', { name: '打开图片查询' }).click();
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

for (const rating of ['r16', 'r18']) {
  test(`restricted ${rating} uses acrylic thumbnails and delays full media until revealed`, async ({ page }) => {
    const { errors, requested } = await mockWorkspace(page, 'root', rating);
    const expectedFilter = rating === 'r18' ? 'blur(36px) brightness(0.42)' : 'blur(24px)';
    await page.route('**/resource/previews/**', route => route.fulfill({ status: 200, headers: { 'X-PicManager-Preview': 'missing' }, contentType: 'image/png', body: '' }));
    await page.goto('/#/gallery');
    const card = page.locator('.modern-image-card').first();
    await expect(card.locator('.modern-image-open img')).toHaveAttribute('src', '/resource/thumbs/AAAAAAAAA1.webp');
    await expect.poll(() => card.locator('.modern-image-open img').evaluate(node => getComputedStyle(node).filter)).toBe(expectedFilter);
    expect(await card.locator('.modern-card-footer').evaluate(node => getComputedStyle(node).backgroundColor)).toContain('0.62');
    await expect.poll(() => page.locator('.modern-gallery').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
    await page.screenshot({ path: test.info().outputPath(`acrylic-${rating}-cards.png`) });
    await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).press('Enter');
    const dialog = page.getByRole('dialog', { name: '图片详情' });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator('.modern-reader-thumb')).toHaveAttribute('src', '/resource/thumbs/AAAAAAAAA1.webp');
    await expect.poll(() => dialog.locator('.modern-reader-thumb').evaluate(node => getComputedStyle(node).filter)).toBe(expectedFilter);
    expect(requested.some(path => /\/resource\/(previews|originals)\//.test(path) && path.includes('AAAAAAAAA1'))).toBe(false);
    await dialog.getByRole('button', { name: `显示 ${rating.toUpperCase()} 图片` }).click();
    await expect(dialog.locator('.modern-reader-preview')).toHaveAttribute('src', /originals/);
    await expect(dialog.locator('.modern-reader-preview')).toHaveClass(/loaded/);
    await page.keyboard.press('ArrowRight');
    await expect(dialog.locator('h2')).toHaveText('10001_p0');
    await expect(dialog.getByRole('button', { name: `显示 ${rating.toUpperCase()} 图片` })).toBeVisible();
    expect(requested.some(path => /\/resource\/(previews|originals)\//.test(path) && path.includes('AAAAAAAAA2'))).toBe(false);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await card.getByRole('button', { name: `${rating.toUpperCase()} · 点击显示` }).click();
    await expect.poll(() => card.locator('.modern-image-open img').evaluate(node => getComputedStyle(node).filter)).toBe('none');
    expect(errors).toEqual([]);
  });
}

test('sidebar remains owned by Vue after loading legacy tools and toggle stays on the divider', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  await page.getByRole('link', { name: '分组', exact: true }).click();
  await expect(page.locator('#group-list')).toContainText('原神');
  await page.evaluate(() => (window as unknown as { PicManagerShell: { init(): void } }).PicManagerShell.init());
  const button = page.locator('#sidebar-toggle');
  const footer = page.locator('.modern-sidebar .sidebar-footer');
  const expanded = await button.boundingBox();
  const divider = await footer.boundingBox();
  expect(expanded!.width).toBe(32);
  expect(Math.abs(expanded!.y + expanded!.height / 2 - divider!.y)).toBeLessThan(2);
  await button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'false');
  await expect.poll(() => page.locator('#workspace-sidebar').evaluate(node => Math.round(node.getBoundingClientRect().width))).toBe(76);
  expect((await button.boundingBox())!.width).toBe(32);
  await button.click();
  await expect(button).toHaveAttribute('aria-expanded', 'true');
  await expect.poll(() => page.locator('#workspace-sidebar').evaluate(node => Math.round(node.getBoundingClientRect().width))).toBe(220);
  await page.reload();
  await expect(page.locator('#sidebar-toggle')).toHaveAttribute('aria-expanded', 'true');
  expect(errors).toEqual([]);
});

test('wide screens keep home and five-column gallery bounded instead of stretching cards', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.route('**/api/rankings?*', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ contribution: ['拈风', '星河', '收藏家', '春日', '小爱'].map((nickname, index) => ({ nickname, count: [1280, 640, 318, 156, 72][index] })), recent_groups: ['原神', '崩坏星穹铁道', '明日方舟', '蔚蓝档案', '东方Project'].map((name, index) => ({ name, count: [42, 26, 18, 12, 7][index] })), recent_days: 30 }) }));
  await page.setViewportSize({ width: 2560, height: 1440 });
  await page.goto('/');
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  expect((await page.locator('.modern-home').boundingBox())!.width).toBeLessThanOrEqual(1120);
  await expect.poll(() => page.locator('.modern-home').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('home-wide.png') });
  await page.getByRole('link', { name: '图片管理', exact: true }).click();
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  expect((await page.locator('.modern-gallery').boundingBox())!.width).toBeLessThanOrEqual(1240);
  expect(await page.locator('.modern-image-grid').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length)).toBe(5);
  expect((await page.locator('.modern-image-card').first().boundingBox())!.height).toBeCloseTo(300, 2);
  await expect.poll(() => page.locator('.modern-gallery').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('gallery-wide.png') });
  await page.locator('.modern-image-card').first().hover();
  await expect.poll(() => page.locator('.modern-card-actions').first().evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('gallery-hover.png') });
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await page.getByRole('combobox', { name: '搜索分组' }).fill('原神');
  await page.getByRole('option', { name: '原神', exact: true }).click();
  await page.getByRole('button', { name: /清除筛选/ }).click();
  await expect(page).not.toHaveURL(/group_id=/);
  expect(errors).toEqual([]);
});

test('embedded profile shares workspace surfaces and keeps sidebar user selection specific', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/');
  await expect(page.locator('.sidebar-user')).not.toHaveAttribute('aria-current');
  await expect(page.locator('.sidebar-user #header-role')).toHaveClass(/role-root/);
  await expect(page.locator('.sidebar-user #header-role')).toHaveText('Root');
  expect((await page.locator('.sidebar-user #header-avatar').boundingBox())!.width).toBe(40);
  expect(await page.locator('.sidebar-user').evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgba(0, 0, 0, 0)');
  expect(await page.locator('.sidebar-user #header-role').evaluate(node => getComputedStyle(node).backgroundImage)).toContain('linear-gradient');
  await page.locator('.sidebar-user').click();
  await expect(page.locator('.sidebar-user')).toHaveAttribute('aria-current', 'page');
  const account = page.frameLocator('#profile-frame');
  await expect(account.locator('#user-nickname')).toHaveText('测试用户');
  await expect(page.locator('.modern-profile').getByRole('heading', { name: '我的', exact: true })).toBeVisible();
  const surface = await account.locator('.user-card').evaluate(node => ({ radius: getComputedStyle(node).borderRadius, background: getComputedStyle(node).backgroundColor }));
  expect(surface).toEqual({ radius: '16px', background: 'rgb(255, 255, 255)' });
  expect((await page.locator('#page-profile').boundingBox())!.width).toBeLessThanOrEqual(1120);
  await account.locator('#edit-nickname-btn').click();
  await expect(account.locator('#new-nickname-input')).toBeVisible();
  await expect.poll(() => page.locator('.modern-profile').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('profile.png') });
  await page.getByRole('link', { name: '图片管理', exact: true }).click();
  await expect(page.locator('.sidebar-user')).not.toHaveAttribute('aria-current');
  expect(errors).toEqual([]);
});

test('tablet breakpoint fits viewport and reduced motion keeps detail usable', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(768);
  await expect(page.locator('#sidebar-toggle')).not.toBeVisible();
  expect(await page.locator('.modern-image-card').first().evaluate(node => getComputedStyle(node).animationName)).toBe('none');
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '图片详情' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: '图片详情' })).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('tablet.png') });
  expect(errors).toEqual([]);
});

test('restored homepage group orbit opens the gallery filter and keeps the original mobile layout', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/');
  const orbit = page.getByRole('complementary', { name: '分组云图' });
  await expect(orbit.locator('.orbit-chip')).toHaveCount(5);
  await expect(orbit).toBeVisible();
  await expect(orbit.locator('.orbit-chip').first()).toHaveAttribute('title', '原神 · 41 张');
  await expect.poll(() => orbit.locator('.home-orbit-core img').evaluate(node => (node as HTMLImageElement).naturalWidth)).toBe(256);
  expect(await orbit.locator('.orbit-chip-label').evaluateAll(nodes => nodes.every(node => getComputedStyle(node).whiteSpace === 'nowrap'))).toBe(true);
  await orbit.getByRole('link', { name: /原神/ }).focus();
  await orbit.getByRole('link', { name: /原神/ }).press('Enter');
  await expect(page).toHaveURL(/group_id=1/);
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await expect(page.locator('#gallery-query-toggle b')).toHaveText('1');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await expect(orbit).not.toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect.poll(() => page.locator('.modern-home').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
  await page.screenshot({ path: test.info().outputPath('home-restored-mobile.png') });
  expect(errors).toEqual([]);
});

test('collapsed search preserves active conditions and Escape returns focus to its button', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  const panel = page.locator('#gallery-search-panel');
  await expect(panel).not.toBeVisible();
  await expect(panel).toHaveAttribute('inert');
  await page.getByRole('group', { name: '年龄分级' }).getByRole('button', { name: 'R12', exact: true }).click();
  await expect(page).toHaveURL(/age_rating=r12/);
  await expect(page.locator('#gallery-query-toggle b')).toHaveCount(0);
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await page.getByRole('textbox', { name: '搜索描述' }).fill('新请求');
  await expect(page.locator('.modern-image-card')).toHaveCount(1);
  await page.getByRole('textbox', { name: '搜索描述' }).press('Escape');
  await expect(panel).not.toBeVisible();
  await expect(page.locator('#gallery-query-toggle')).toBeFocused();
  await expect(page.locator('#gallery-query-toggle b')).toHaveText('1');
  await page.reload();
  await expect(panel).not.toBeVisible();
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await expect(page.getByRole('textbox', { name: '搜索描述' })).toHaveValue('新请求');
  expect(errors).toEqual([]);
});

test('library detail restores colored tag bubbles and compact edit download delete actions', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery');
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '图片详情' });
  await expect(dialog.locator('.pm-tag-character')).toContainText('芙宁娜');
  await expect(dialog.locator('.pm-tag-feature_tag')).toHaveText('蓝色');
  const tagColors = await dialog.locator('.modern-detail-tags .pm-tag').evaluateAll(nodes => nodes.map(node => ({ color: getComputedStyle(node).backgroundColor, radius: getComputedStyle(node).borderRadius })));
  expect(new Set(tagColors.map(tag => tag.color)).size).toBe(3);
  expect(tagColors.every(tag => tag.radius === '999px')).toBe(true);
  const actions = dialog.locator('.modern-detail-actions');
  await expect(actions).toContainText('编辑标签');
  await expect(actions.getByRole('link', { name: '下载原图' })).toHaveText('');
  await expect(actions.getByRole('link', { name: '下载原图' })).toHaveAttribute('href', '/api/images/AAAAAAAAA1/download');
  await expect(actions.getByRole('button', { name: '删除图片' })).toHaveText('');
  const deletions: string[] = [];
  page.on('request', request => { if (request.method() === 'DELETE') deletions.push(request.url()); });
  page.once('dialog', async confirmation => {
    expect(confirmation.type()).toBe('confirm');
    expect(confirmation.message()).toContain('10000_p0');
    await confirmation.dismiss();
  });
  await actions.getByRole('button', { name: '删除图片' }).click();
  await expect(dialog).toBeVisible();
  expect(deletions).toEqual([]);
  await dialog.locator('.pm-tag-feature_tag').click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/feature_tag_id=1/);
  expect(errors).toEqual([]);
});

for (const role of ['root', 'user']) {
  test(`library deletion popup confirms before submitting for ${role}`, async ({ page }) => {
    await mockWorkspace(page, role);
    let deletions = 0;
    await page.route('**/api/images/AAAAAAAAA1', async route => {
      if (route.request().method() !== 'DELETE') { await route.fallback(); return; }
      deletions++;
      await route.fulfill({ json: { status: role === 'root' ? 'success' : 'pending', message: '完成' } });
    });
    await page.goto('/#/gallery');
    await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '图片详情' });
    const button = dialog.getByRole('button', { name: role === 'root' ? '删除图片' : '请求删除图片', exact: true });
    page.once('dialog', async confirmation => { await confirmation.dismiss(); });
    await button.click();
    await expect(dialog).toBeVisible();
    expect(deletions).toBe(0);
    page.once('dialog', async confirmation => {
      expect(confirmation.type()).toBe('confirm');
      expect(confirmation.message()).toContain(role === 'root' ? '无法恢复' : '删除申请');
      await confirmation.accept();
    });
    await button.click();
    await expect(dialog).toHaveCount(0);
    expect(deletions).toBe(1);
  });
}

test('bottom original-image island switches quality once and resets on the next image', async ({ page }) => {
  const { errors, requested } = await mockWorkspace(page);
  let releaseOriginal: () => void = () => {};
  const originalResponse = new Promise<void>(resolve => { releaseOriginal = resolve; });
  await page.route('**/resource/originals/**', async route => { await originalResponse; await route.fallback(); });
  try {
    await page.goto('/#/gallery');
    await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '图片详情' });
    await expect(dialog.locator('.modern-reader-preview')).toHaveClass(/loaded/);
    const island = dialog.getByRole('button', { name: '查看原图', exact: true });
    await expect(island).toBeVisible();
    await expect.poll(() => dialog.locator('.modern-reader-preview').evaluate(node => getComputedStyle(node).opacity)).toBe('1');
    const position = () => dialog.evaluate(node => {
      const media = node.querySelector('.modern-reader-media')!.getBoundingClientRect();
      const button = node.querySelector('.modern-original-island')!.getBoundingClientRect();
      return { center: Math.abs(button.x + button.width / 2 - media.x - media.width / 2), bottom: media.bottom - button.bottom };
    });
    await expect.poll(async () => (await position()).center).toBeLessThan(1);
    await expect.poll(async () => (await position()).bottom).toBeCloseTo(14, 0);
    expect(requested.some(path => path.startsWith('/resource/originals/'))).toBe(false);
    await page.screenshot({ path: test.info().outputPath('original-island.png') });
    await island.click();
    await expect(dialog.getByRole('button', { name: '正在加载原图' })).toBeDisabled();
    releaseOriginal();
    await expect(dialog.locator('.modern-reader-preview')).toHaveAttribute('src', /originals/);
    await expect(dialog.getByRole('button', { name: '已显示原图' })).toBeDisabled();
    expect(requested.filter(path => path.startsWith('/resource/originals/'))).toHaveLength(1);
    await page.keyboard.press('ArrowRight');
    await expect(dialog.locator('h2')).toHaveText('10001_p0');
    await expect(dialog.getByRole('button', { name: '查看原图', exact: true })).toBeEnabled();
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(dialog.getByRole('button', { name: '查看原图', exact: true })).toBeInViewport();
    expect(errors).toEqual([]);
  } finally { releaseOriginal(); }
});
