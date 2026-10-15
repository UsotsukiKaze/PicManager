import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page, options: { role?: string; theme?: string; duplicate?: boolean; fail?: boolean; unknown?: boolean } = {}) {
  const errors: string[] = [], sent: Array<{ name: string; body: string }> = [];
  let inFlight = 0, maxInFlight = 0;
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(theme => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme, reduced: false })), options.theme || 'light');
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: options.role || 'root', nickname: '测试用户' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (path === '/api/upload/capabilities') body = { max_file_size: 50 * 1024 * 1024, extensions: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'] };
    else if (path === '/api/groups/') body = [{ id: 1, name: '鸣潮' }, { id: 2, name: '原神' }];
    else if (path === '/api/characters/') body = [{ id: 1, name: '琳奈', group_id: 1 }, { id: 2, name: '芙宁娜', group_id: 2 }];
    else if (path === '/api/feature-tags/') body = [{ id: 1, name: '蓝发' }, { id: 2, name: '眼镜' }];
    else if (path === '/api/emotion-tags/') body = [{ id: 1, name: '开心' }, { id: 2, name: '#摸头' }];
    else if (path === '/api/images/search') body = { images: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/emojis/search') body = { emojis: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/emojis/characters') body = [];
    else if (path === '/api/upload/temp-count') body = { count: 0 };
    else if (path === '/api/upload/temp-images') body = { images: [], items: [] };
    else if (path === '/api/upload/temp-pixiv/start') body = { run_id: 'test' };
    else if (path === '/api/upload/duplicates/resolve') body = { status: route.request().postDataJSON().keep === 'cancel' ? 'cancelled' : 'success', image_id: 'existing', message: '已保存比对结果' };
    else if (path === '/api/upload/direct/prepare') { await route.fulfill({ status: 409, json: { detail: 'Direct upload requires STORAGE_BACKEND=r2' } }); return; }
    else if (path === '/api/upload/single' || path === '/api/emojis/upload') {
      const raw = route.request().postDataBuffer()?.toString() || '';
      const name = /filename="([^"]+)"/.exec(raw)?.[1] || '';
      sent.push({ name, body: raw }); inFlight++; maxInFlight = Math.max(maxInFlight, inFlight);
      await new Promise(resolve => setTimeout(resolve, 80)); inFlight--;
      if (options.unknown) { await route.abort('connectionfailed'); return; }
      if (options.fail && sent.filter(item => item.name === name).length === 1) { await route.fulfill({ status: 400, json: { detail: '标签已失效，请重新选择' } }); return; }
      body = options.duplicate && name !== '5.png' ? { status: 'duplicate', duplicate_token: 'fixture-token', incoming: { image_id: 'new', width: 640, height: 480 }, duplicates: [{ image_id: 'existing', width: 640, height: 480, score: 99 }] }
        : { status: options.role === 'user' ? 'pending' : 'success', image_id: options.role === 'user' ? 'pending' : 'test-id', message: '入库完成' };
    }
    await route.fulfill({ json: body });
  });
  return { errors, sent, maxInFlight: () => maxInFlight };
}
async function image(page: Page, name: string, color = '#91b7df') {
  const data = await page.evaluate(fill => {
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const context = canvas.getContext('2d')!; context.fillStyle = fill; context.fillRect(0, 0, 640, 480);
    context.fillStyle = '#e9bdd4'; context.beginPath(); context.arc(350, 250, 150, 0, Math.PI * 2); context.fill();
    return canvas.toDataURL('image/png').split(',')[1]!;
  }, color);
  return { name, mimeType: 'image/png', buffer: Buffer.from(data, 'base64') };
}
async function pick(page: Page, label: string, name: string) {
  await page.getByRole('combobox', { name: `搜索${label}`, exact: true }).click();
  await page.getByRole('option', { name, exact: true }).click();
}

test('one intake expands into a batch, preserves metadata and appends selected tags', async ({ page }, info) => {
  const mock = await fixture(page);
  await page.goto('/#/upload');
  await expect(page.locator('.intake-dropzone')).toBeVisible();
  const first = await image(page, '12345678_p0.png');
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(first);
  await expect(page.locator('.intake-cards')).toHaveClass(/is-single/);
  await pick(page, '角色', '琳奈');
  await expect(page.getByRole('button', { name: '移除分组 鸣潮', exact: true })).toBeVisible();
  await pick(page, '特征', '蓝发');
  await page.locator('.intake-more summary').click();
  await expect(page.locator('#intake-pid')).toHaveValue('12345678');
  await page.locator('#intake-description').fill('单张备注保留');
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(await image(page, 'second.png', '#adb3d6'));
  await expect(page.locator('.intake-card')).toHaveCount(2);
  await expect(page.locator('.intake-cards')).not.toHaveClass(/is-single/);
  await page.getByRole('button', { name: '选择可编辑项', exact: true }).click();
  await pick(page, '角色', '琳奈');
  await pick(page, '特征', '眼镜');
  await page.getByRole('button', { name: '应用到 2 张', exact: true }).click();
  await page.getByRole('button', { name: '撤销编辑', exact: true }).click();
  await page.getByRole('button', { name: '选择可编辑项', exact: true }).click();
  await pick(page, '角色', '琳奈');
  await pick(page, '特征', '眼镜');
  await page.getByRole('button', { name: '应用到 2 张', exact: true }).click();
  await expect(page.getByRole('button', { name: '提交 2 张', exact: true })).toBeEnabled();
  await expect.poll(() => page.locator('.intake-editor').evaluate(node => node.scrollTop)).toBe(0);
  await page.locator('#workspace-scroll').evaluate(node => { node.scrollTop = 0; });
  await page.mouse.move(10, 10);
  await page.screenshot({ path: info.outputPath('upload-batch-light.png'), fullPage: true });
  await page.getByRole('button', { name: '提交 2 张', exact: true }).click();
  await expect(page.locator('.intake-state[data-state=success]')).toHaveCount(2);
  expect(mock.sent).toHaveLength(2);
  const body = mock.sent.find(item => item.name === first.name)!.body;
  expect(body).toContain('单张备注保留'); expect(body).toContain('12345678');
  expect(body).toContain('name="feature_tag_ids"\r\n\r\n[1,2]');
  expect(mock.sent.find(item => item.name === 'second.png')!.body).toContain('name="feature_tag_ids"\r\n\r\n[2]');
  expect(mock.errors).toEqual([]);
});

