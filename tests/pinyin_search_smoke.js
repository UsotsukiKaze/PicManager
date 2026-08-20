const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = {
    console,
    Map,
    setTimeout: callback => callback(),
    requestIdleCallback: callback => callback(),
};
context.window = context;
context.self = context;
context.globalThis = context;
vm.createContext(context);

for (const relativePath of [
    'static/vendor/pinyin-pro-3.29.2.min.js',
    'static/js/pinyin-search.js',
]) {
    vm.runInContext(fs.readFileSync(path.join(root, relativePath), 'utf8'), context, {
        filename: relativePath,
    });
}

const search = context.PinyinSearch;
assert.ok(search);
assert.equal(search.getStats().engineReady, true);

const expected = new Map([
    ['鸣潮', ['mingchao', 'mc']],
    ['蔚蓝档案', ['weilandangan', 'wlda']],
    ['崩坏·星穹铁道', ['benghuaixingqiongtiedao', 'bhxqtd']],
    ['绝区零', ['juequling', 'jql']],
    ['原神', ['yuanshen', 'ys']],
    ['虚拟歌姬', ['xunigeji', 'xngj']],
]);

for (const [name, [full, initials]] of expected) {
    assert.equal(search.getFullPinyin(name), full, `${name} full pinyin`);
    assert.equal(search.getPinyinInitials(name), initials, `${name} initials`);
    assert.equal(search.match(name, full), true, `${name} matches full pinyin`);
    assert.equal(search.match(name, initials), true, `${name} matches initials`);
}

assert.equal(search.match('东方Project', 'dfproject'), true);
assert.equal(search.match('', 'anything'), false);

const entities = [
    { id: 1, name: '原神话' },
    { id: 2, name: '原神' },
    { id: 3, name: '芙宁娜', nicknames: ['水神'] },
    { id: 4, name: '提瓦特', aliases: [{ alias: '原批' }] },
];
assert.deepEqual(search.filter(entities, '原神').map(item => item.id), [2, 1]);
assert.deepEqual(search.filter(entities, 'ss').map(item => item.id), [3]);
assert.deepEqual(search.filter(entities, 'yuanpi').map(item => item.id), [4]);

search.learnWords(Array.from(expected.keys()));
assert.ok(search.getStats().indexedWords >= expected.size);
