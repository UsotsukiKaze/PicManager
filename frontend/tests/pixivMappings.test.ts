import { readFileSync } from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';

const source = readFileSync('../static/js/pixiv-ol.js', 'utf8');
const roles = [{ id: 10, name: '爱音', group_id: 1 }, { id: 11, name: '素世', group_id: 1 }];

function editor(evidence: object[] = []) {
  const runtime = window as unknown as Record<string, any>;
  runtime.PicManagerSecurity = { escapeHTML: (value: string) => String(value).replace(/</g, '&lt;') };
  runtime.auth = { isRoot: () => true };
  runtime.imageTagSelectors = {};
  class Selector {
    groups: any[] = [];
    characters: any[] = [];
    featureTags: any[] = [];
    value: any;
    setData(data: any) { this.groups = data.groups; this.characters = data.characters; this.featureTags = data.featureTags; }
    setSelected(value: any) { this.value = value; }
    getValue() { return this.value; }
    getLabel(kind: string, id: number) { return kind === 'group' ? 'MyGO' : roles.find(role => role.id === id)?.name; }
  }
  const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ saved: true }) }));
  new Function('window', 'document', 'ImageTagSelector', 'fetch', source)(runtime, document, Selector, fetcher);
  document.body.innerHTML = '<section id="reader"><div id="pixiv-cart-tag-selector"></div><div class="px-source-tags"></div><div class="px-tag-feedback"></div><div class="px-legacy-tags"></div></section>';
  const reader = document.getElementById('reader')!;
  const pol = runtime.pixivOL;
  const handle = pol.cartTagEditor(reader, { tags: [{ name: 'anosoyo' }], match: { evidence } },
    { group_ids: [1], character_ids: [10, 11], feature_tag_ids: [] },
    { data: { groups: [{ id: 1, name: 'MyGO' }], characters: roles, featureTags: [] } });
  return { reader, fetcher, handle };
}

afterEach(() => { document.body.innerHTML = ''; });

it('selects two roles together and saves them as one atomic association request', async () => {
  const { reader, fetcher, handle } = editor();
  reader.querySelector<HTMLButtonElement>('[data-source-index]')!.click();
  const popup = document.querySelector('dialog')!;
  const save = popup.querySelector<HTMLButtonElement>('[data-associate-save]')!;
  expect(save.disabled).toBe(true);
  popup.querySelector<HTMLButtonElement>('[data-target-index="1"]')!.click();
  popup.querySelector<HTMLButtonElement>('[data-target-index="2"]')!.click();
  expect(save.disabled).toBe(false);
  expect(popup.querySelectorAll('[aria-pressed="true"]')).toHaveLength(2);
  save.click();
  await vi.waitFor(() => expect(document.querySelector('dialog')).toBeNull());
  const [url, options] = fetcher.mock.calls[0] as unknown as [string, { body: string }];
  expect(url).toBe('/api/pixiv-ol/tag-mappings/batch');
  expect(JSON.parse(options.body).bindings).toEqual([
    { tag: 'anosoyo', target_type: 'character', target_id: 10 },
    { tag: 'anosoyo', target_type: 'character', target_id: 11 },
  ]);
  expect(reader.querySelector('.px-source-tags')!.textContent).toContain('爱音 + 素世');
  handle.destroy();
});

it('shows both saved associations on reopening and only adds the new target', async () => {
  const { reader, fetcher, handle } = editor([{ pixiv_tag: 'anosoyo', type: 'character', id: 10 }]);
  reader.querySelector<HTMLButtonElement>('[data-source-index]')!.click();
  const popup = document.querySelector('dialog')!;
  expect(popup.querySelector<HTMLButtonElement>('[data-target-index="1"]')!.disabled).toBe(true);
  popup.querySelector<HTMLButtonElement>('[data-target-index="2"]')!.click();
  popup.querySelector<HTMLButtonElement>('[data-associate-save]')!.click();
  await vi.waitFor(() => expect(document.querySelector('dialog')).toBeNull());
  expect(reader.querySelector('.px-source-tags')!.textContent).toContain('爱音 + 素世');
  const [, options] = fetcher.mock.calls[0] as unknown as [string, { body: string }];
  expect(JSON.parse(options.body).bindings).toHaveLength(1);
  reader.querySelector<HTMLButtonElement>('[data-source-index]')!.click();
  expect(document.querySelectorAll('dialog [data-target-index][disabled]')).toHaveLength(2);
  handle.destroy();
});

it('keeps the chooser and selections when saving fails, allowing a retry', async () => {
  const { reader, fetcher, handle } = editor();
  fetcher.mockResolvedValueOnce({ ok: false, json: async () => ({ detail: '保存失败' }) } as any);
  reader.querySelector<HTMLButtonElement>('[data-source-index]')!.click();
  const popup = document.querySelector('dialog')!;
  popup.querySelector<HTMLButtonElement>('[data-target-index="1"]')!.click();
  popup.querySelector<HTMLButtonElement>('[data-target-index="2"]')!.click();
  const save = popup.querySelector<HTMLButtonElement>('[data-associate-save]')!;
  save.click();
  await vi.waitFor(() => expect(popup.querySelector('.px-error')!.textContent).toBe('保存失败'));
  expect(popup.querySelectorAll('[aria-pressed="true"]')).toHaveLength(2);
  expect(save.disabled).toBe(false);
  save.click();
  await vi.waitFor(() => expect(document.querySelector('dialog')).toBeNull());
  expect(fetcher).toHaveBeenCalledTimes(2);
  handle.destroy();
});

it('allows confirming a suggested name match that has not yet been saved as a mapping', async () => {
  const { reader, fetcher, handle } = editor([{ pixiv_tag: 'anosoyo', type: 'character', id: 10, basis: 'name_or_alias' }]);
  reader.querySelector<HTMLButtonElement>('[data-source-index]')!.click();
  const popup = document.querySelector('dialog')!;
  const target = popup.querySelector<HTMLButtonElement>('[data-target-index="1"]')!;
  expect(target.disabled).toBe(false);
  target.click();
  popup.querySelector<HTMLButtonElement>('[data-associate-save]')!.click();
  await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  handle.destroy();
});
