import { test, expect } from '@playwright/test';

for (const theme of ['light', 'dark']) {
  test(`custom confirmation supports nested dialogs and keyboard in ${theme}`, async ({ page }) => {
    await page.route('http://127.0.0.1:18877/', route => route.fulfill({ contentType: 'text/html', body: '<html><head><meta charset="UTF-8"></head><body><dialog id="editor"><button id="trigger">删除</button></dialog></body></html>' }));
    await page.goto('/');
    await page.addStyleTag({ url: '/static/css/design-tokens.css' });
    await page.addScriptTag({ url: '/static/js/dialogs.js' });
    await page.setViewportSize({ width: 375, height: 700 });
    const nativeDialogs: string[] = [];
    page.on('dialog', async dialog => { nativeDialogs.push(dialog.type()); await dialog.dismiss(); });
    await page.evaluate(theme => {
      document.documentElement.dataset.theme = theme;
      (document.querySelector('#editor') as HTMLDialogElement).showModal();
      document.querySelector<HTMLButtonElement>('#trigger')!.onclick = async () => {
        const result = await window.PicManagerDialogs.confirm('确认删除？\n<img src=x onerror=alert(1)>');
        document.body.dataset.result = String(result);
      };
    }, theme);
    await page.locator('#trigger').click();
    const popup = page.getByRole('dialog', { name: '确认操作', exact: true });
    await expect(popup).toBeVisible();
    await expect(popup.locator('img')).toHaveCount(0);
    await expect(popup.getByRole('button', { name: '取消', exact: true })).toBeFocused();
    expect(await popup.evaluate(node => node.getBoundingClientRect().width)).toBeLessThan(375);
    await page.keyboard.press('Escape');
    await expect(page.locator('body')).toHaveAttribute('data-result', 'false');
    await expect(page.locator('#editor')).toBeVisible();
    await expect(page.locator('#trigger')).toBeFocused();
    await page.locator('#trigger').click();
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    await expect(page.locator('body')).toHaveAttribute('data-result', 'true');
    expect(nativeDialogs).toEqual([]);
  });
}

test('fallback keeps existing inert state and ignores duplicate decisions', async ({ page }) => {
  await page.route('http://127.0.0.1:18877/', route => route.fulfill({ contentType: 'text/html', body: '<html><head><meta charset="UTF-8"></head><body><main>内容</main><aside inert>隐藏内容</aside></body></html>' }));
  await page.goto('/');
  await page.addScriptTag({ url: '/static/js/dialogs.js' });
  await page.evaluate(() => {
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { value: undefined });
    void window.PicManagerDialogs.confirm('确认清理？').then(value => { document.body.dataset.result = String(value); });
  });
  expect(await page.evaluate(() => window.PicManagerDialogs.confirm('重复操作'))).toBe(false);
  await expect(page.locator('main')).toHaveAttribute('inert', '');
  await page.locator('[data-cancel]').click();
  await expect(page.locator('main')).not.toHaveAttribute('inert');
  await expect(page.locator('aside')).toHaveAttribute('inert', '');
  await expect(page.locator('body')).toHaveAttribute('data-result', 'false');
});
