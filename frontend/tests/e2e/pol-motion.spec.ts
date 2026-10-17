import { test, expect, type Page } from '@playwright/test';

async function fixture(page: Page, options: { slowAccount?: boolean; slowRecommendations?: boolean; dark?: boolean; activeJob?: boolean } = {}) {
  const errors: string[] = [], modes: string[] = [], writes: string[] = [];
  let releaseRecommendations!: () => void;
  const recommendationGate = new Promise<void>(resolve => { releaseRecommendations = resolve; });
  let cart: any[] = [];
  const art = (id: number, mode = 'personal') => ({ pid: String(id), title: `${mode}画作${id}`, author: '测试画师', author_id: '9', page_count: 1, preview_url: '/static/icon/Pic.png', author_avatar_url: '/static/icon/Pic.png', imported_pages: [], tags: [], match: { group_ids: [], character_ids: [], feature_tag_ids: [], conflicts: [], evidence: [] } });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(dark => {
    localStorage.setItem('picmanager.appearance', JSON.stringify({ theme: dark ? 'dark' : 'light', reduced: false }));
    (window as any).polWipes = [];
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
      if (node instanceof Element && node.matches('.pol-title-exit')) (window as any).polWipes.push(node.textContent);
    }))).observe(document, { childList: true, subtree: true });
  }, options.dark || false);
  await page.route('**/*', async route => {
    const url = new URL(route.request().url()), path = url.pathname, method = route.request().method();
    if (!path.startsWith('/api/') && !path.startsWith('/auth/')) { await route.continue(); return; }
    if (/\/artworks\/\d+\/(reader-preview|avatar)/.test(path)) {
      await route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="800"><rect width="600" height="800" fill="#abc4df"/><circle cx="350" cy="300" r="180" fill="#e4bfd1"/></svg>' }); return;
    }
    let body: unknown = {};
    if (path === '/auth/me') body = { is_guest: false, user: { id: 1, role: 'root', nickname: '测试用户' } };
    else if (path === '/auth/notifications') body = { approved: 0, rejected: 0 };
    else if (/\/api\/(groups|characters|feature-tags|emotion-tags)\/$/.test(path) || path === '/api/groups/popular') body = [];
    else if (path === '/api/system/status') body = { total_images: 20, total_groups: 0 };
    else if (path === '/api/images/search') body = { images: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/emojis/search') body = { emojis: [], total: 0, limit: 20, offset: 0 };
    else if (path === '/api/emojis/characters') body = [];
    else if (path === '/api/upload/capabilities') body = { max_file_size: 52428800, extensions: ['png'] };
    else if (path === '/api/pixiv-ol/account') {
      if (options.slowAccount) await new Promise(resolve => setTimeout(resolve, 1000));
      body = { connected: true, user_id: '7', name: '测试画友', media_revision: 'test' };
    } else if (path === '/api/pixiv-ol/cart' || path === '/api/pixiv-ol/cart/refresh-tags') {
      if (method === 'POST' && path.endsWith('/cart')) {
        const pid = route.request().postDataJSON().pid; writes.push(pid);
        if (pid === '1001') { await route.fulfill({ status: 400, json: { detail: 'cache_full' } }); return; }
        cart = [...cart, { id: 'cart-' + pid, status: 'ready', bytes: 12345, artwork: art(Number(pid)), preview_url: '/static/icon/Pic.png', pages: [0], cached_pages: [0], draft: { pages: [0], group_ids: [], character_ids: [], feature_tag_ids: [], new_tags: [], confirmed_pages: [], import_mode: 'merged' } }];
      }
      body = { items: cart };
    } else if (path === '/api/pixiv-ol/recommendations') {
      if (options.slowRecommendations) await recommendationGate;
      const mode = url.searchParams.get('mode') || 'personal'; modes.push(mode);
      body = { batch_id: mode + '-batch', total: 20, next_offset: 20, has_more: false, items: Array.from({ length: 20 }, (_, i) => art(1000 + i, mode)) };
    } else if (path === '/api/pixiv-ol/jobs') body = options.activeJob ? [{ id: 1, kind: 'import', status: 'running', pid: '999', title: '后台入库' }] : [];
    else if (path === '/api/pixiv-ol/library-status' || path === '/api/pixiv-ol/similarity' || path === '/api/pixiv-ol/bookmarks/states') body = { items: [] };
    else if (path === '/api/pixiv-ol/bookmarks/status') body = { enabled: false };
    await route.fulfill({ json: body });
  });
  return { errors, modes, writes, releaseRecommendations };
}
async function settle(page: Page) {
  await page.evaluate(() => document.getAnimations().filter(animation => animation.id.startsWith('pol-')).forEach(animation => animation.finish()));
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-title', 'idle');
}
async function enter(page: Page) {
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await expect(page.locator('.px-card')).toHaveCount(20);
}

