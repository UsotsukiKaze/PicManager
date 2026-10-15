import { test, expect, type Page } from '@playwright/test';

const groups = [{ id: 1, name: '鸣潮' }, { id: 2, name: '原神' }];
const characters = [{ id: 1, name: '琳奈', group_id: 1 }, { id: 2, name: '芙宁娜', group_id: 2 }];
const emotions = [{ id: 1, name: '兴奋', aliases: ['开心'] }, { id: 2, name: '#摸头', aliases: [] }];
const emojis = [
  { emoji_id: 'EMOTE1', file_path: 'resource/emojis/EMOTE1.gif', file_extension: 'gif', file_size: 1000, width: 640, height: 640, original_filename: 'smile.gif', created_at: '2026-10-14T10:00:00', description: '开心', groups: [groups[0]], characters: [characters[0]], emotions: [emotions[0]] },
  { emoji_id: 'EMOTE2', file_path: 'resource/emojis/EMOTE2.png', file_extension: 'png', file_size: 800, width: 640, height: 640, original_filename: 'touch.png', created_at: '2026-10-14T09:00:00', description: '摸头', groups: [groups[1]], characters: [characters[1]], emotions: [emotions[1]] },
];

async function mockEmojiPage(page: Page, theme: 'light' | 'dark' = 'dark') {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(mode => localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: mode, reduced: false })), theme);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path.startsWith('/resource/')) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="640"><rect width="640" height="640" fill="#dce5f4"/><circle cx="320" cy="310" r="180" fill="#e3adc7"/><circle cx="260" cy="275" r="18"/><circle cx="380" cy="275" r="18"/><path d="M250 360 Q320 420 390 360" fill="none" stroke="#313845" stroke-width="17"/></svg>' });
      return;
    }
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: 'root', nickname: '测试用户' } };
    else if (path === '/api/groups/') body = groups;
    else if (path === '/api/characters/') body = characters;
    else if (path === '/api/feature-tags/') body = [];
    else if (path === '/api/images/search') body = { images: emojis.map(item => ({ image_id: item.emoji_id, age_rating: 'all', groups: item.groups, characters: item.characters })), total: 2, limit: 20, offset: 0 };
    else if (path === '/api/emotion-tags/') body = emotions;
    else if (path === '/api/emojis/characters') body = characters.map(character => ({ ...character, emoji_count: 1 }));
    else if (path === '/api/emojis/search') {
      const list = emojis.filter(item => (!url.searchParams.get('group_id') || String(item.groups[0].id) === url.searchParams.get('group_id'))
        && (!url.searchParams.get('character_id') || String(item.characters[0].id) === url.searchParams.get('character_id'))
        && (!url.searchParams.get('emotion_id') || item.emotions.some(tag => String(tag.id) === url.searchParams.get('emotion_id')))
        && (!url.searchParams.get('function_id') || item.emotions.some(tag => String(tag.id) === url.searchParams.get('function_id')))
        && (!url.searchParams.get('description') || item.description.includes(url.searchParams.get('description')!)));
      body = { emojis: list, total: list.length, limit: 20, offset: 0 };
    } else if (path.startsWith('/api/emojis/')) {
      const item = emojis.find(item => item.emoji_id === path.split('/')[3]);
      if (item && route.request().method() === 'PUT') { item.description = route.request().postDataJSON().description; body = { status: 'success' }; }
      else body = item || {};
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
  });
  return errors;
}