test('duplicate review releases worker slots and tasks survive navigation', async ({ page }) => {
  const mock = await fixture(page, { duplicate: true });
  await page.goto('/#/upload?group_id=1&character_id=1');
  const files = await Promise.all(['1.png','2.png','3.png','4.png','5.png'].map((name, index) => image(page, name, `rgb(${100 + index * 20},170,210)`)));
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(files);
  await expect(page.getByRole('button', { name: '提交 5 张', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '提交 5 张', exact: true }).click();
  await expect(page.locator('.intake-state[data-state=attention]')).toHaveCount(4);
  await expect(page.locator('.intake-state[data-state=success]')).toHaveCount(1);
  expect(mock.sent).toHaveLength(5); expect(mock.maxInFlight()).toBeLessThanOrEqual(3);
  await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '表情包库', exact: true }).click();
  await expect(page.locator('.modern-emoji')).toBeVisible();
  await page.getByRole('navigation', { name: '主导航' }).getByRole('link', { name: '上传', exact: false }).click();
  await expect(page.locator('.intake-card')).toHaveCount(5);
  await expect(page.locator('.intake-state[data-state=attention]')).toHaveCount(4);
  await page.getByRole('button', { name: '比对图片', exact: true }).first().click();
  await expect(page.locator('.duplicate-workbench')).toBeVisible();
  await page.getByRole('button', { name: '保留两张', exact: true }).click();
  await expect(page.locator('.intake-state[data-state=attention]')).toHaveCount(3);
  await expect(page.locator('.intake-state[data-state=success]')).toHaveCount(2);
  expect(mock.sent).toHaveLength(5); expect(mock.errors).toEqual([]);
});

test('failed items retry without resending successful files and pending review stays distinct', async ({ page }) => {
  const mock = await fixture(page, { fail: true, role: 'user' });
  await page.goto('/#/upload?group_id=1&character_id=1');
  await expect(page.getByRole('group', { name: '新文件入库目标' }).getByRole('button', { name: '表情', exact: true })).toHaveCount(0);
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(await image(page, 'retry.png'));
  await page.getByRole('button', { name: '提交审核 1 张', exact: true }).click();
  await expect(page.locator('.intake-state')).toHaveText('失败');
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('.intake-state')).toHaveText('待审核');
  expect(mock.sent).toHaveLength(2); expect(mock.errors).toEqual([]);
});

test('mobile emoji intake, content deduplication and restoring metadata drafts', async ({ page }, info) => {
  const mock = await fixture(page, { theme: 'dark' });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/upload?kind=emoji');
  const file = await image(page, 'emoji.png');
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(file);
  await expect(page.getByRole('group', { name: '入库类型' }).getByRole('button', { name: '表情', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await pick(page, '情绪', '开心');
  await page.locator('.intake-more summary').click();
  await page.locator('#intake-description').fill('草稿备注');
  await page.getByRole('button', { name: '关闭信息面板', exact: true }).click();
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles({ ...file, name: 'same-content.png' });
  await expect(page.locator('.intake-card')).toHaveCount(1);
  await page.screenshot({ path: info.outputPath('upload-mobile-dark.png'), fullPage: true });
  expect(await page.locator('#workspace-scroll').evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  await page.reload();
  await expect(page.locator('.intake-restore')).toContainText('1 份信息草稿');
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(file);
  await page.locator('.intake-more summary').click();
  await expect(page.locator('#intake-description')).toHaveValue('草稿备注');
  await expect(page.getByRole('button', { name: '移除情绪 开心', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '关闭信息面板', exact: true }).click();
  await page.getByRole('button', { name: '提交 1 张', exact: true }).click();
  await expect(page.locator('.intake-state')).toHaveText('已入库');
  expect(mock.sent[0]!.body).toContain('name="emotion_ids"\r\n\r\n[1]'); expect(mock.errors).toEqual([]);
});

test('unknown response requires checking results, and temporary intake uses the common wheel', async ({ page }) => {
  const mock = await fixture(page, { unknown: true });
  await page.goto('/#/upload?group_id=1&character_id=1');
  await page.getByLabel('选择上传文件', { exact: true }).setInputFiles(await image(page, 'unknown.png'));
  await page.getByRole('button', { name: '提交 1 张', exact: true }).click();
  await expect(page.locator('.intake-state')).toHaveText('结果待核对');
  await expect(page.getByRole('button', { name: '提交 0 张', exact: true })).toBeDisabled();
  await expect(page.locator('.section-wheel')).toHaveClass(/is-idle/);
  await page.locator('.section-wheel-trigger').click();
  await page.getByRole('dialog').getByRole('button', { name: '切换到待整', exact: true }).click();
  await expect(page).toHaveURL(/tab=temp/);
  await expect(page.locator('#tab-temp-upload')).toBeVisible();
  await expect(page.locator('#page-upload>.page-header')).toBeHidden();
  await expect(page.locator('#page-upload .upload-tab-header')).toBeHidden();
  expect(mock.errors).toEqual([]);
});