test('reader opens and loads preview before library status finishes', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/pixiv');
  await expect(page.locator('.px-card')).toHaveCount(20);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/pixiv-ol/library-status?**', async route => {
    await gate;
    await route.fulfill({ json: { items: [{ pid: '1000', imported_pages: [0] }] } });
  });
  await page.locator('.px-card').first().locator('[data-action=detail]').first().click();
  const reader = page.locator('.px-artwork-reader');
  await expect(reader).toBeVisible({ timeout: 1500 });
  await expect(reader.locator('.px-detail-cover')).toHaveClass(/is-ready/);
  await expect(reader.locator('#pixiv-draft-submit')).toBeDisabled();
  release();
  await expect(reader.locator('#pixiv-draft-submit')).toHaveText('已入库');
  await expect(reader.locator('#pixiv-draft-submit')).toBeDisabled();
  await reader.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(reader).toHaveCount(0);
  expect(mock.errors).toEqual([]);
});

test('all sources use the icon push while marquee and center-expanding tools enter together', async ({ page }, info) => {
  const mock = await fixture(page, { activeJob: true });
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/#/gallery');
  await expect(page.locator('.section-film-title')).toBeVisible();
  await enter(page);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-source', '/gallery');
  expect(await page.evaluate(() => (window as any).polWipes)).toEqual([]);
  const clocks = await page.evaluate(() => {
    const animations = document.getAnimations().filter(animation => animation.id.startsWith('pol-'));
    const starts = Object.fromEntries(animations.map(animation => [animation.id, animation.startTime]));
    animations.forEach(animation => animation.pause()); return starts;
  });
  expect(typeof clocks['pol-mode-marquee']).toBe('number');
  expect(clocks['pol-mode-marquee']).toBe(clocks['pol-tools-unfold']);
  expect(Math.abs(Number(clocks['pol-push-title']) - Number(clocks['pol-tools-unfold']))).toBeLessThan(320);
  const sample = async (time: number) => page.evaluate(async milliseconds => {
    document.getAnimations().filter(animation => animation.id.startsWith('pol-')).forEach(animation => { animation.currentTime = milliseconds; });
    await new Promise(requestAnimationFrame);
    return [...document.querySelectorAll('.px-floating-actions button')].map(button => { const box = button.getBoundingClientRect(); return { x: box.x, y: box.y }; });
  }, time);
  const compact = await sample(80), expanded = await sample(560);
  await expect(page.getByRole('button', { name: '入库进度', exact: true })).toBeVisible();
  expect(Math.max(...compact.map(point => point.y)) - Math.min(...compact.map(point => point.y)), JSON.stringify({ compact, expanded })).toBeLessThan(1);
  expect(Math.max(...compact.map(point => point.x)) - Math.min(...compact.map(point => point.x))).toBeLessThan(1);
  expect(Math.max(...expanded.map(point => point.x)) - Math.min(...expanded.map(point => point.x))).toBeLessThan(1);
  expect(expanded[2]!.y - expanded[0]!.y).toBeGreaterThan(60);
  const shell = await page.locator('.pol-tools-shell').boundingBox();
  const refresh = await page.locator('.px-floating-actions [data-action=refresh]').boundingBox();
  expect(Math.abs(shell!.y + shell!.height / 2 - refresh!.y - refresh!.height / 2)).toBeLessThan(1);
  await sample(608);
  const dotScale = await page.locator('.px-floating-cart').evaluate(element => new DOMMatrixReadOnly(getComputedStyle(element).transform).a);
  expect(dotScale).toBeCloseTo(1.06, 2);
  await page.screenshot({ path: info.outputPath('pol-entrance-light.png') });
  await settle(page);
  expect(mock.modes).toEqual(['personal']); expect(mock.errors).toEqual([]);
});

