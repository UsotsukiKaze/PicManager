const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
function harness(){
    const calls=[],timers=[],gallery={html:'',insertAdjacentHTML(_where,html){this.html+=html;}},sentinel={textContent:'',innerHTML:'',top:850,querySelector:()=>null,getBoundingClientRect(){return {top:this.top};}};
    let scrollListener,intersection;
    const scroll={scrollTop:0,getBoundingClientRect:()=>({bottom:800}),addEventListener(_name,listener){scrollListener=listener;}};
    const context={URL,URLSearchParams,AbortController,innerHeight:800,setTimeout:fn=>{timers.push(fn);return timers.length;},clearTimeout(){},document:{},
        window:{PicManagerSecurity:{escapeHTML:String}},ui:{currentPage:'pixiv-ol',showToast(){}},
        IntersectionObserver:class{constructor(callback,options){intersection=callback;this.options=options;}observe(){}disconnect(){}}};
    vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../static/js/pixiv-ol.js'),'utf8'),context);
    const pol=context.window.pixivOL;
    pol.root={closest:()=>scroll,querySelector:selector=>selector==='.px-gallery'?gallery:selector==='.px-load-sentinel'?sentinel:null};
    pol.items=[];pol.abort=new AbortController();pol.watch=()=>{};
    const flow=pol.flow={view:'recommendations',mode:'combined',offset:0,cursor:null,seen:new Set(),more:true,upstreamMore:true,busy:false,lazyReady:false};
    context.fetch=async(url,options={})=>{calls.push({url,options});const offset=Number(new URL(url,'http://localhost').searchParams.get('offset'));return {ok:true,json:async()=>({batch_id:'batch',total:100,items:Array.from({length:20},(_,i)=>({pid:String(offset+i),title:'Artwork',author:'Artist',page_count:1,preview_url:'/preview'}))})};};
    return {pol,flow,calls,timers,gallery,sentinel,scroll,context,fireScroll:()=>scrollListener(),fireIntersection:()=>intersection([{isIntersecting:true}])};
}

test('new recommendation modes send already-read PIDs and keep separate reading keys',async()=>{
    const h=harness();h.flow.mode='stock';h.flow.seen=new Set(['101','102']);
    h.context.fetch=async(url,options)=>{h.calls.push({url,options});return {ok:true,json:async()=>({id:8})};};
    await h.pol.continueReading(h.flow);
    const payload=JSON.parse(h.calls[0].options.body);
    assert.deepEqual(payload,{view:'recommendations',mode:'stock',seen_pids:['101','102']});
    assert.equal(h.flow.continueJob,8);
    assert.equal(new Set(['personal','stock','discovery'].map(mode=>h.pol.readingKey('recommendations',mode))).size,3);
});

test('first render fetches exactly twenty and never eagerly chains later pages',async()=>{
    const {pol,flow,calls,timers,gallery}=harness();await pol.loadMore(flow);
    assert.match(calls[0].url,/limit=20/);assert.equal(pol.items.length,20);assert.equal(timers.length,0);
    assert.equal((gallery.html.match(/loading="eager"/g)||[]).length,5);
    assert.equal((gallery.html.match(/loading="lazy"/g)||[]).length,15);
});

test('a short initial supply continues filling without waiting for an impossible scroll',async()=>{
    const h=harness();
    h.context.fetch=async()=>({ok:true,json:async()=>({batch_id:'batch',total:10,items:Array.from({length:10},(_,i)=>({pid:String(i),title:'Artwork',page_count:1,preview_url:'/preview'}))})});
    await h.pol.loadMore(h.flow);assert.equal(h.pol.items.length,10);assert.equal(h.timers.length,1);
});

test('observer waits for scrolling and loads the next twenty only near the bottom',async()=>{
    const h=harness();await h.pol.loadMore(h.flow);h.pol.observeFlow(h.flow);
    h.fireIntersection();assert.equal(h.calls.length,1);
    assert.equal(h.pol.loadObserver.options.rootMargin,'0px 0px 320px 0px');
    h.sentinel.top=1700;h.scroll.scrollTop=100;h.fireScroll();assert.equal(h.calls.length,1);
    h.sentinel.top=1000;h.fireScroll();h.fireIntersection();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(h.calls.length,2);assert.match(h.calls[1].url,/offset=20/);assert.equal(h.pol.items.length,40);
});

test('navigation invalidates deferred loading and refresh requests a first-page job',async()=>{
    const h=harness();await h.pol.loadMore(h.flow);h.flow.lazyReady=true;h.pol.flow=null;h.pol.maybeLoadMore(h.flow);assert.equal(h.calls.length,1);
    const button={dataset:{action:'refresh'},classList:{contains:()=>false}};
    h.context.fetch=async(url,options)=>{h.calls.push({url,body:JSON.parse(options.body)});return {ok:true,json:async()=>({id:5})};};
    await h.pol.click({target:{closest:()=>button}});
    assert.equal(h.calls[1].body.first_page,true);assert.equal(h.pol.pendingRefresh.id,5);
});

test('recommendations use immutable batch offsets even when the visible total shrinks',async()=>{
    const h=harness();
    h.context.fetch=async(url)=>{
        h.calls.push({url});
        return {ok:true,json:async()=>({batch_id:'batch',total:2,next_offset:27,has_more:true,
            items:[{pid:'26',title:'Artwork',page_count:1,preview_url:'/preview'}]})};
    };
    await h.pol.loadMore(h.flow);
    assert.equal(h.flow.offset,27);assert.equal(h.flow.more,true);
    await h.pol.loadMore(h.flow);assert.match(h.calls[1].url,/offset=27/);
});

test('a cart update racing a recommendation response cannot render the excluded artwork',async()=>{
    const h=harness();h.pol.cartItems=[{artwork:{pid:'0'}}];
    await h.pol.loadMore(h.flow);
    assert.equal(h.pol.items.length,19);assert.equal(h.flow.offset,20);
    assert.equal(h.pol.items.some(item=>item.pid==='0'),false);assert.equal(h.timers.length,1);
});

test('cart and library exclusions update active and saved recommendation cards while keeping feed cards',()=>{
    const h=harness(),makeCard=pid=>({style:{},hidden:false,querySelector:()=>({dataset:{pid}})});
    const current=[makeCard('100'),makeCard('101')],saved=[makeCard('100')],feed=[makeCard('100')];
    h.pol.items=[{pid:'100',imported_pages:[]},{pid:'101',imported_pages:[2]}];
    h.pol.root.querySelectorAll=selector=>selector==='.px-card'?current:[];
    h.pol.readingStates.set('native',{flow:{view:'recommendations'},items:[{pid:'100'}],content:{querySelectorAll:()=>saved}});
    h.pol.readingStates.set('feed',{flow:{view:'feed'},items:[{pid:'100'}],content:{querySelectorAll:()=>feed}});
    h.pol.cartItems=[{artwork:{pid:'100'}}];h.pol.maybeLoadMore=()=>{};
    h.pol.syncCartButtons();
    assert.equal(current[0].hidden,true);assert.equal(current[1].hidden,true);assert.equal(saved[0].hidden,true);
    assert.equal(feed[0].hidden,false);assert.equal(h.pol.visibleGalleryCount(h.flow),0);
    h.pol.cartItems=[];h.pol.syncCartButtons();
    assert.equal(current[0].hidden,false);assert.equal(saved[0].hidden,false);assert.equal(current[1].hidden,true);
    assert.equal(h.pol.visibleGalleryCount(h.flow),1);
});
