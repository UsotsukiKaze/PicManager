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
    if (url.href === 'https://usotsuki-kaze.com/favicon.ico') {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="6" fill="#739bd5"/><circle cx="16" cy="16" r="8" fill="#d89cb6"/></svg>' }); return;
    }
    if (path.includes('/resource/previews/COVER')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900"><defs><linearGradient id="sky" x2=".7" y2="1"><stop stop-color="#7ca7c5"/><stop offset="1" stop-color="#efd6df"/></linearGradient></defs><rect width="1600" height="900" fill="url(#sky)"/><circle cx="1230" cy="190" r="105" fill="#fff" opacity=".7"/><path d="M0 700L400 230L950 830L1600 460V900H0" fill="#596a93"/><path d="M0 890L850 570L1600 810V900H0" fill="#d0aac2"/></svg>' }); return;
    }
    if (!url.hostname.startsWith('127.')) { await route.abort(); return; }
    if (path.startsWith('/resource/')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1000"><defs><linearGradient id="g"><stop stop-color="#8aa9db"/><stop offset="1" stop-color="#d6c2df"/></linearGradient></defs><rect width="800" height="1000" fill="url(#g)"/><circle cx="400" cy="400" r="180" fill="#fff" opacity=".4"/></svg>' }); return;
    }
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown;
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role, nickname: '测试用户', avatar_url: '/favicon.ico' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/system/status') body = { total_images: 41, total_groups: 2, total_characters: 1, total_emojis: 0, temp_count: 0, store_count: 41 };
    else if (path === '/api/groups/popular') body = [...groups, { id: 3, name: '明日方舟' }, { id: 4, name: '东方Project' }, { id: 5, name: '蔚蓝档案' }, { id: 6, name: '碧蓝航线' }, { id: 7, name: '鸣潮' }, { id: 8, name: '绝区零' }].map((group, index) => ({ ...group, image_count: 41 - index * 5, cover: index < 2 ? {
      image_id: `COVER0000${index + 1}`, preview_url: `/resource/previews/COVER0000${index + 1}.webp`,
      width: 1600, height: 900, source: 'pixiv_bookmarks', bookmarks: 1200 - index * 100,
    } : null }));
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
    else if (path === '/api/pixiv-ol/account/login/pending') body = { session: null };
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
  const selector = page.getByRole('group', { name: '推荐方式' });
  await expect(selector.getByRole('button', { name: '猜你喜欢' })).toHaveAttribute('aria-pressed', 'true');
  await expect(selector.getByRole('button')).toHaveText(['猜你喜欢', '进货模式', 'Pixiv 发现']);
  await expect(page.locator('.px-card')).toHaveCount(20);
  await selector.getByRole('button', { name: '进货模式' }).click();
  await expect(page.locator('.px-card')).toHaveCount(20);
  await expect(page.locator('.px-gallery')).toContainText('stock作品');
  await selector.getByRole('button', { name: 'Pixiv 发现' }).click();
  await expect(page.locator('.px-gallery')).toContainText('discovery作品');
  await selector.getByRole('button', { name: '猜你喜欢' }).click();
  await expect(page.locator('.px-gallery')).toContainText('personal作品');
  expect(modes).toEqual(['personal', 'stock', 'discovery']);
  const gallery = (await page.locator('.px-gallery').boundingBox())!;
  const tools = (await page.locator('.px-floating-tools').boundingBox())!;
  expect(tools.x).toBeGreaterThanOrEqual(gallery.x + gallery.width);
  expect(tools.x + tools.width).toBeLessThanOrEqual(1920);
  await page.screenshot({ path: test.info().outputPath('pixiv-archive.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileMode = page.getByRole('combobox', { name: '推荐方式' });
  await expect(mobileMode).toBeVisible();
  await mobileMode.selectOption('stock');
  await expect(page.locator('.px-gallery')).toContainText('stock作品');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect.poll(() => page.locator('#workspace-sidebar').evaluate(node => Math.round(node.getBoundingClientRect().width))).toBe(390);
  const exit = (await page.getByRole('button', { name: '退出', exact: true }).boundingBox())!;
  expect(exit.x + exit.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: test.info().outputPath('pixiv-mobile.png') });
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
  await expect(page.getByRole('combobox', { name: '搜索角色' })).toHaveValue('芙宁娜');
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
    expect(await card.locator('.modern-card-footer').evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgba(247, 249, 253, 0.84)');
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
  await expect.poll(() => page.locator('#workspace-sidebar').evaluate(node => Math.round(node.getBoundingClientRect().width))).toBe(204);
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
  expect((await page.locator('.modern-home').boundingBox())!.width).toBeLessThanOrEqual(1320);
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
  await page.getByRole('button', { name: '清除条件', exact: true }).click();
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
  expect(await page.locator('.sidebar-user #header-role').evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgb(231, 237, 246)');
  await page.locator('.sidebar-user').click();
  await expect(page.locator('.sidebar-user')).toHaveAttribute('aria-current', 'page');
  const account = page.frameLocator('#profile-frame');
  await expect(account.locator('#user-nickname')).toHaveText('测试用户');
  await expect(page.locator('.modern-profile').getByRole('heading', { name: '我的', exact: true })).toBeVisible();
  const surface = await account.locator('.user-card').evaluate(node => ({ radius: getComputedStyle(node).borderRadius, background: getComputedStyle(node).backgroundColor }));
  expect(surface).toEqual({ radius: '8px', background: 'rgb(250, 251, 253)' });
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

test('archive group selection supports keyboard navigation and mobile browsing', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/');
  const deck = page.getByRole('complementary', { name: '分组档案' });
  await expect(deck.locator('.archive-group-selector button')).toHaveCount(5);
  await expect(page.getByRole('heading', { name: '小爱图库', exact: true })).toBeVisible();
  await expect(page.locator('.archive-launch small')).toHaveText('EXPLORE ARCHIVE');
  await expect(page.locator('.archive-upload small')).toHaveText('UPLOAD RESOURCE');
  await expect(page.locator('.archive-personal-icon img')).toHaveAttribute('src', /^(https:\/\/usotsuki-kaze\.com\/favicon\.ico|\/static\/icon\/Pic\.png)$/);
  await expect(deck.locator('.archive-cover')).toHaveAttribute('src', '/resource/previews/COVER00001.webp');
  await deck.getByRole('button', { name: '预览崩坏星穹铁道' }).focus();
  await page.keyboard.press('Enter');
  await expect(deck.getByRole('button', { name: '预览崩坏星穹铁道' })).toHaveAttribute('aria-pressed', 'true');
  await expect(deck.getByRole('link', { name: '浏览崩坏星穹铁道分组' })).toBeVisible();
  await deck.getByRole('link', { name: '浏览崩坏星穹铁道分组' }).click();
  await expect(page).toHaveURL(/group_id=2/);
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await expect(page.locator('#gallery-query-toggle b')).toHaveText('1');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('link', { name: '首页', exact: true }).click();
  await expect(page.getByText('小 · 爱 · 图 · 库')).toBeVisible();
  await expect(deck).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await page.locator('#workspace-scroll').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await expect(deck.locator('.archive-sheet-front')).toHaveCSS('transition-duration', '0s');
  await page.locator('#workspace-scroll').evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: test.info().outputPath('home-archive-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.locator('#workspace-scroll').evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: test.info().outputPath('home-archive-wide.png') });
  await page.getByLabel('界面外观', { exact: true }).click();
  await page.getByRole('button', { name: '深色', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.keyboard.press('Escape');
  await page.locator('#workspace-scroll').evaluate(node => { node.scrollTop = 0; });
  await page.screenshot({ path: test.info().outputPath('home-archive-dark.png') });
  await deck.getByRole('button', { name: '预览明日方舟' }).click();
  await expect(deck.locator('.archive-cover')).toHaveCount(0);
  await expect(deck.locator('.entity-avatar')).toBeVisible();
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
  expect(tagColors.every(tag => tag.radius === '5px')).toBe(true);
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


test('appearance persists and synchronizes the account frame while reduced motion skips reader animations', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'no-preference' });
  await page.goto('/');
  await page.getByLabel('界面外观', { exact: true }).click();
  await page.getByRole('button', { name: '深色', exact: true }).click();
  await page.getByLabel('减少动态效果').check();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced');
  await page.keyboard.press('Escape');
  await expect(page.locator('.modern-appearance')).not.toHaveAttribute('open');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('html')).toHaveAttribute('data-motion', 'reduced');
  await page.locator('.sidebar-user').click();
  await expect(page.frameLocator('#profile-frame').locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.frameLocator('#profile-frame').locator('html')).toHaveAttribute('data-motion', 'reduced');
  const surface = await page.frameLocator('#profile-frame').locator('.user-card').evaluate(node => getComputedStyle(node).backgroundColor);
  expect(surface).toBe('rgb(32, 36, 44)');
  await page.getByRole('link', { name: '图片管理', exact: true }).click();
  const card = page.locator('.modern-image-card').first();
  await expect(card).toBeVisible();
  expect(await card.locator('.modern-card-footer').evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgba(18, 24, 34, 0.78)');
  await card.hover();
  await expect(card.locator('.modern-card-actions')).toHaveCSS('opacity', '1');
  await page.screenshot({ path: test.info().outputPath('gallery-dark.png') });
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '图片详情' });
  await expect(dialog).toBeVisible();
  expect(await dialog.evaluate(node => node.getAnimations({ subtree: true }).length)).toBe(0);
  await page.screenshot({ path: test.info().outputPath('detail-dark.png') });
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await page.getByLabel('界面外观', { exact: true }).click();
  await page.getByRole('button', { name: '跟随系统', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  expect(await card.locator('.modern-card-footer').evaluate(node => getComputedStyle(node).backgroundColor)).toBe('rgba(247, 249, 253, 0.84)');
  expect(await card.locator('.modern-card-identity strong').evaluate(node => getComputedStyle(node).color)).toBe('rgb(48, 53, 64)');
  await page.keyboard.press('Escape');
  await page.mouse.move(0, 0);
  await card.hover();
  await expect(card.locator('.modern-card-actions')).toHaveCSS('opacity', '1');
  await page.screenshot({ path: test.info().outputPath('gallery-light.png') });
  await page.emulateMedia({ colorScheme: 'dark' });
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(errors).toEqual([]);
});


test('Pixiv reader confirms collection after success and preserves the added state across views', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  const artworks = Array.from({ length: 20 }, (_, index) => ({ pid: String(2000 + index), title: `蓝粉灰作品 ${index}`, author: '测试画师', author_id: '9', page_count: 1, width: 800, height: 1000,
    preview_url: '/static/icon/Pic.png', imported_pages: [], tags: [{ name: '芙宁娜' }], match: { group_ids: [1], character_ids: [1], feature_tag_ids: [], conflicts: [] } }));
  let cart: unknown[] = [];
  await page.route('**/api/pixiv-ol/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/reader-preview') || path.endsWith('/avatar')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1000"><rect width="800" height="1000" fill="#739bd5"/><circle cx="400" cy="500" r="240" fill="#d89cb6"/></svg>' });
    } else if (path.endsWith('/account')) {
      await route.fulfill({ json: { connected: true, user_id: '7', name: '测试画友', media_revision: 'test' } });
    } else if (path.endsWith('/recommendations') || path.endsWith('/feed')) {
      await route.fulfill({ json: { items: artworks, total: 20, has_more: false, next_cursor: null } });
    } else if (path.endsWith('/cart')) {
      if (route.request().method() === 'POST') cart = [{ id: 'cart-1', status: 'caching', artwork: artworks[0], pages: [0], draft: { pages: [0], import_mode: 'merged' } }];
      await route.fulfill({ json: { items: cart } });
    } else await route.fallback();
  });
  await page.goto('/#/pixiv');
  await expect(page.locator('.px-card')).toHaveCount(20);
  await page.getByRole('button', { name: '查看 蓝粉灰作品 0', exact: true }).click();
  const reader = page.locator('.px-artwork-reader');
  await expect(reader).toBeVisible();
  await expect(reader.locator('.px-detail-cover')).toHaveClass(/is-ready/);
  await expect.poll(() => reader.evaluate(node => Math.abs(node.querySelector('.px-detail-cover')!.getBoundingClientRect().top - node.querySelector('.px-detail-body')!.getBoundingClientRect().top))).toBeLessThan(3);
  await page.screenshot({ path: test.info().outputPath('pixiv-detail.png') });
  await reader.getByRole('button', { name: '加入优选夹', exact: true }).click();
  await expect(reader.locator('#pixiv-draft-submit')).toHaveText('已加入');
  await expect(reader).toHaveCount(0);
  await expect(page.locator('.px-floating-cart .px-cart-count')).toHaveText('1');
  await page.getByRole('tab', { name: '关注更新', exact: true }).click();
  await page.getByRole('button', { name: '查看 蓝粉灰作品 0', exact: true }).click();
  await expect(reader.locator('#pixiv-draft-submit')).toHaveText('已加入');
  await expect(reader.locator('#pixiv-draft-submit')).toBeDisabled();
  await page.keyboard.press('Escape');
  expect(errors).toEqual([]);
});


test('gallery resumes interrupted filter and reader motion without a jump', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'no-preference' });
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await page.getByRole('button', { name: '打开图片查询' }).click();
  const filterDelta = await page.evaluate(async () => {
    const panel = document.getElementById('gallery-search-panel')!;
    const animation = panel.getAnimations()[0];
    if (!animation) throw new Error('Expected the filter opening animation');
    animation.pause();
    animation.currentTime = 90;
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    const before = panel.getBoundingClientRect().height;
    document.getElementById('gallery-query-toggle')!.click();
    await Promise.resolve();
    return Math.abs(panel.getBoundingClientRect().height - before);
  });
  expect(filterDelta).toBeLessThan(2);
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await expect(page.getByRole('textbox', { name: '搜索描述' })).toBeVisible();
  await page.getByRole('textbox', { name: '搜索描述' }).press('Escape');
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await page.getByRole('button', { name: '查看图片 10000_p0', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '图片详情' });
  await expect(dialog).toBeVisible();
  const readerDelta = await page.evaluate(async () => {
    const reader = document.querySelector<HTMLElement>('.modern-reader-media')!;
    const animation = reader.getAnimations()[0];
    if (!animation) throw new Error('Expected the reader opening animation');
    animation.pause();
    animation.currentTime = 110;
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()));
    const before = reader.getBoundingClientRect();
    document.querySelector<HTMLButtonElement>('.modern-reader-close')!.click();
    const after = reader.getBoundingClientRect();
    return Math.max(Math.abs(after.left - before.left), Math.abs(after.top - before.top), Math.abs(after.width - before.width));
  });
  expect(readerDelta).toBeLessThan(2);
  await expect(dialog).toHaveCount(0);
  await expect(page.getByRole('button', { name: '查看图片 10000_p0', exact: true })).toBeFocused();
  expect(errors).toEqual([]);
});