test('marquee wraps, lights the passing label and lands on a clicked mode without cycling requests', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/pixiv'); await expect(page.locator('.px-card')).toHaveCount(20);
  const toolsEpoch = await page.evaluate(() => {
    const animations = document.getAnimations().filter(animation => animation.id.startsWith('pol-'));
    const start = animations.find(animation => animation.id === 'pol-tools-unfold')!.startTime;
    animations.forEach(animation => animation.pause()); return start;
  });
  for (const [time, expected] of [[0, 0], [266, 1], [421, 2], [690, 0]]) {
    const lit = await page.evaluate(async milliseconds => {
      document.getAnimations().filter(animation => animation.id.startsWith('pol-mode-')).forEach(animation => { animation.currentTime = milliseconds!; });
      await new Promise(requestAnimationFrame);
      return [...document.querySelectorAll('.px-mode-switch button')].map(button => Number(getComputedStyle(button).opacity));
    }, time);
    expect(lit.indexOf(Math.max(...lit))).toBe(expected);
  }
  const before = await page.evaluate(async () => {
    document.getAnimations().filter(animation => animation.id.startsWith('pol-mode-')).forEach(animation => { animation.currentTime = 520; });
    await new Promise(requestAnimationFrame);
    const rail = document.querySelector('.pol-mode-track')!.getBoundingClientRect();
    const frames = [...document.querySelectorAll('.pol-mode-track .px-mode-indicator')].map(element => element.getBoundingClientRect());
    return { wraps: frames.every(box => box.right > rail.left && box.left < rail.right),
      position: new DOMMatrixReadOnly(getComputedStyle(document.querySelector('.pol-mode-track .px-mode-indicator')!).transform).m41 / parseFloat(getComputedStyle(document.querySelector('.pol-mode-track .px-mode-indicator')!).width) % 3 };
  });
  expect(before.wraps).toBe(true);
  await page.getByRole('button', { name: 'Pixiv 发现', exact: true }).click();
  await expect(page.locator('.px-gallery')).toContainText('discovery画作');
  const landing = await page.evaluate(() => {
    const motion = document.getAnimations().find(animation => animation.id === 'pol-mode-select')!;
    return { duration: motion.effect!.getTiming().duration,
      start: new DOMMatrixReadOnly(String((motion.effect as KeyframeEffect).getKeyframes()[0]!.transform)).m41 / parseFloat(getComputedStyle(document.querySelector('.pol-mode-track .px-mode-indicator')!).width),
      toolsEpoch: document.getAnimations().find(animation => animation.id === 'pol-tools-unfold')?.startTime };
  });
  expect(landing.duration).toBe(320);
  expect(landing.start).toBeCloseTo(before.position, 2);
  expect(landing.toolsEpoch).toBe(toolsEpoch);
  await settle(page);
  await expect(page.locator('.px-mode-switch [data-mode=discovery]')).toHaveAttribute('aria-pressed', 'true');
  expect(mock.modes).toEqual(['personal', 'discovery']); expect(mock.errors).toEqual([]);
});

