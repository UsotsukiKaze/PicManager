const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const {test}=require('node:test');
function harness(){
    const calls=[],status={textContent:''},button={},window={addEventListener(){},auth:{}},context={window,console,AbortController,setTimeout,clearTimeout,URL,Map,Set,
        document:{getElementById:id=>id==='temp-precheck-status'?status:id==='temp-import-selected'?button:null,querySelectorAll:()=>[]},
        ui:{currentPage:'upload',currentTab:'temp-upload',showToast(){},closeModal(){},async updateTempCount(){},loadSystemStatus(){}},
        api:{request:async()=>({run_id:'run'}),uploadTempImage:async()=>({status:'success'})},fetch:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return {};}};
    const source=fs.readFileSync(path.join(__dirname,'../../static/js/upload.js'),'utf8').replace('window.upload = new UploadManager();','window.UploadManager = UploadManager;');
    vm.runInNewContext(source,context);window.UploadManager.prototype.initializeEventListeners=()=>{};
    const upload=new window.UploadManager();upload.updateTempCard=()=>{};upload.tempActive=true;upload.tempNames=['a','b'];
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/temp-upload.js'),'utf8'),context);
    return {upload,context,calls,status,button,workbench:new window.TempUploadWorkbench(upload)};
}
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}

test('temp files default unchecked and multipage character suggestions remain per-file',()=>{
    const {upload,workbench}=harness();assert.equal(upload.tempSelection.size,0);
    const art={page_count:2,match:{group_ids:[1],character_ids:[1,2],feature_tag_ids:[3]}};
    const draft=workbench.matchedDraft({artwork:art,pid:'12345678_p0'});
    assert.equal(draft.character_ids.length,0);assert.deepEqual(Array.from(draft.group_ids),[1]);assert.equal(draft.confirmed,false);
    art.page_count=1;assert.equal(workbench.matchedDraft({artwork:art}).character_ids.length,2);
});

test('navigation while session start is pending stops the late run without checking files',async()=>{
    const {upload,context,calls}=harness(),start=deferred();
    context.api.request=()=>start.promise;
    const running=upload.precheckTemp(upload.tempGeneration,new AbortController());
    upload.suspendTemp();start.resolve({run_id:'late'});await running;
    assert(calls.some(call=>call.body.run_id==='late'));assert.equal(upload.tempResults.size,0);
});

test('leaving temp aborts the active request and prevents queue continuation and late results',async()=>{
    const {upload,context,calls}=harness(),pending=deferred(),checks=[];
    context.api.request=async(url,options)=>{if(url.endsWith('/start'))return {run_id:'running'};checks.push(options);return pending.promise;};
    const controller=upload.tempAbort=new AbortController(),running=upload.precheckTemp(upload.tempGeneration,controller);
    await new Promise(resolve=>setImmediate(resolve));assert.equal(checks.length,1);
    assert.equal(checks[0].headers['Content-Type'],'application/json');assert.equal(checks[0].headers['X-Pixiv-OL'],'1');
    upload.suspendTemp();assert(controller.signal.aborted);
    pending.resolve({filename:'a',status:'verified'});await running;
    assert.equal(checks.length,1);assert.equal(upload.tempResults.size,0);assert(calls.some(call=>call.body.run_id==='running'));
});

test('old file list cannot render after navigation',async()=>{
    const {upload,context}=harness(),pending=deferred();let rendered=0;
    upload.renderTempImages=()=>rendered++;context.api.request=()=>pending.promise;
    const loading=upload.loadTempImages();upload.suspendTemp();pending.resolve({images:['old']});await loading;
    assert.equal(rendered,0);
});

test('preflight preserves list order and publishes each result before the remaining queue completes',async()=>{
    const {upload,context}=harness(),pending=deferred(),checked=[],published=[];
    upload.tempNames=['ordinary.png','12345678_p0.png'];
    upload.updateTempCard=name=>published.push(name);
    context.api.request=async(url,options)=>{
        if(url.endsWith('/start'))return {run_id:'ordered'};
        const name=JSON.parse(options.body).filename;checked.push(name);
        return name==='ordinary.png'?{filename:name,status:'ordinary'}:pending.promise;
    };
    const running=upload.precheckTemp(upload.tempGeneration,new AbortController());
    await new Promise(resolve=>setImmediate(resolve));
    assert.deepEqual(checked,['ordinary.png','12345678_p0.png']);
    assert.deepEqual(published,['ordinary.png']);assert(upload.tempResults.has('ordinary.png'));
    pending.resolve({filename:'12345678_p0.png',status:'verified'});await running;
    assert.deepEqual(published,['ordinary.png','12345678_p0.png']);
});

test('batch submission clears selection immediately and continues in the upload dock after navigation',async()=>{
    const {upload,context}=harness(),pending=deferred(),tasks=[],updates=[];
    upload.tempDrafts.set('a',{filename:'a',confirmed:true});upload.tempSelection.add('a');
    context.window.uploadQueue={add:task=>{tasks.push(task);return 1;},update:(_id,update)=>updates.push(update)};
    context.api.uploadTempImage=()=>pending.promise;
    const importing=upload.importTempSelected();assert.equal(upload.tempSelection.size,0);assert(upload.tempUploading.has('a'));assert.equal(tasks.length,1);
    upload.suspendTemp();pending.resolve({status:'success',message:'done'});await importing;
    assert(!upload.tempDrafts.has('a'));assert(!upload.tempUploading.has('a'));assert(updates.some(update=>update.status==='success'));
});

test('failed import restores the confirmed draft and selection with a dock retry',async()=>{
    const {upload,context}=harness(),updates=[];upload.tempActive=false;
    upload.tempDrafts.set('a',{filename:'a',confirmed:true});upload.tempSelection.add('a');
    context.window.uploadQueue={add:()=>7,update:(_id,value)=>updates.push(value)};
    context.api.uploadTempImage=async()=>{throw new Error('network');};
    await upload.importTempSelected();assert(upload.tempSelection.has('a'));assert(upload.tempDrafts.get('a').confirmed);
    assert.equal(typeof updates.find(value=>value.status==='failed').retry,'function');
});

test('manual confirmation is required when changing a verified Pixiv page',()=>{
    const {upload,workbench,context}=harness();workbench.name='a';workbench.form={isConnected:true};
    upload.tempResults.set('a',{status:'verified',page:0,token:'proof',artwork:{pid:'12345678',page_count:2}});
    workbench.values=()=>({group_ids:[1],character_ids:[1],pid:'12345678_p1',identity_confirmed:false});
    workbench.confirm();assert.equal(upload.tempSelection.size,0);
    workbench.values=()=>({group_ids:[1],character_ids:[1],pid:'12345678_p1',identity_confirmed:true});
    workbench.confirm();assert(upload.tempSelection.has('a'));assert.equal(upload.tempDrafts.get('a').pixiv_token,'proof');
});
