import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

test('login preserves a QR destination and rejects external redirects', async ({ page }) => {
  let loggedIn = false;
  const loginHTML = await readFile(new URL('../../../static/login.html', import.meta.url), 'utf8');
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/login') return route.fulfill({ contentType:'text/html', body:loginHTML });
    if (path === '/auth/guest') { loggedIn = true; return route.fulfill({ json:{ success:true } }); }
    if (path === '/auth/me') return route.fulfill(loggedIn ? { json:{ is_guest:true, guest_name:'测试游客' } } : { status:401,json:{ detail:'Login required' } });
    if (path === '/api/images/A123456789') return route.fulfill({ json:{ image_id:'A123456789',pid:'12345_p0',age_rating:'all',width:800,height:1200,characters:[],groups:[],feature_tags:[],pixiv_tags:[] } });
    if (path === '/api/images/search') return route.fulfill({ json:{ images:[],total:0 } });
    if (path.startsWith('/api/')) return route.fulfill({ json:[] });
    if (path.startsWith('/resource/')) return route.fulfill({ contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1200"/>' });
    return route.continue();
  });
  await page.goto('/#/gallery?image=A123456789');
  await expect(page).toHaveURL(/\/login\?redirect=/);
  await page.getByRole('button',{ name:'游客模式',exact:true }).click();
  await page.getByRole('button',{ name:'先进去看看',exact:true }).click();
  await expect(page.locator('dialog[open] h2')).toContainText('12345_p0');
  loggedIn = false;
  await page.goto('/login?redirect=https://evil.example');
  expect(await page.evaluate(() => (window as any).loginDestination())).toBe('/');
});

test('a gallery QR link opens the exact picture outside the current results', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith('/resource/')) return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1200"><rect width="800" height="1200" fill="#99aacc"/></svg>' });
    if (path === '/auth/me') return route.fulfill({ json: { is_guest: false, user: { id: 1, role: 'root', nickname: '测试' } } });
    if (path === '/api/images/A123456789') return route.fulfill({ json: { image_id: 'A123456789', pid: '12345_p0', age_rating: 'all', width: 800, height: 1200, characters: [], groups: [], feature_tags: [], pixiv_tags: [] } });
    if (path === '/api/images/search') return route.fulfill({ json: { images: [], total: 0, offset: 0, limit: 20 } });
    if (path.startsWith('/api/')) return route.fulfill({ json: [] });
    return route.continue();
  });
  await page.goto('/#/gallery?image=A123456789');
  await expect(page.locator('dialog[open]')).toBeVisible();
  await expect(page.locator('dialog h2')).toContainText('12345_p0');
  expect(errors).toEqual([]);
});
