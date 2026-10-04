const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function harness() {
    const timers = new Map();let nextTimer = 0;
    const context = vm.createContext({
        console, URL, window: { addEventListener() {} },
        document: { hidden: false, addEventListener() {}, querySelectorAll() { return []; }, getElementById() { return null; } },
        setTimeout(fn) { timers.set(++nextTimer, fn);return nextTimer; }, clearTimeout(id) { timers.delete(id); },
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../../static/js/ui.js'), 'utf8'), context);
    const ids = ['scan-pixiv-upgrades-button','pixiv-check-stop','pixiv-check-auto','pixiv-upgrade-progress',
        'pixiv-upgrade-progress-label','pixiv-upgrade-progress-count','pixiv-upgrade-progress-bar',
        'pixiv-upgrade-progress-detail','pixiv-check-review-queue'];
    const nodes = Object.fromEntries(ids.map(id => [id, {
        dataset: {}, hidden: false, checked: false, textContent: '', innerHTML: '',
        removeAttribute() {}, querySelectorAll() { return []; }, querySelector() { return null; },
    }]));
    context.document.getElementById = id => nodes[id] || null;
    context.ui = { currentPage: 'settings', isAdminView: () => true, showToast() {}, loadSystemStatus() {} };
    let data = { run: { id:'run',status:'running',total:4,workers:3,fingerprints:0,counts:{queued:2,review:1,completed:1},errors:[] },
        reviews:[{id:'review',pid:'101_p0',title:'Needs confirmation',page_count:2}],review_count:1 };
    const calls = [];
    context.api = {
        async startPixivCheckQueue() { calls.push('start');return {id:'run'}; },
        async getPixivCheckQueue() { calls.push('poll');return data; },
        async getPixivCheckReview(id) { calls.push(`review:${id}`);return {review_id:id}; },
        async stopPixivCheckQueue() { calls.push('stop');data.run.status='cancelled'; },
        async resolvePixivCheck() { calls.push('resolve');return {pid:'101_p0'}; },
    };
    return {context,nodes,calls,timers,setData(value) {data=value;},data};
}

test('background progress keeps polling while a review is open; defer never cancels scanning', async () => {
    const {context,nodes,calls,data} = harness();
    let defer;
    context.reviewPixivCheck = () => new Promise(resolve => {defer=resolve;});
    await context.scanPixivUpgrades();
    await new Promise(setImmediate);
    assert.equal(calls.filter(call => call==='start').length, 1);
    const reviewing = context.reviewQueuedPixivCheck('review');
    await new Promise(setImmediate);
    data.run.counts = {completed:3,review:1};
    await context.refreshPixivCheckQueue();
    assert.match(nodes['pixiv-upgrade-progress-count'].textContent, /4 \/ 4/);
    assert.match(nodes['pixiv-check-review-queue'].innerHTML, /Needs confirmation/);
    defer(null);
    await reviewing;
    await new Promise(setImmediate);
    assert.equal(calls.includes('stop'), false);
    assert.equal(calls.includes('resolve'), false);
    assert.equal(vm.runInContext("pixivCheckQueueState.deferred.has('review')",context), true);
});

test('refresh restores durable pending reviews without creating another scan', async () => {
    const {context,nodes,calls,data} = harness();
    data.run.status='completed';data.run.counts={completed:3,review:1};
    await context.refreshPixivCheckQueue();
    assert.equal(calls.includes('start'), false);
    assert.equal(nodes['scan-pixiv-upgrades-button'].disabled, false);
    assert.equal(nodes['pixiv-upgrade-progress'].dataset.state, 'review');
    assert.match(nodes['pixiv-check-review-queue'].innerHTML, /data-pixiv-review="review"/);
    assert.equal(vm.runInContext('pixivCheckQueueState.runId',context), 'run');
});

test('stop acts on the durable run and keeps its review list available', async () => {
    const {context,nodes,calls} = harness();
    await context.refreshPixivCheckQueue();
    await context.stopPixivCheckQueue();
    assert.equal(calls.filter(call => call==='stop').length, 1);
    assert.equal(nodes['pixiv-upgrade-progress'].dataset.state, 'stopped');
    assert.equal(nodes['pixiv-check-review-queue'].hidden, false);
    assert.match(nodes['pixiv-check-review-queue'].innerHTML, /Needs confirmation/);
});