test('emoji library filters, previews and adapts to dark mobile layout', async ({ page }, testInfo) => {
  const errors = await mockEmojiPage(page);
  await page.goto('/#/emoji');
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(2);
  await expect(page.locator('#modern-emoji-results')).toContainText('2 个表情包');
  await expect(page.locator('.modern-card-identity strong').first()).toHaveText('琳奈');
  await expect(page.locator('.modern-rating')).toHaveCount(1);
  const footer = await page.locator('.modern-card-footer').first().evaluate(element => getComputedStyle(element).backgroundColor);
  expect(footer).not.toBe('rgb(255, 255, 255)');
  await expect(page.locator('#modern-emoji-grid .modern-image-card').first()).toHaveCSS('opacity', '1');
  await page.screenshot({ path: testInfo.outputPath('emoji-dark-desktop.png') });

  await page.getByRole('button', { name: '搜索与筛选表情包' }).click();
  await page.getByRole('textbox', { name: '搜索备注' }).fill('摸头');
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '移除备注：摸头' })).toBeVisible();
  await expect(page).toHaveURL(/description=%E6%91%B8%E5%A4%B4/);
  await page.reload();
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(1);
  await page.getByRole('button', { name: '搜索与筛选表情包' }).click();
  await expect(page.getByRole('textbox', { name: '搜索备注' })).toHaveValue('摸头');
  await page.locator('#modern-emoji-results .modern-filter-chip').click();
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(2);
  await page.locator('#modern-emoji-grid .modern-image-open').first().click();
  await expect(page.locator('.modern-file-info')).toBeVisible();
  await expect(page.locator('.modern-detail-actions')).toContainText('下载表情包');
  await expect(page.locator('.modern-reader')).toBeVisible();
  await expect(page.locator('.modern-reader-media')).toHaveCSS('transform', 'none');
  await page.screenshot({ path: testInfo.outputPath('emoji-dark-detail.png') });
  await page.getByRole('button', { name: '关闭详情' }).click();
  await expect(page.locator('.modern-reader')).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(2);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await page.screenshot({ path: testInfo.outputPath('emoji-dark-mobile.png') });
  expect(errors).toEqual([]);
});

test('emoji labels and light cards restore from the URL', async ({ page }, testInfo) => {
  const errors = await mockEmojiPage(page, 'light');
  await page.goto('/#/emoji?tab=tags');
  await expect(page.locator('.modern-emoji-tags')).toBeVisible();
  await expect(page.locator('.modern-emoji-tag-card')).toHaveCount(2);
  await page.getByRole('button', { name: '功能标签', exact: true }).click();
  await expect(page.locator('.modern-emoji-tag-card')).toHaveCount(1);
  await page.getByRole('searchbox', { name: '搜索标签' }).fill('摸头');
  await expect(page.locator('.modern-emoji-tags')).toContainText('#摸头');
  await page.locator('.section-wheel-trigger').click();
  await page.getByRole('dialog').getByRole('button', { name: '切换到全部表情', exact: true }).click();
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card')).toHaveCount(2);
  await expect(page.locator('#modern-emoji-grid .modern-emoji-card').first()).toHaveCSS('opacity', '1');
  await page.screenshot({ path: testInfo.outputPath('emoji-light-desktop.png') });
  const footer = await page.locator('.modern-card-footer').first().evaluate(element => getComputedStyle(element).backgroundColor);
  expect(footer).not.toBe('rgb(27, 34, 45)');
  expect(errors).toEqual([]);
});

test('emoji and gallery reuse toolbar, card and picker styling', async ({ page }) => {
  const errors = await mockEmojiPage(page, 'light');
  await page.goto('/#/gallery');
  await expect(page.locator('.modern-image-card')).toHaveCount(2);
  const readStyle = (element: Element) => {
    const style = getComputedStyle(element);
    return { background: style.backgroundColor, border: style.borderColor, radius: style.borderRadius, height: style.height, fontSize: style.fontSize };
  };
  const galleryButton = await page.locator('#gallery-query-toggle').evaluate(readStyle);
  const galleryCard = await page.locator('.modern-image-card').first().evaluate(readStyle);
  await page.goto('/#/emoji');
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(2);
  expect(await page.locator('#emoji-query-toggle').evaluate(readStyle)).toEqual(galleryButton);
  expect(await page.locator('.modern-image-card').first().evaluate(readStyle)).toEqual(galleryCard);
  await page.getByRole('button', { name: '搜索与筛选表情包' }).click();
  await page.getByRole('combobox', { name: '搜索角色', exact: true }).fill('琳');
  await page.getByRole('option', { name: '琳奈' }).click();
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '移除角色：琳奈' })).toBeVisible();
  await page.getByRole('button', { name: '刷新表情包' }).click();
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(1);
  await page.locator('#modern-emoji-grid .modern-image-open').click();
  await page.getByRole('button', { name: '编辑表情包', exact: true }).click();
  await page.locator('#emoji-edit-description').fill('编辑后的备注');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect(page.locator('#modal-overlay')).toBeHidden();
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(1);
  await expect(page).toHaveURL(/character_id=1/);
  await page.getByRole('button', { name: '移除角色：琳奈' }).click();
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(2);
  await page.getByRole('button', { name: '上传表情包', exact: true }).click();
  await expect(page.locator('.emoji-file-drop')).toBeVisible();
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.locator('#modern-emoji-grid .modern-image-card')).toHaveCount(2);
  expect(errors).toEqual([]);
});
