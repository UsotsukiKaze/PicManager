const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.resolve(__dirname, '..');
const context = vm.createContext({
    console,
    setTimeout,
    clearTimeout,
    URL,
    window: {
        addEventListener() {},
        PicManagerSecurity: {
            escapeHTML(value) { return String(value ?? ''); }
        }
    },
    document: {
        addEventListener() {},
        querySelectorAll() { return []; },
        getElementById() { return null; }
    }
});

for (const name of ['entity-cache.js', 'search-selector.js', 'image-list.js', 'modal.js', 'ui.js']) {
    const source = fs.readFileSync(path.join(root, 'static', 'js', name), 'utf8');
    vm.runInContext(source, context, { filename: name });
}

async function main() {
    const ui = context.window.ui;
    for (const method of ['loadCachedEntity', 'initializeSearchSelectors', 'loadImages', 'showModal']) {
        assert.equal(typeof ui[method], 'function', `${method} was not installed`);
    }

    let calls = 0;
    let release;
    const loader = () => {
        calls += 1;
        return new Promise(resolve => { release = resolve; });
    };
    const first = ui.loadCachedEntity('groups', loader);
    const second = ui.loadCachedEntity('groups', loader);
    await Promise.resolve();
    assert.equal(calls, 1, 'in-flight requests were not deduplicated');
    release([{ id: 1 }]);
    assert.deepEqual(await first, [{ id: 1 }]);
    assert.deepEqual(await second, [{ id: 1 }]);

    let releaseStale;
    const stale = ui.loadCachedEntity('characters', () => new Promise(resolve => { releaseStale = resolve; }));
    await Promise.resolve();
    ui.invalidateCache('characters');
    releaseStale([{ id: 2 }]);
    await stale;
    assert.equal(ui.dataCache.characters.data, null, 'invalidated stale response repopulated cache');
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
