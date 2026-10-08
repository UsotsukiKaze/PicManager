const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../static/js/emoji-library.js'), 'utf8');
const tags = [
    { id: 1, name: 'love' }, { id: 2, name: 'angry' },
    { id: 3, name: '#睡觉' }, { id: 4, name: '#摸头' },
];
const plain = value => JSON.parse(JSON.stringify(value));

function element() {
    return {
        innerHTML: '', value: '', handlers: {}, isConnected: true,
        addEventListener(name, handler) { this.handlers[name] = handler; },
        querySelectorAll() { return []; },
    };
}

function harness() {
    const ids = ['emoji-upload-tag-selector', 'emoji-upload-tag-picker', 'emoji-grid',
        'emoji-group-filter', 'emoji-character-filter', 'emoji-emotion-filter', 'emoji-function-filter'];
    const nodes = Object.fromEntries(ids.map(id => [id, element()]));
    const lists = Object.fromEntries(['group', 'character', 'emotion', 'function'].map(type => [type, element()]));
    const search = element();
    nodes['emoji-upload-tag-picker'].querySelector = selector => lists[selector.match(/"(.*?)"/)[1]];
    const ui = {
        modals: [], toasts: [],
        showModal(title, html) { this.modals.push({ title, html }); },
        closeModal() {}, showToast(message) { this.toasts.push(message); },
    };
    const api = {
        async getGroups() { return []; }, async getCharacters() { return []; },
        async getEmotionTags() { return tags; }, async getEmojiCharacters() { return []; },
    };
    const context = {
        window: {}, ui, api, console, confirm: () => true,
        document: { getElementById: id => nodes[id] || null, querySelector: () => search },
    };
    vm.runInNewContext(source, context);
    const lib = context.window.emojiLibrary;
    lib.emotions = tags;
    lib.initialized = true;
    return { lib, ui, api, nodes, lists };
}

test('picker retains one independent selection per category and clears either category', () => {
    const { lib, nodes, lists } = harness();
    lib.openUploadTagPicker();
    assert.match(lists.emotion.innerHTML, /love/);
    assert.doesNotMatch(lists.emotion.innerHTML, /#睡觉/);
    assert.match(lists.function.innerHTML, /#睡觉/);
    assert.doesNotMatch(lists.function.innerHTML, /love/);
    const choose = (type, id) => nodes['emoji-upload-tag-picker'].handlers.change({
        target: { tagName: 'INPUT', name: `emoji-picker-${type}`, value: String(id) },
    });
    choose('emotion', 1);
    choose('function', 3);
    choose('function', 4);
    lib.confirmUploadTagPicker();
    assert.deepEqual(plain(lib.selectedEmotionIds()), [1, 4]);
    lib.clearUploadTag('emotion_id');
    assert.deepEqual(plain(lib.selectedEmotionIds()), [4]);
    lib.openUploadTagPicker();
    choose('emotion', 2);
    choose('function', 0);
    lib.confirmUploadTagPicker();
    assert.deepEqual(plain(lib.selectedEmotionIds()), [2]);
});

test('editing unordered mixed tags preserves both, while function-only editing adds no base emotion', async () => {
    for (const selectedTags of [[tags[3], tags[0]], [tags[2]]]) {
        const { lib, api } = harness();
        api.getEmoji = async () => ({ emoji_id: 'TEST', emotions: selectedTags });
        let saved;
        api.updateEmoji = async (id, payload) => { saved = payload; };
        lib.refreshCharacterFacets = async () => {};
        lib.load = async () => {};
        await lib.showEditEmojiModal('TEST');
        await lib.saveEmojiInfo('TEST');
        assert.deepEqual(plain(saved.emotion_ids), selectedTags.length === 2 ? [1, 4] : [3]);
        if (selectedTags.length === 1) assert.equal(lib.uploadTags.emotion_id, null);
    }
});

test('upload submits a function alone or both categories', async () => {
    for (const base of [null, 1]) {
        const { lib, api } = harness();
        lib.uploadFile = { name: 'test.gif' };
        lib.uploadTags.emotion_id = base;
        lib.uploadTags.function_id = 4;
        let uploaded;
        api.uploadEmoji = async (file, payload) => { uploaded = payload; };
        lib.refreshCharacterFacets = async () => {};
        lib.load = async () => {};
        await lib.upload();
        assert.deepEqual(plain(uploaded.emotion_ids), base ? [1, 4] : [4]);
    }
});

test('filters separate catalogs and send both constraints together', async () => {
    const { lib, api, nodes } = harness();
    await lib.loadOptions();
    assert.match(nodes['emoji-emotion-filter'].innerHTML, /love/);
    assert.doesNotMatch(nodes['emoji-emotion-filter'].innerHTML, /#摸头/);
    assert.match(nodes['emoji-function-filter'].innerHTML, /#摸头/);
    assert.doesNotMatch(nodes['emoji-function-filter'].innerHTML, /love/);
    nodes['emoji-emotion-filter'].value = '1';
    nodes['emoji-function-filter'].value = '4';
    let query;
    api.searchEmojis = async params => { query = params; return { total: 0, emojis: [] }; };
    await lib.load();
    assert.equal(query.emotion_id, '1');
    assert.equal(query.function_id, '4');
});

test('cards show both labels, and details render each category separately', async () => {
    const { lib, api, nodes, ui } = harness();
    const emoji = { emoji_id: 'TEST', emotions: [tags[3], tags[0]] };
    lib.renderGrid([emoji]);
    assert.match(nodes['emoji-grid'].innerHTML, /love · #摸头/);
    api.getEmoji = async () => emoji;
    await lib.showEmojiDetail('TEST');
    const html = ui.modals.at(-1).html;
    assert.match(html, /detail-chip-emotion">love/);
    assert.match(html, /detail-chip-function">#摸头/);
});