test('gallery chips remove individual conditions and clearing preserves the selected rating', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  await page.goto('/#/gallery?age_rating=r12&group_id=1&character_id=1&feature_tag_id=1&pid=10000&artist=画师&description=测试');
  await expect(page.locator('.modern-filter-chip')).toHaveCount(6);
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await expect(page.locator('#gallery-query-toggle b')).toHaveText('6');
  await page.getByRole('button', { name: '移除分组：原神', exact: true }).click();
  await expect(page).not.toHaveURL(/group_id=/);
  await expect(page).toHaveURL(/character_id=1/);
  await expect(page).toHaveURL(/age_rating=r12/);
  await expect(page.locator('.modern-filter-chip')).toHaveCount(5);
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await expect(page.getByRole('combobox', { name: '搜索角色' })).toHaveValue('芙宁娜');
  await page.getByRole('button', { name: '清除条件', exact: true }).click();
  await expect(page.locator('.modern-filter-chip')).toHaveCount(0);
  await expect(page).toHaveURL(/age_rating=r12$/);
  await expect(page.getByRole('button', { name: 'R12', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByRole('textbox', { name: '搜索画师' })).toHaveValue('');
  await page.route('**/api/images/search?*', async route => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('description') === '无匹配') await route.fulfill({ json: { images: [], total: 0, offset: 0, limit: 20 } });
    else await route.fallback();
  });
  await page.getByRole('textbox', { name: '搜索描述' }).fill('无匹配');
  await expect(page.locator('.modern-gallery-empty')).toContainText('没有匹配的图片');
  await expect(page.getByRole('textbox', { name: '搜索描述' })).toHaveValue('无匹配');
  await page.getByRole('button', { name: '清除搜索条件', exact: true }).click();
  await expect(page.locator('.modern-image-card')).toHaveCount(20);
  await expect(page).toHaveURL(/age_rating=r12$/);
  expect(errors).toEqual([]);
});

