const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
function harness(fetch){
    const revoked=[];let next=0;
    const context={AbortController,setTimeout,clearTimeout,fetch,URL:{createObjectURL:()=>`blob:${++next}`,revokeObjectURL:url=>revoked.push(url)},window:{}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/pixiv-ol.js'),'utf8'),context);
    return {media:context.window.pixivOL.media,context,revoked};
}
const response=()=>({ok:true,blob:async()=>({type:'image/webp',size:1024})});
test('concurrent requests for one media key share a fetch and retain the decoded blob',async()=>{
    let resolve;const calls=[];
    const {media,revoked}=harness((url,options)=>{calls.push({url,options});return new Promise(done=>resolve=done);});
    const first=media.load('/preview'),second=media.load('/preview');assert.equal(first,second);
    resolve(response());assert.equal(await first,'blob:1');assert.equal(await media.load('/preview'),'blob:1');
    assert.equal(calls.length,1);assert.equal(media.bytes,1024);
    assert.equal(calls[0].options.credentials,'same-origin');media.clear();assert.deepEqual(revoked,['blob:1']);
});
test('account cache clear aborts pending downloads and releases completed blobs',async()=>{
    let signal;
    const {media,revoked}=harness((url,options)=>url==='/ready'?Promise.resolve(response()):new Promise((_resolve,reject)=>{
        signal=options.signal;signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true});
    }));
    await media.load('/ready');const pending=media.load('/pending');
    media.clear();assert(signal.aborted);await assert.rejects(pending,/aborted/);
    assert.equal(media.entries.size,0);assert.equal(media.bytes,0);assert.deepEqual(revoked,['blob:1']);
});
test('late failure from an old account cannot evict the new account request',async()=>{
    let rejectOld,resolveNew,calls=0;
    const {media}=harness(()=>++calls===1?new Promise((_resolve,reject)=>rejectOld=reject):new Promise(resolve=>resolveNew=resolve));
    const old=media.load('/same');media.clear();const current=media.load('/same');
    rejectOld(new Error('old'));await assert.rejects(old,/old/);assert.equal(media.entries.size,1);
    resolveNew(response());assert.equal(await current,'blob:1');media.clear();
});
