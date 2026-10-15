import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page, options: { role?: string; slowProfile?: boolean; reduced?: boolean; dark?: boolean; review?: boolean } = {}) {
  const errors: string[] = [], requests: string[] = [], writes: unknown[] = [];
  let nickname = '测试用户', fail = false, pending = options.review, release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  const user = () => ({ id: 1, role: options.role || 'root', nickname, avatar_url: '/static/icon/Pic.png', created_at: '2026-01-01' });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(options => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: options.dark ? 'dark' : 'light', reduced: options.reduced || false })), options);
  await page.route('**/*', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (!/^\/(auth|api|admin)\//.test(path)) { await route.continue(); return; }
    requests.push(path);
    let body: unknown = {};
    if (path === '/auth/me') {
      if (options.slowProfile && request.frame().parentFrame()) await gate;
      body = options.role === 'guest' ? { is_guest: true, guest_name: '访客', remaining_operations: 5, daily_limit: 10 } : { is_guest: false, user: user() };
    } else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/auth/profile-stats') body = { approved_total: 42, approved_add: 30, approved_edit: 12, contribution: { score: 120, percent: 45 }, preferences: { groups: [{ name: '测试分组', count: 3 }], total_group: 3 } };
    else if (path === '/auth/set-nickname') {
      writes.push(request.postDataJSON());
      if (fail) { await route.fulfill({ status: 400, json: { detail: '测试保存失败' } }); return; }
      nickname = request.postDataJSON().nickname; body = { user: user(), message: '昵称已保存' };
    } else if (path === '/admin/pending/9') {
      writes.push(request.postDataJSON());
      if (fail) { await route.fulfill({ status: 400, json: { detail: '审核失败' } }); return; }
      pending = false; body = { message: '已批准' };
    } else if (path === '/admin/pending') body = pending ? [{ id: 9, request_type: 'group_add', group_info: { name: '测试分组' }, created_at: '2026-10-15T12:00:00' }] : [];
    else if (path === '/auth/my-requests' || path === '/admin/admins') body = [];
    else if (/\/api\/(groups|characters|feature-tags|emotion-tags)\/$/.test(path) || path === '/api/groups/popular') body = [];
    else if (path === '/api/system/status' || path === '/api/system/diagnostics') body = { total_images: 42, total_groups: 3, total_characters: 2, store_path: '/resource/store', temp_path: '/resource/temp' };
    else if (path === '/api/images/search') body = { images: [], total: 0 };
    else if (path === '/api/emojis/search') body = { emojis: [], total: 0 };
    else if (path === '/api/emojis/characters') body = [];
    else if (path === '/api/upload/capabilities') body = { max_file_size: 52428800, extensions: ['png'] };
    else if (path === '/api/pixiv-ol/account') body = { connected: true, status: 'connected', user_id: '7', name: '画友' };
    else if (path === '/api/pixiv-ol/preferences') {
      if (request.method() === 'PUT') {
        writes.push(request.postDataJSON());
        if (fail) { await route.fulfill({ status: 400, json: { detail: '测试保存失败' } }); return; }
        body = { saved: true };
      } else body = { groups: {}, ai: 'exclude', bookmark_sync: false, include_r18: false, bookmark_sync_scope: 'both', bookmark_visibility: 'private' };
    } else if (path === '/api/pixiv-ol/account/login/pending') body = null;
    else if (path === '/api/pixiv-ol/jobs') body = [];
    else if (path === '/api/pixiv-ol/cart') body = { items: [] };
    await route.fulfill({ json: body });
  });
  return { errors, requests, writes, release, fail(value: boolean) { fail = value; } };
}
async function finishTitle(page: Page) {
  await page.locator('.section-heading').evaluate(element => element.getAnimations({ subtree: true }).forEach(animation => animation.finish()));
  await expect(page.locator('.section-film-title')).toHaveAttribute('data-rolling', 'false');
}

test('five page titles share a continuous reel through settings and profile', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/gallery'); await finishTitle(page);
  for (const [path, title] of [['/settings', '设置'], ['/profile', '我的'], ['/emoji', '表情包库']]) {
    const previous = await page.locator('.section-film-frame').textContent();
    await page.locator(`a[href="#${path}"]`).first().click();
    await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible();
    const titles = await page.locator('.section-film-frame').allTextContents();
    expect(titles[0]).toBe(previous); expect(titles.at(-1)).toBe(title);
    await finishTitle(page);
    await expect(page.locator('.section-film-frame')).toHaveText([title]);
  }
  expect(mock.errors).toEqual([]);
});

test('settings folds can reverse and save feedback preserves the edited form on failure', async ({ page }, info) => {
  const mock = await fixture(page);
  await page.goto('/#/settings');
  await expect(page.locator('#pixiv-ai')).toBeVisible();
  const fold = page.locator('.px-group-panel');
  await fold.locator(':scope>summary').click();
  await expect(fold).toHaveAttribute('open', '');
  await fold.locator(':scope>summary').click();
  await expect(fold).not.toHaveAttribute('open', '');
  await page.locator('#pixiv-ai').selectOption('include');
  const save = page.locator('[data-action=save-settings]');
  mock.fail(true); await save.click();
  await expect(page.locator('.account-save-feedback')).toContainText('测试保存失败');
  await expect(page.locator('#pixiv-ai')).toHaveValue('include');
  await expect(save).toBeEnabled();
  mock.fail(false); await save.click();
  await expect(save).toContainText('已保存');
  await expect(page.locator('#pixiv-ai')).toHaveValue('include');
  expect(mock.writes).toHaveLength(2);
  await page.locator('#workspace-scroll').evaluate(element => element.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path: info.outputPath('settings-light.png') });
  await page.getByRole('link', { name: '表情包库', exact: true }).click();
  expect(await page.evaluate(() => !!window.PicManagerAccountMotion)).toBe(false);
  expect(mock.errors).toEqual([]);
});