test('home uses only the icon push and mode changes preserve reading without replaying entry', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/'); await expect(page.locator('.archive-home')).toBeVisible();
  await enter(page); await settle(page);
  expect(await page.evaluate(() => (window as any).polWipes)).toEqual([]);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-source', '/');
  await page.getByRole('button', { name: 'Pixiv 发现', exact: true }).click();
  await expect(page.locator('.px-gallery')).toContainText('discovery画作');
  await expect(page.locator('.pol-mode-running')).toHaveCount(0);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-title', 'idle');
  await page.getByRole('button', { name: '猜你喜欢', exact: true }).click();
  await expect(page.locator('.px-gallery')).toContainText('personal画作');
  expect(mock.modes).toEqual(['personal', 'discovery']);
  await page.getByRole('link', { name: '表情包库', exact: true }).click();
  await expect(page.locator('.modern-emoji')).toBeVisible();
  await enter(page);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-entry', 'full');
  await expect(page.locator('.pol-mode-running')).toHaveCount(1);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-tools', 'unfolding');
  await settle(page);
  expect(mock.errors).toEqual([]);
});

test('cart and heart feedback follow successful writes, reader shrinks back and restores focus', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/pixiv'); await expect(page.locator('.px-card')).toHaveCount(20); await settle(page);
  const first = page.locator('.px-card').filter({ has: page.locator('[data-pid="1000"]') });
  await first.hover();
  await first.getByRole('button', { name: '喜欢', exact: true }).click();
  await expect(first.locator('.pol-like-ring')).toBeAttached();
  await first.getByRole('button', { name: '加入优选夹', exact: true }).click();
  await expect(page.locator('.px-cart-count')).toHaveText('1');
  await expect(page.locator('.pol-cart-flight')).toBeVisible();
  await settle(page);
  const rejected = page.locator('.px-card').filter({ has: page.locator('[data-pid="1001"]') });
  await rejected.getByRole('button', { name: '加入优选夹', exact: true }).click();
  await expect(page.locator('.modern-toasts')).toContainText('暂存空间已满');
  await expect(page.locator('.px-cart-count')).toHaveText('1');
  await expect(page.locator('.pol-cart-flight')).toHaveCount(0);
  const source = page.locator('.px-image-button[data-pid="1002"]');
  await source.click(); await expect(page.locator('.px-artwork-reader')).toBeVisible();
  await expect(page.locator('.px-detail-cover')).toHaveClass(/is-ready/);
  await page.keyboard.press('Escape');
  await expect(page.locator('.px-artwork-reader')).toHaveCount(0); await expect(source).toBeFocused();
  await page.locator('.px-cart-button').click(); await expect(page.locator('.px-cart-row')).toHaveCount(1);
  await page.getByRole('button', { name: '继续发现', exact: true }).click();
  await expect(page.locator('.px-card:visible')).toHaveCount(19);
  expect(mock.writes).toEqual(['1000', '1001']); expect(mock.errors).toEqual([]);
});

test('slow cold start shows title immediately and leaving cancels its motion and late rendering', async ({ page }) => {
  const mock = await fixture(page, { slowAccount: true });
  await page.goto('/#/gallery'); await expect(page.locator('.section-film-title')).toBeVisible();
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-title', 'pushing');
  await expect(page.locator('.px-card')).toHaveCount(0);
  await page.getByRole('link', { name: '表情包库', exact: true }).click();
  await expect(page.locator('.modern-emoji')).toBeVisible();
  await expect(page.locator('.pol-title-exit,.pol-cart-flight')).toHaveCount(0);
  expect(await page.evaluate(() => document.getAnimations().filter(animation => animation.id.startsWith('pol-')).length)).toBe(0);
  expect(mock.modes).toEqual([]); expect(mock.errors).toEqual([]);
});