test('gallery dropdown stays inside the viewport and Escape closes it before the search panel', async ({ page }) => {
  const { errors } = await mockWorkspace(page);
  const groups = Array.from({ length: 120 }, (_, index) => ({ id: index + 1, name: `测试分组${index + 1}` }));
  await page.route('**/api/groups/?*', route => {
    const offset = Number(new URL(route.request().url()).searchParams.get('skip') || 0);
    return route.fulfill({ json: groups.slice(offset, offset + 100) });
  });
  await page.setViewportSize({ width: 1280, height: 400 });
  await page.goto('/#/gallery');
  await page.getByRole('button', { name: '打开图片查询' }).click();
  const picker = page.getByRole('combobox', { name: '搜索分组' });
  await picker.focus();
  const list = page.getByRole('listbox', { name: '分组', exact: true });
  await expect(list).toBeVisible();
  await expect(list).toHaveClass(/opens-upwards/);
  const box = await list.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(11);
  expect(box!.y + box!.height).toBeLessThanOrEqual(389);
  await picker.press('Escape');
  await expect(list).not.toBeVisible();
  await expect(page.locator('#gallery-search-panel')).toBeVisible();
  await picker.press('Escape');
  await expect(page.locator('#gallery-search-panel')).not.toBeVisible();
  await expect(page.locator('#gallery-query-toggle')).toBeFocused();
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.getByRole('button', { name: '打开图片查询' }).click();
  await page.getByRole('combobox', { name: '搜索角色' }).fill('水神');
  await page.getByRole('option', { name: '芙宁娜 原神', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '搜索角色' })).toHaveValue('芙宁娜');
  await expect.poll(() => page.locator('#gallery-search-panel').evaluate(node => node.getAnimations().length)).toBe(0);
  const layout = await page.evaluate(() => {
    const form = document.querySelector('.modern-gallery-filters')!.getBoundingClientRect();
    const results = document.querySelector('.modern-gallery-results')!.getBoundingClientRect();
    const grid = document.querySelector('.modern-image-grid')!.getBoundingClientRect();
    return { height: form.height, panelGap: results.top - form.bottom, resultGap: grid.top - results.bottom };
  });
  expect(layout.height).toBeLessThanOrEqual(190);
  expect(layout.panelGap).toBeCloseTo(16, 1);
  expect(layout.resultGap).toBeCloseTo(12, 1);
  await page.screenshot({ path: test.info().outputPath('gallery-search-desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(await page.locator('#workspace-scroll').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('gallery-search-mobile.png') });
  expect(errors).toEqual([]);
});
