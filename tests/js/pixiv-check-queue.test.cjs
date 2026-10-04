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
        insertAdjacentHTML(_position,value) {this.innerHTML+=value;},
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
    assert.match(nodes['pixiv-check-review-queue'].innerHTML, /data-start-reviews/);
    assert.doesNotMatch(nodes['pixiv-check-review-queue'].innerHTML, /data-pixiv-review/);
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

test('supplement duplicate jobs remain visible and can resume after review count reaches zero', async () => {
    const {context,nodes,calls,data}=harness();
    data.run.status='completed';data.reviews=[];data.review_count=0;
    data.imports=[{id:7,pid:'101',pages:[1],done:0,status:'awaiting_duplicate',page:1,duplicates:[{image_id:'0000000001'}]}];
    data.import_count=1;
    context.api.resolvePixivCheckImport=async(id,action)=>{calls.push(`duplicate:${id}:${action}`);data.imports=[];data.import_count=0;};
    await context.refreshPixivCheckQueue();
    assert.equal(nodes['pixiv-check-review-queue'].hidden,false);
    assert.match(nodes['pixiv-check-review-queue'].innerHTML,/需要查重确认/);
    assert.match(nodes['pixiv-check-review-queue'].innerHTML,/data-check-import="different"/);
    await context.actOnPixivCheckImport({dataset:{job:'7',checkImport:'different'},disabled:false});
    assert(calls.includes('duplicate:7:different'));
});

test('queue confirmation uses the saved modal result without submitting a second time', async () => {
    const {context,calls}=harness();
    context.reviewPixivCheck=async(result,onConfirm)=>{
        const choice={review_id:result.review_id,current_page:0,pages:[],upgrade:false};
        return {...choice,saved:await onConfirm(choice)};
    };
    await context.reviewQueuedPixivCheck('review');
    assert.equal(calls.filter(call=>call==='resolve').length,1);
});

test('failed checks are reported as partial completion and not a successful batch',async()=>{
    const {context,nodes,data}=harness();
    data.run.status='completed';data.run.counts={completed:3,failed:1};
    data.reviews=[];data.review_count=0;
    await context.refreshPixivCheckQueue();
    assert.equal(nodes['pixiv-upgrade-progress'].dataset.state,'partial');
    assert.match(nodes['pixiv-upgrade-progress-label'].textContent,/需重试/);
});

function continuousQueue(context,data,calls,total) {
    data.reviews=Array.from({length:total},(_,index)=>({id:`r${index}`,pid:`${100+index}`,page_count:2}));
    data.review_count=total;
    context.api.getPixivCheckQueue=async(_run,offset=0)=>{
        calls.push(`page:${offset}`);
        return {...data,reviews:data.reviews.slice(offset,offset+20),review_count:data.reviews.length};
    };
    context.api.resolvePixivCheck=async choice=>{
        calls.push(`saved:${choice.review_id}`);
        data.reviews=data.reviews.filter(row=>row.id!==choice.review_id);
        data.review_count=data.reviews.length;
        return {pid:choice.review_id};
    };
}

test('start processing confirms a whole queue including new arrivals without another click',async()=>{
    const {context,data,calls}=harness();continuousQueue(context,data,calls,23);
    let added=false;
    context.reviewPixivCheck=async(result,onConfirm)=>{
        assert.equal(result.queue_processing,true);
        if(!added){data.reviews.push({id:'new',pid:'200',page_count:2});added=true;}
        const choice={review_id:result.review_id,current_page:0,pages:[],upgrade:false};
        return {...choice,saved:await onConfirm(choice)};
    };
    await context.startProcessingPixivChecks();
    assert.equal(data.reviews.length,0);
    assert.equal(calls.filter(call=>call.startsWith('review:')).length,24);
    assert.equal(calls.filter(call=>call.startsWith('saved:')).length,24);
    assert.equal(calls.includes('stop'),false);
    assert.equal(vm.runInContext('pixivCheckQueueState.processing',context),false);
});

test('deferred reviews are skipped across pagination and offered again on the next start',async()=>{
    const {context,data,calls}=harness();continuousQueue(context,data,calls,22);
    context.reviewPixivCheck=async(result,onConfirm)=>{
        if(Number(result.review_id.slice(1))<20)return {deferred:true};
        const choice={review_id:result.review_id};return {...choice,saved:await onConfirm(choice)};
    };
    await context.startProcessingPixivChecks();
    assert.equal(calls.filter(call=>call.startsWith('review:')).length,22);
    assert.equal(data.reviews.length,20);
    assert(calls.includes('page:20'));
    assert.equal(calls.includes('stop'),false);
    context.reviewPixivCheck=async(result,onConfirm)=>{
        const choice={review_id:result.review_id};return {...choice,saved:await onConfirm(choice)};
    };
    await context.startProcessingPixivChecks();
    assert.equal(data.reviews.length,0);
});

test('closing pauses continuous processing and prevents automatic reopening',async()=>{
    const {context,nodes,data,calls}=harness();continuousQueue(context,data,calls,3);
    context.reviewPixivCheck=async()=>null;
    await context.startProcessingPixivChecks();
    nodes['pixiv-check-auto'].checked=true;data.reviews.forEach(row=>row.auto_review_safe=true);
    await context.refreshPixivCheckQueue();
    assert.equal(calls.filter(call=>call.startsWith('review:')).length,1);
    assert.equal(data.reviews.length,3);
    assert.equal(calls.includes('stop'),false);
});

test('double start cannot create two readers and a background stop prevents the next reader',async()=>{
    const {context,data,calls}=harness();continuousQueue(context,data,calls,3);
    let finish;
    context.reviewPixivCheck=()=>new Promise(resolve=>{finish=resolve;});
    const processing=context.startProcessingPixivChecks();
    await new Promise(setImmediate);
    await context.startProcessingPixivChecks();
    assert.equal(calls.filter(call=>call.startsWith('review:')).length,1);
    context.window.cancelPixivCheckReview=()=>finish(null);
    await context.stopPixivCheckQueue();
    await processing;
    assert.equal(calls.filter(call=>call.startsWith('review:')).length,1);
    assert.equal(data.reviews.length,3);
});

test('leaving settings while loading a review does not open its reader',async()=>{
    const {context,data,calls}=harness();continuousQueue(context,data,calls,2);
    let finish;
    context.api.getPixivCheckReview=id=>new Promise(resolve=>{calls.push(`review:${id}`);finish=resolve;});
    context.reviewPixivCheck=()=>{assert.fail('Reader must not open after leaving settings');};
    const processing=context.startProcessingPixivChecks();
    await new Promise(setImmediate);
    context.ui.currentPage='gallery';finish({review_id:'r0'});
    await processing;
    assert.equal(data.reviews.length,2);
    assert.equal(vm.runInContext('pixivCheckQueueState.processing',context),false);
});

test('load failure pauses without dropping reviews; restarting resumes',async()=>{
    const {context,data,calls}=harness();continuousQueue(context,data,calls,2);
    const original=context.api.getPixivCheckReview;
    context.api.getPixivCheckReview=async()=>{throw new Error('external_error');};
    await context.startProcessingPixivChecks();
    assert.equal(data.reviews.length,2);
    context.api.getPixivCheckReview=original;
    context.reviewPixivCheck=async(result,onConfirm)=>{
        const choice={review_id:result.review_id};return {...choice,saved:await onConfirm(choice)};
    };
    await context.startProcessingPixivChecks();
    assert.equal(data.reviews.length,0);
});