test('mobile dark tools fit the viewport and reduced motion keeps all controls usable', async ({ page }, info) => {
  const mock = await fixture(page, { dark: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#/pixiv'); await expect(page.locator('.px-card')).toHaveCount(20); await settle(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1);
  const tools = await page.locator('.px-floating-tools').boundingBox();
  expect(tools!.x).toBeGreaterThanOrEqual(0); expect(tools!.x + tools!.width).toBeLessThanOrEqual(390);
  await page.screenshot({ path: info.outputPath('pol-mobile-dark.png') });
  await page.emulateMedia({ reducedMotion: 'reduce' }); await page.reload();
  await expect(page.locator('.px-card')).toHaveCount(20);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-title', 'idle');
  expect(await page.evaluate(() => document.getAnimations().filter(animation => animation.id.startsWith('pol-')).length)).toBe(0);
  await page.getByRole('combobox', { name: '推荐方式', exact: true }).selectOption('stock');
  await expect(page.locator('.px-gallery')).toContainText('stock画作');
  expect(mock.errors).toEqual([]);
});

test('cross-page handoff holds the heading baseline and replaces loading cards without a gap', async ({ page }) => {
  const mock = await fixture(page, { slowRecommendations: true });
  await page.goto('/#/gallery'); await expect(page.locator('.section-film-title')).toBeVisible();
  await page.evaluate(() => {
    (window as any).polBaselines = [];
    (window as any).polRecording = true;
    const sample = () => {
      if (!(window as any).polRecording) return;
      const header = document.querySelector<HTMLElement>('#pixiv-ol-root .px-header');
      if (header && header.getBoundingClientRect().width) (window as any).polBaselines.push(header.getBoundingClientRect().top);
      requestAnimationFrame(sample);
    };
    requestAnimationFrame(sample);
  });
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await expect(page.locator('.pol-loading-card')).toHaveCount(10);
  await expect(page.locator('.px-gallery')).toHaveAttribute('aria-busy', 'true');
  mock.releaseRecommendations();
  await expect(page.locator('.px-card')).toHaveCount(20);
  await expect(page.locator('.pol-loading-card')).toHaveCount(0);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-title', 'idle');
  const baselines = await page.evaluate(() => { (window as any).polRecording = false; return (window as any).polBaselines as number[]; });
  expect(baselines.length).toBeGreaterThan(10);
  expect(Math.max(...baselines) - Math.min(...baselines)).toBeLessThan(1);
  expect(await page.evaluate(() => document.getAnimations().filter(animation => animation.id === 'pol-page-out' || animation.id === 'pol-page-in').length)).toBe(0);
  expect(mock.modes).toEqual(['personal']); expect(mock.errors).toEqual([]);
});

test('leaving while POL assets warm keeps the next page visible and cancels the handoff', async ({ page }) => {
  const mock = await fixture(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  let requested!: () => void;
  const warming = new Promise<void>(resolve => { requested = resolve; });
  await page.route('**/static/js/pixiv-ol.js?*', async route => { requested(); await gate; await route.continue(); });
  await page.goto('/#/gallery'); await expect(page.locator('.section-film-title')).toBeVisible();
  await page.getByRole('link', { name: 'Pixiv-ol', exact: true }).click();
  await warming;
  await expect(page.locator('.modern-gallery')).toBeVisible();
  await expect(page.locator('#workspace-scroll')).toHaveCSS('opacity', '1');
  await page.getByRole('link', { name: '表情包库', exact: true }).click();
  await expect(page.locator('.modern-emoji')).toBeVisible();
  const loaded = page.waitForResponse(response => response.url().includes('/static/js/pixiv-ol.js'));
  release(); await loaded;
  await expect(page.locator('#workspace-scroll')).toHaveCSS('opacity', '1');
  await expect(page.locator('#page-pixiv-ol')).not.toBeVisible();
  expect(mock.modes).toEqual([]); expect(mock.errors).toEqual([]);
});

test('settings hands its legacy view over to POL without hiding the new header', async ({ page }) => {
  const mock = await fixture(page);
  await page.goto('/#/settings'); await expect(page.locator('#page-settings')).toBeVisible();
  await enter(page);
  await expect(page.locator('#pixiv-ol-root')).toHaveAttribute('data-pol-source', '/settings');
  await settle(page);
  await expect(page.locator('.px-heading')).toBeVisible();
  await expect(page.locator('#page-settings')).not.toBeVisible();
  expect(mock.errors).toEqual([]);
});
