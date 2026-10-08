import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const source = (file: string) => readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../../static', file), 'utf8');
const security = { escapeHTML: (value: unknown) => String(value ?? '') };

function pixiv() {
  const runtime: any = { PicManagerSecurity: security };
  const confirm = vi.fn(() => false);
  const fetch = vi.fn(async (_url: string, _options: any = {}): Promise<{ ok: boolean; json: () => Promise<any> }> => ({ ok: true, json: async () => ({ liked: false }) }));
  const ui = { showToast: vi.fn() };
  new Function('window', 'document', 'confirm', 'fetch', 'ui', source('js/pixiv-ol.js'))(runtime, document, confirm, fetch, ui);
  const pol = runtime.pixivOL;
  pol.updateRefreshButton = vi.fn();
  pol.loadCart = vi.fn(); pol.render = vi.fn(); pol.loadAccount = vi.fn(); pol.settings = vi.fn();
  pol.setLiked = vi.fn(); pol.watch = vi.fn();
  return { pol, confirm, fetch };
}

afterEach(() => { document.body.innerHTML = ''; });

it.each(['cart-remove', 'disconnect', 'resolve'])('cancelling %s leaves data and requests untouched; accepting submits once', async action => {
  const { pol, confirm, fetch } = pixiv();
  pol.account = { name: '画友' };
  pol.cartItems = [{ id: 'one', artwork: { title: '作品' } }];
  pol.selection.add('one');
  const button = document.createElement('button');
  Object.assign(button.dataset, { action, id: 'one', choice: 'merge_new' });
  if (action === 'resolve') button.dataset.id = '7';
  await pol.click({ target: button });
  expect(confirm).toHaveBeenCalledOnce();
  expect(fetch).not.toHaveBeenCalled();
  expect(pol.cartItems).toHaveLength(1);
  expect(pol.selection.has('one')).toBe(true);
  expect(pol.loadCart).not.toHaveBeenCalled();
  expect(button.disabled).toBe(false);
  confirm.mockReturnValue(true);
  await pol.click({ target: button });
  expect(fetch).toHaveBeenCalledOnce();
  expect(fetch.mock.calls[0][0]).toBe(`/api/pixiv-ol/${action === 'cart-remove' ? 'cart/one' : action === 'disconnect' ? 'account' : 'imports/7/resolve'}`);
});

it('cancelling unlike keeps the heart selected; adding a like needs no removal confirmation', async () => {
  const { pol, confirm, fetch } = pixiv();
  const button = document.createElement('button');
  button.setAttribute('aria-pressed', 'true');
  await pol.toggleLike('100', button);
  expect(fetch).not.toHaveBeenCalled(); expect(pol.setLiked).not.toHaveBeenCalled();
  expect(button.getAttribute('aria-pressed')).toBe('true');
  confirm.mockReturnValue(true);
  await pol.toggleLike('100', button);
  expect(pol.setLiked).toHaveBeenCalledWith('100', false);
  confirm.mockClear(); button.setAttribute('aria-pressed', 'false');
  await pol.toggleLike('100', button);
  expect(confirm).not.toHaveBeenCalled();
});

it('mapping cancellation preserves both targets; acceptance removes only the selected association', async () => {
  const { pol, confirm, fetch } = pixiv();
  const rows = [10, 11].map((id, index) => ({ id: index + 1, tag: 'anosoyo', target_type: 'character', target_id: id, source: 'manual' }));
  pol.entities = vi.fn(); pol.groups = []; pol.features = [];
  pol.characters = [{ id: 10, name: '爱音' }, { id: 11, name: '素世' }];
  fetch.mockImplementation(async (url: any, options: any = {}) => {
    if (options.method === 'DELETE') rows.splice(rows.findIndex(row => url.endsWith(`/${row.id}`)), 1);
    return { ok: true, json: async () => options.method === 'DELETE' ? {} : rows };
  });
  const saved = vi.fn();
  await pol.editMappings(null, null, '', [], saved);
  const button = document.querySelector<HTMLButtonElement>('[data-map-delete="1"]')!;
  fetch.mockClear(); button.click();
  expect(fetch).not.toHaveBeenCalled(); expect(saved).not.toHaveBeenCalled();
  expect(document.querySelectorAll('[data-map-delete]')).toHaveLength(2);
  confirm.mockReturnValue(true); button.click();
  await vi.waitFor(() => expect(document.querySelectorAll('[data-map-delete]')).toHaveLength(1));
  expect(rows.map(row => row.target_id)).toEqual([11]); expect(saved).toHaveBeenCalledOnce();
  expect(fetch.mock.calls.filter(([, options]: any[]) => options?.method === 'DELETE')).toHaveLength(1);
  const target = document.querySelector<HTMLSelectElement>('[data-map-target]')!;
  target.value = 'ignore:0'; document.querySelector<HTMLInputElement>('[data-map-tag]')!.value = 'anosoyo';
  confirm.mockReturnValue(false); fetch.mockClear();
  document.querySelector<HTMLButtonElement>('[data-map-save]')!.click();
  expect(fetch).not.toHaveBeenCalled(); expect(rows).toHaveLength(1);
});

