const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
function harness(){
    const calls=[],content={innerHTML:'',insertAdjacentHTML(_position,html){this.innerHTML+=html;}};
    const context={URL,setTimeout,clearTimeout,window:{PicManagerSecurity:{escapeHTML:String}},
        document:{getElementById:()=>content},ui:{showToast(){}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/pixiv-ol.js'),'utf8'),context);
    const pol=context.window.pixivOL;
    pol.root={querySelectorAll:()=>[],querySelector:()=>null};pol.positionTools=()=>{};pol.watch=()=>{};
    context.fetch=async(url,options={})=>{calls.push({url,body:options.body&&JSON.parse(options.body)});return {ok:true,json:async()=>url.endsWith('/cart')?{items:pol.cartItems}:{jobs:[]}};};
    return {context,pol,calls,content};
}
function row(id='one'){
    return {id,status:'ready',pages:[0],bytes:10,cached_pages:[0],preview_url:'/preview',
        artwork:{pid:'100',title:'Artwork',author:'Artist',match:{evidence:[]}},
        draft:{pages:[0],import_mode:'merged',group_ids:[1],character_ids:[],feature_tag_ids:[]}};
}

test('Pixiv duplicate review reuses the shared merger and submits the reviewed page and candidate',async()=>{
    const {context,pol,calls}=harness();
    pol.importJobs=[{id:7,kind:'import',status:'awaiting_duplicate',result:{page:2,review_key:'a'.repeat(32)}}];
    const comparison={page:2,review_key:'a'.repeat(32),incoming:{thumbnail_url:'/clear-preview'},duplicates:[{image_id:'OLD'}]};
    context.window.auth={loadFeature:async()=>({resolveDuplicateChoice:async(result,url,options)=>{
        assert.equal(result.page,2);assert.equal(url,'/clear-preview');assert.equal(options.pixiv,true);
        return {action:'merge',keep:'new',otherImageId:'OLD',metadataSources:{characters:'other'}};
    }})};
    context.ui.currentPage='pixiv-ol';
    context.fetch=async(url,options={})=>{calls.push({url,body:options.body&&JSON.parse(options.body)});return {ok:true,json:async()=>comparison};};
    pol.loadImportJobs=async()=>[];
    await pol.reviewImportJob(7);
    const submission=calls.find(call=>call.url.endsWith('/resolve')).body;
    assert.equal(submission.action,'merge_new');assert.equal(submission.image_id,'OLD');assert.equal(submission.page,2);assert.equal(submission.review_key,comparison.review_key);
    assert.equal(submission.metadata_sources.characters,'other');assert.equal(pol.importReviewBusy,false);
});

test('automatic merge reviews pause behind an open dialog and do not repeat a deferred review',async()=>{
    const {context,pol}=harness();pol.importJobs=[{id:7,kind:'import',status:'awaiting_duplicate',result:{page:0,review_key:'b'.repeat(32)}}];
    context.ui.currentPage='pixiv-ol';let open=true,shown=0;
    context.document.getElementById=()=>({style:{display:'none'}});context.document.querySelector=()=>open?{}:null;
    context.window.auth={loadFeature:async()=>({resolveDuplicateChoice:async()=>{shown++;return {action:'later'};}})};
    context.fetch=async()=>({ok:true,json:async()=>({page:0,review_key:'b'.repeat(32),incoming:{thumbnail_url:'/preview'},duplicates:[]})});
    pol.offerImportReviews();assert.equal(shown,0);
    open=false;pol.offerImportReviews();await new Promise(resolve=>setImmediate(resolve));assert.equal(shown,1);
    pol.offerImportReviews();await new Promise(resolve=>setImmediate(resolve));assert.equal(shown,1);
    await pol.reviewImportJob(7);assert.equal(shown,2);
});
test('ready cart rows stay unchecked by default and confirmed selection survives rendering',()=>{
    const {pol,content}=harness();pol.cartItems=[row()];pol.renderCart(content);
    assert.equal(pol.selection.size,0);assert.doesNotMatch(content.innerHTML,/value="one" checked/);
    pol.selectTaggedCartItem(pol.cartItems[0]);pol.renderCart(content);
    assert.match(content.innerHTML,/value="one" checked/);pol.renderCart(content);assert.equal(pol.selection.size,1);
});
test('split selection waits for all selected pages and rejects empty group confirmation',()=>{
    const {pol}=harness(),item=row();item.draft={import_mode:'split',pages:[0,2],confirmed_pages:[0],page_drafts:{0:{group_ids:[1]},2:{group_ids:[2]}}};
    pol.selectTaggedCartItem(item);assert.equal(pol.selection.size,0);
    item.draft.confirmed_pages.push(2);pol.selectTaggedCartItem(item);assert(pol.selection.has(item.id));
    pol.selection.clear();item.draft.page_drafts[2].group_ids=[];pol.selectTaggedCartItem(item);assert.equal(pol.selection.size,0);
});
test('import immediately clears selection, hides submitted rows and prevents double submission',async()=>{
    const {pol,context,calls,content}=harness();pol.view='cart';pol.cartItems=[row()];pol.selection.add('one');
    let respond;context.fetch=async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return new Promise(resolve=>{respond=()=>resolve({ok:true,json:async()=>({jobs:[{id:7,kind:'import',status:'queued',pid:'100',page_count:1,result:{}}]})});});};
    const importing=pol.importSelected();assert.equal(pol.selection.size,0);
    assert.doesNotMatch(content.innerHTML,/name="pixiv-cart-check"/);assert(pol.submittingCartIds.has('one'));
    await pol.importSelected();assert.equal(calls.length,1);respond();await importing;
    assert.equal(pol.cartItems[0].status,'importing');assert.equal(pol.importJobs[0].id,7);
    assert.equal(pol.submittingCartIds.size,0);assert.equal(pol.selection.size,0);
});
test('server rejection restores selection and cart rows without losing the draft',async()=>{
    const {pol,context,content}=harness();pol.view='cart';pol.cartItems=[row()];pol.selection.add('one');
    context.fetch=async()=>({ok:false,json:async()=>({detail:'cache_missing'})});
    await assert.rejects(pol.importSelected(),/缓存文件缺失/);
    assert(pol.selection.has('one'));assert.equal(pol.cartItems[0].status,'ready');
    assert.match(content.innerHTML,/value="one" checked/);assert.equal(pol.importSubmitting,false);
});
test('one selected page of a multi-page artwork skips mode choice and submits split mode',async()=>{
    const {pol,calls}=harness();pol.items=[{pid:'100',page_count:3,imported_pages:[]}];
    pol.loadCart=async()=>{};pol.setLiked=()=>{};pol.chooseImportMode=()=>assert.fail('Mode dialog must not open');
    await pol.add('100',[2],false);assert.equal(calls[0].body.import_mode,'split');assert.deepEqual(calls[0].body.pages,[2]);
});
test('two selected pages still ask for import mode',async()=>{
    const {pol,calls}=harness();pol.items=[{pid:'100',page_count:3,imported_pages:[]}];
    pol.loadCart=async()=>{};pol.setLiked=()=>{};let choices=0;
    pol.chooseImportMode=async()=>{choices++;return 'merged';};await pol.add('100',[0,2],false);
    assert.equal(choices,1);assert.equal(calls[0].body.import_mode,'merged');
});
test('cart reload removes submitted and deleted selections while preserving other choices',async()=>{
    const {pol}=harness();pol.cartItems=[row('ready'),{...row('submitted'),status:'importing'}];
    ['ready','submitted','deleted'].forEach(id=>pol.selection.add(id));await pol.loadCart();
    assert.deepEqual(Array.from(pol.selection),['ready']);
});
test('job status from polling takes precedence over stale cart status',()=>{
    const {pol}=harness();const item=row();item.job={id:7,kind:'import',status:'queued',result:{}};pol.cartItems=[item];
    pol.importJobs=[{id:7,kind:'import',status:'awaiting_duplicate',result:{page:0,duplicates:[]}}];
    const jobs=pol.currentImportJobs();assert.equal(jobs.length,1);assert.equal(jobs[0].status,'awaiting_duplicate');
    assert.equal(jobs[0].title,'Artwork');assert.equal(jobs[0].page_count,1);
});
test('a cart read started before submission cannot bring imported rows back',async()=>{
    const {pol,context,content}=harness();pol.view='cart';pol.cartItems=[row()];pol.selection.add('one');
    let respond;
    context.fetch=async(url)=>url.endsWith('/cart')?new Promise(resolve=>{respond=()=>resolve({ok:true,json:async()=>({items:[row()]})});}):{ok:true,json:async()=>({jobs:[]})};
    const reading=pol.loadCart();await pol.importSelected();respond();await reading;
    assert.equal(pol.cartItems[0].status,'importing');pol.renderCart(content);
    assert.doesNotMatch(content.innerHTML,/name="pixiv-cart-check"/);
});
