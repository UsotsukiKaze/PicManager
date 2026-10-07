const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function client() {
    const context = vm.createContext({ window: {}, FormData, console });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../static/js/api.js'), 'utf8'), context);
    return context.window.api;
}

const file = new Blob(['synthetic image'], { type: 'image/png' });
const metadata = { character_ids: [], group_ids: [], feature_tag_ids: [] };

test('failed R2 PUT falls back once and skips direct upload on subsequent files', async () => {
    const api = client();
    const calls = [];
    api.request = async endpoint => {
        calls.push(endpoint);
        return endpoint.endsWith('prepare') ? { upload_url: 'https://r2.invalid', token: 'synthetic' } : { status: 'success' };
    };
    api.putFileWithProgress = async () => { throw new Error('synthetic PUT timeout'); };
    assert.equal((await api.uploadSingleImage(file, metadata)).status, 'success');
    assert.equal((await api.uploadSingleImage(file, metadata)).status, 'success');
    assert.deepEqual(calls, ['/upload/direct/prepare', '/upload/single', '/upload/single']);
});

test('lost finalize response does not retry through multipart', async () => {
    const api = client();
    const calls = [];
    api.putFileWithProgress = async () => {};
    api.request = async endpoint => {
        calls.push(endpoint);
        if (endpoint.endsWith('finalize')) throw new Error('synthetic finalize timeout');
        return { upload_url: 'https://r2.invalid', token: 'synthetic' };
    };
    await assert.rejects(api.uploadSingleImage(file, metadata), /synthetic finalize timeout/);
    assert.deepEqual(calls, ['/upload/direct/prepare', '/upload/direct/finalize']);
});