it('removing an image tag or character prompts before changing selection or firing callbacks', () => {
  const runtime: any = { PicManagerSecurity: security };
  const confirm = vi.fn(() => false), changed = vi.fn();
  new Function('window', 'document', 'confirm', `${source('js/tag-selector.js')}\nwindow.Selector=ImageTagSelector;`)(runtime, document, confirm);
  const selector = Object.create(runtime.Selector.prototype);
  Object.assign(selector, { groups: [], characters: [], featureTags: [{ id: 2, name: '水着' }], selected: { group_ids: [], character_ids: [], feature_tag_ids: [2] }, render: vi.fn(), onChange: changed });
  selector.remove('feature_tag', 2);
  expect(selector.selected.feature_tag_ids).toEqual([2]); expect(changed).not.toHaveBeenCalled();
  confirm.mockReturnValue(true); selector.remove('feature_tag', 2);
  expect(selector.selected.feature_tag_ids).toEqual([]); expect(changed).toHaveBeenCalledOnce();
  new Function('window', 'document', 'confirm', `${source('js/character-selector.js')}\nwindow.Selector=CharacterSelector;`)(runtime, document, confirm);
  const character = Object.create(runtime.Selector.prototype);
  Object.assign(character, { selectedCharacters: [{ id: 10, name: '爱音' }], renderTags: vi.fn(), updateDropdown: vi.fn(), onChangeCallback: changed });
  confirm.mockReturnValue(false); changed.mockClear(); character.removeCharacter(10);
  expect(character.selectedCharacters).toHaveLength(1); expect(changed).not.toHaveBeenCalled();
  confirm.mockReturnValue(true); character.removeCharacter(10);
  expect(character.selectedCharacters).toHaveLength(0); expect(changed).toHaveBeenCalledWith([]);
});

it('batch clearing confirms once and keeps unfinished uploads; manual form clear can be cancelled', () => {
  const runtime: any = { imageTagSelectors: {} };
  const confirm = vi.fn(() => false), revoke = vi.fn();
  const script = source('js/upload.js').replace('window.upload = new UploadManager();', 'window.Manager=UploadManager;');
  new Function('window', 'document', 'confirm', 'URL', script)(runtime, document, confirm, { revokeObjectURL: revoke });
  const upload = Object.create(runtime.Manager.prototype);
  Object.assign(upload, { batchSubmitting: false, batchFiles: [{ id: 1, file: { name: 'done.png' }, status: 'success', previewUrl: 'blob:one' }, { id: 2, file: { name: 'pending.png' }, status: 'pending-review' }, { id: 3, file: { name: 'ready.png' }, status: 'ready' }], getBatchElement: () => null, updateBatchControls: vi.fn(), singleFile: { name: 'original.png' } });
  upload.clearSuccessfulBatchItems();
  expect(upload.batchFiles).toHaveLength(3); expect(revoke).not.toHaveBeenCalled();
  upload.removeBatchItem(1); expect(upload.batchFiles).toHaveLength(3);
  confirm.mockReturnValue(true); confirm.mockClear(); upload.clearSuccessfulBatchItems();
  expect(confirm).toHaveBeenCalledOnce(); expect(upload.batchFiles.map((item: any) => item.id)).toEqual([3]);
  expect(revoke).toHaveBeenCalledWith('blob:one');
  confirm.mockReturnValue(false); upload.clearSingleUpload(); expect(upload.singleFile.name).toBe('original.png');
  confirm.mockClear(); upload.clearSingleUpload(true);
  expect(upload.singleFile).toBeNull(); expect(confirm).not.toHaveBeenCalled();
});

