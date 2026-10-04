const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const callback = 'https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback?state=test&code=synthetic-code';
function harness() {
    const nodes = {};
    const dialog = {
        querySelector(selector) { return nodes[selector] ||= { value: '', hidden: false, focus() {} }; },
        showModal() {}, remove() {}, addEventListener() {},
    };
    const requests = [];
    const context = {
        URL, setTimeout, clearTimeout, window: { PicManagerSecurity: { escapeHTML: String } },
        document: { createElement: () => dialog, body: { appendChild() {} } },
        ui: { showToast() {} },
        async fetch(url, options) {
            requests.push({ url, body: JSON.parse(options.body) });
            return { ok: true, async json() { return {}; } };
        },
    };
    vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../static/js/pixiv-ol.js'), 'utf8'), context);
    context.window.pixivOL.initSettings = async () => {};
    return { pol: context.window.pixivOL, dialog, nodes, requests };
}

test('manual login recognizes Firefox colonless callback and copied browser addresses', () => {
    const { pol } = harness();
    for (const input of [callback, callback.replace('https:', 'https'), callback.replace('https://', ''), `“${callback}”`]) {
        assert.equal(pol.authorizationInput(input), callback);
    }
    assert.equal(pol.authorizationInput('pixiv://account/login?code=synthetic-code'), 'pixiv://account/login?code=synthetic-code');
    assert.equal(pol.authorizationInput('synthetic-code'), 'synthetic-code');
});

test('manual login refuses non-callback, misleading host and ambiguous or malformed code', () => {
    const { pol } = harness();
    for (const input of ['', callback.replace('/callback', '/start'), callback.replace('app-api.pixiv.net', 'evil.test'),
        callback.replace('app-api.pixiv.net', 'app-api.pixiv.net@evil.test'), callback + '&code=other', callback + '&code=', callback + '#fragment',
        callback.replace('app-api.pixiv.net', 'app-api.pixiv.net:8443'), callback.replace('synthetic-code', '%22'),
        callback + '\nextra text', 'code=synthetic-code']) {
        assert.throws(() => pol.authorizationInput(input));
    }
});

test('remote manual dialog submits a normalized callback instead of rejecting before request', async () => {
    const { pol, dialog, requests } = harness();
    pol.manualLogin({ id: 'synthetic-session', url: 'https://app-api.pixiv.net/web/v1/login', opened: false });
    dialog.querySelector('#pixiv-login-code').value = callback.replace('https:', 'https');
    const button = dialog.querySelector('#pixiv-login-complete');
    await button.onclick({ currentTarget: button });
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, '/api/pixiv-ol/account/login/synthetic-session/complete');
    assert.equal(requests[0].body.code, callback);
    assert.equal(dialog.querySelector('#pixiv-login-error').textContent, '');
});