test('profile waits for permissions, cruises without loading tabs and edits the nickname in place', async ({ page }, info) => {
  const mock = await fixture(page, { slowProfile: true });
  await page.goto('/#/profile');
  await expect(page.locator('.profile-loading')).toBeVisible();
  await expect(page.getByRole('heading', { name: '我的', exact: true })).toBeVisible();
  mock.release();
  await expect(page.locator('#page-profile')).toHaveAttribute('aria-busy', 'false');
  const frame = page.frameLocator('#profile-frame');
  await expect(frame.locator('.profile-tab:not(.hidden)')).toHaveCount(4);
  expect(await frame.locator('.profile-tabs').evaluate(element => element.getAnimations({ subtree: true }).some(animation => animation.id === 'account-tab-loop'))).toBe(true);
  expect(mock.requests.filter(path => ['/auth/my-requests', '/admin/pending', '/admin/admins'].includes(path))).toEqual([]);
  await frame.getByRole('button', { name: '我的审核', exact: true }).click();
  await expect(frame.locator('#my-requests-panel')).toHaveClass(/active/);
  await frame.getByRole('button', { name: '个人信息', exact: true }).click();
  await expect(frame.locator('#personal-panel')).toHaveClass(/active/);
  await frame.locator('#edit-nickname-btn').click();
  await frame.locator('#new-nickname-input').fill('新的昵称');
  mock.fail(true); await frame.locator('#edit-nickname-form .btn-success').click();
  await expect(frame.locator('.account-save-feedback')).toContainText('测试保存失败');
  await expect(frame.locator('#new-nickname-input')).toHaveValue('新的昵称');
  mock.fail(false); await frame.locator('#edit-nickname-form .btn-success').click();
  await expect(frame.locator('#edit-nickname-form')).toBeHidden();
  await expect(frame.locator('#user-nickname')).toHaveText('新的昵称');
  await expect(page.locator('#header-username')).toHaveText('新的昵称');
  await expect(frame.locator('#contribution-score')).toHaveText('120');
  await page.screenshot({ path: info.outputPath('profile-light.png') });
  expect(mock.requests.filter(path => path === '/auth/my-requests')).toHaveLength(1);
  expect(mock.errors).toEqual([]);
});

test('review cards stay on failure and collapse only after a successful review', async ({ page }) => {
  const mock = await fixture(page, { review: true });
  await page.goto('/#/profile'); await expect(page.locator('#page-profile')).toHaveAttribute('aria-busy', 'false');
  const frame = page.frameLocator('#profile-frame');
  await frame.getByRole('button', { name: '管理员控制台', exact: true }).click();
  const card = frame.locator('[data-request-id="9"]'); await expect(card).toBeVisible();
  mock.fail(true); await card.getByRole('button', { name: '批准', exact: true }).click();
  await expect(card.getByRole('button', { name: '批准', exact: true })).toBeEnabled();
  await expect(card).toBeVisible();
  mock.fail(false); await card.getByRole('button', { name: '批准', exact: true }).click();
  await expect(card).toHaveCount(0); await expect(frame.locator('#pending-count')).toHaveText('0');
  expect(mock.writes).toEqual([{ action: 'approve', reason: null }, { action: 'approve', reason: null }]);
  expect(mock.errors).toEqual([]);
});

test('guest profile opens one tab without requesting private panels', async ({ page }) => {
  const mock = await fixture(page, { role: 'guest' });
  await page.goto('/#/profile'); await expect(page.locator('#page-profile')).toHaveAttribute('aria-busy', 'false');
  const frame = page.frameLocator('#profile-frame');
  await expect(frame.locator('.profile-tab:not(.hidden)')).toHaveCount(1);
  await expect(frame.locator('#guest-view')).toBeVisible();
  expect(mock.requests.filter(path => ['/auth/my-requests', '/admin/pending', '/admin/admins', '/auth/profile-stats'].includes(path))).toEqual([]);
  expect(mock.errors).toEqual([]);
});

test('reduced motion and narrow dark profile keep only permitted tabs and fit the viewport', async ({ page }, info) => {
  const mock = await fixture(page, { role: 'user', reduced: true, dark: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/profile');
  await expect(page.locator('#page-profile')).toHaveAttribute('aria-busy', 'false');
  const frame = page.frameLocator('#profile-frame');
  await expect(frame.locator('.profile-tab:not(.hidden)')).toHaveCount(2);
  const state = await frame.locator('html').evaluate(element => ({ theme: element.getAttribute('data-theme'), animations: element.ownerDocument.getAnimations().filter(animation => animation.id.startsWith('account-')).length, overflow: element.scrollWidth - element.clientWidth }));
  expect(state).toEqual({ theme: 'dark', animations: 0, overflow: 0 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  await frame.getByRole('button', { name: '我的审核', exact: true }).click();
  await expect(frame.locator('#my-requests-panel')).toHaveClass(/active/);
  await page.screenshot({ path: info.outputPath('profile-mobile-dark.png') });
  expect(mock.errors).toEqual([]);
});