it.each([['delete', 'approve', ''], ['group_delete', 'approve', ''], ['character_delete', 'approve', ''], ['duplicate_archive', 'approve', ''], ['add', 'reject', ''], ['add', 'approve', 'merge-new']])('review %s/%s waits for confirmation before a destructive action', async (type, action, duplicateKeep) => {
  const script = source('profile.html');
  const method = script.slice(script.indexOf('        async function handleRequest('), script.indexOf('        // 加载管理员列表'));
  const confirm = vi.fn(() => false), fetch = vi.fn(async () => ({ ok: true, json: async () => ({ message: '完成' }) }));
  document.body.innerHTML = `<article data-request-id="7" data-request-type="${type}" data-duplicate-keep="${duplicateKeep}"></article>`;
  const review = new Function('document', 'confirm', 'fetch', 'showToast', 'loadPendingRequests', `${method}\nreturn handleRequest;`)(document, confirm, fetch, vi.fn(), vi.fn());
  await review(7, action); expect(confirm).toHaveBeenCalledOnce(); expect(fetch).not.toHaveBeenCalled();
  confirm.mockReturnValue(true); await review(7, action); expect(fetch).toHaveBeenCalledOnce();
});

it('alias removal by click and Backspace can both be cancelled', () => {
  const runtime: any = {}, confirm = vi.fn(() => false);
  const ui = { escapeHomeRankingText: String };
  new Function('window', 'document', 'confirm', 'ui', source('js/workspace-shell.js'))(runtime, document, confirm, ui);
  document.body.innerHTML = '<form id="editor"><div class="form-group"><label>名称</label><input id="group-name"></div><div class="form-group"><label>别称</label><input id="group-aliases" value="a, b"></div><div class="form-actions"><button type="submit"></button><button type="button"></button></div></form>';
  runtime.PicManagerShell.enhanceTagEditor('editor', 'group', null);
  document.querySelector<HTMLButtonElement>('[data-alias-index="0"]')!.click();
  const entry = document.getElementById('group-aliases-entry')!;
  entry.dispatchEvent(new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true }));
  expect((document.getElementById('group-aliases') as HTMLInputElement).value).toBe('a, b');
  expect(confirm).toHaveBeenCalledTimes(2);
  confirm.mockReturnValue(true); entry.dispatchEvent(new KeyboardEvent('keydown', { key: 'Backspace', bubbles: true }));
  expect((document.getElementById('group-aliases') as HTMLInputElement).value).toBe('a');
});

it('cancelling emoji file or tag removal retains the editable draft', () => {
  const runtime: any = {}, confirm = vi.fn(() => false);
  new Function('window', 'document', 'confirm', source('js/emoji-library.js'))(runtime, document, confirm);
  const lib = runtime.emojiLibrary;
  lib.uploadTags.emotion_id = 1; lib.emotions = [{ id: 1, name: '开心' }];
  lib.uploadFile = { name: 'emoji.png' };
  lib.renderUploadTagControls = vi.fn(); lib.clearUploadFile = vi.fn();
  lib.clearUploadTag('emotion_id'); lib.removeUploadFile();
  expect(lib.uploadTags.emotion_id).toBe(1); expect(lib.uploadFile.name).toBe('emoji.png');
  expect(lib.renderUploadTagControls).not.toHaveBeenCalled(); expect(lib.clearUploadFile).not.toHaveBeenCalled();
  confirm.mockReturnValue(true); lib.clearUploadTag('emotion_id'); lib.removeUploadFile();
  expect(lib.uploadTags.emotion_id).toBeNull(); expect(lib.clearUploadFile).toHaveBeenCalledOnce();
});

it('clearing an emoji category in the picker prompts once and keeps the picker open on cancellation', () => {
  const runtime: any = {}, confirm = vi.fn(() => false), ui = { closeModal: vi.fn() };
  new Function('window', 'document', 'confirm', 'ui', source('js/emoji-library.js'))(runtime, document, confirm, ui);
  const lib = runtime.emojiLibrary;
  lib.uploadTags = { group_id: null, character_id: null, emotion_id: 1, function_id: 2 };
  lib.uploadPickerDraft = { group_id: null, character_id: null, emotion_id: null, function_id: null };
  lib.renderUploadTagControls = vi.fn();
  lib.confirmUploadTagPicker();
  expect(lib.uploadTags.emotion_id).toBe(1); expect(lib.uploadTags.function_id).toBe(2);
  expect(ui.closeModal).not.toHaveBeenCalled(); expect(lib.uploadPickerDraft).not.toBeNull();
  confirm.mockReturnValue(true); confirm.mockClear(); lib.confirmUploadTagPicker();
  expect(confirm).toHaveBeenCalledOnce(); expect(lib.uploadTags.emotion_id).toBeNull();
  expect(ui.closeModal).toHaveBeenCalledOnce();
});

it('restoring the default avatar waits for confirmation before clearing the custom association', () => {
  const script = source('js/ui.js');
  const method = script.slice(script.indexOf('    resetAvatarUpload('), script.indexOf('    openAvatarCropper('));
  const confirm = vi.fn(() => false);
  document.body.innerHTML = '<input id="group-avatar-url" value="/avatar.webp"><img id="group-avatar-preview" src="/avatar.webp">';
  const editor = new Function('document', 'confirm', `class Editor {${method}} return new Editor();`)(document, confirm);
  editor.resetAvatarUpload('group');
  expect((document.getElementById('group-avatar-url') as HTMLInputElement).value).toBe('/avatar.webp');
  expect(document.getElementById('group-avatar-preview')!.getAttribute('src')).toBe('/avatar.webp');
  confirm.mockReturnValue(true); editor.resetAvatarUpload('group');
  expect((document.getElementById('group-avatar-url') as HTMLInputElement).value).toBe('');
});

it('cancelling local cleanup sends no maintenance request and does not mark it running', async () => {
  const runtime: any = {}, confirm = vi.fn(() => false), request = vi.fn();
  document.body.innerHTML = '<button id="local-check-button"></button><button id="local-check-stop" hidden></button><p id="local-check-status">未开始</p>';
  new Function('window', 'document', 'confirm', 'auth', 'api', source('js/workspace-shell.js'))(runtime, document, confirm, { isAdmin: () => true }, { request });
  await runtime.runLocalValidation();
  expect(request).not.toHaveBeenCalled();
  expect((document.getElementById('local-check-button') as HTMLButtonElement).disabled).toBe(false);
  expect(document.getElementById('local-check-status')!.textContent).toBe('未开始');
});

it('cancelling merge keeps the comparison open; acceptance returns the selected keep file', async () => {
  const runtime: any = {}, confirm = vi.fn(() => false);
  document.body.innerHTML = '<section id="modal-body"></section>';
  const ui = {
    showModal: vi.fn((_title: string, html: string) => { document.getElementById('modal-body')!.innerHTML = `<section>${html}</section>`; }),
    closeModal: vi.fn(),
  };
  const script = source('js/upload.js').replace('window.upload = new UploadManager();', 'window.Manager=UploadManager;');
  new Function('window', 'document', 'confirm', 'ui', script)(runtime, document, confirm, ui);
  const upload = Object.create(runtime.Manager.prototype);
  upload.duplicateChoiceQueue = Promise.resolve();
  const choice = upload.resolveDuplicateChoice({ duplicates: [{ image_id: 'OLD1' }, { image_id: 'OLD2' }] });
  await vi.waitFor(() => expect(document.querySelector('[data-duplicate-action="confirm-merge"]')).not.toBeNull());
  const button = document.querySelector<HTMLButtonElement>('[data-duplicate-action="confirm-merge"]')!;
  button.click(); expect(ui.closeModal).not.toHaveBeenCalled();
  expect(document.querySelector('input[name="duplicate-file-keep"]:checked')).not.toBeNull();
  confirm.mockReturnValue(true); button.click();
  expect((await choice).keep).toBe('OLD1'); expect(ui.closeModal).toHaveBeenCalledOnce();
});
