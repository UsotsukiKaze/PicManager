(function () {
    'use strict';
    const esc = value => window.PicManagerSecurity.escapeHTML(value ?? '');
    const icons = {bag:'<path d="M5 7h14l1 13H4L5 7Z"/><path d="M8 8V6a4 4 0 0 1 8 0v2"/>',
        spark:'<path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6L12 3Z"/>',
        plus:'<path d="M12 5v14M5 12h14"/>',arrow:'<path d="m12 5-7 7 7 7M5 12h14"/>',top:'<path d="m6 13 6-6 6 6M12 7v14M5 3h14"/>',
        refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1"/>',
        eye:'<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
        upload:'<path d="m8 9 4-4 4 4M12 5v10M5 15v5h14v-5"/>',
        heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
        check:'<path d="m5 12 4 4L19 6"/>',search:'<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>', settings:'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>'};
    const icon = name => `<svg class="px-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.spark}</svg>`;
    const errors = {reauth_required:'账号登录已失效，请前往设置重新登录', account_changed:'账号已更换，请刷新页面',
        group_required:'请为所选作品确认至少一个分组', content_filtered:'作品不符合当前内容偏好',
        pages_unconfirmed:'请逐页确认分 P 作品的标签后再入库',invalid_page_draft:'分 P 标签草稿不完整，请重新确认',
        artwork_unavailable:'找不到该作品，可能已删除、私密或不可访问',external_error:'Pixiv 暂时不可用，请稍后重试', download_failed:'下载失败，请重试缓存', cache_full:'暂存空间已满，请入库或移除部分作品',image_too_large:'原图的文件大小或像素数量超过服务端上限',
        cache_missing:'缓存文件缺失，请移除后重新加入', cache_changed:'缓存文件已变化，请移除后重新加入',
        tag_conflict:'新标签存在歧义，请在优选夹或标签管理中确认映射', cart_removed:'暂存作品已被移除',
        processing_failed:'处理失败，可以重试', login_browser_failed:'登录窗口无法完成授权，请尝试普通浏览器授权',
        login_browser_navigation_failed:'Pixiv 登录页加载失败，请尝试普通浏览器授权或检查网络',
        login_browser_dependency_missing:'未安装旧版自动登录依赖，请使用默认浏览器登录或手动授权',
        login_request_rejected:'Pixiv 拒绝了登录中转请求，请重新登录或尝试普通浏览器授权',
        login_exchange_failed:'Pixiv 拒绝了授权码，可能已过期、已使用或不属于本次登录，请重新登录',
        login_authorization_rejected:'Pixiv 拒绝了授权兑换请求，请重新登录并立即提交本次回调链接',
        login_client_rejected:'Pixiv 拒绝了登录客户端，请检查登录适配；继续提交同一授权码无法解决',
        login_network_error:'服务无法连接 Pixiv 授权接口，请检查服务器网络或代理后重新登录',
        login_service_unavailable:'Pixiv 授权服务暂时不可用，请稍后重新登录',
        login_response_invalid:'Pixiv 授权响应不符合预期，请检查登录适配后重新登录',
        rate_limited:'Pixiv 请求过于频繁，请稍后重试', access_denied:'Pixiv 拒绝访问，请检查服务器网络或代理',
        login_expired:'登录已超时，请重新登录', login_closed:'登录窗口已关闭',
        login_used:'授权已使用，请重新登录', login_interrupted:'服务已重启，请重新登录', permission_revoked:'操作权限已撤销',
        login_cli_not_installed:'尚未安装 pixiv-cli，请完成安装后重试', login_cli_version:'pixiv-cli 版本不兼容，请使用 v1.1.1',
        login_cli_failed:'pixiv-cli 登录失败，请重新登录', login_cli_busy:'另一轮 pixiv-cli 登录仍在运行，请结束后重试',
        login_cli_storage_failed:'pixiv-cli 无法保存账号，请检查本机账号存储目录后重新登录',
        login_callback_invalid:'回跳不属于本次登录或已使用，请重新开始登录',
        pixiv_proxy_invalid:'Pixiv 代理配置无效，请检查代理地址后重新登录',
        login_cli_handler_failed:'无法注册 Pixiv 授权回调，请检查本机协议关联',
        login_cli_browser_failed:'无法打开默认浏览器，请检查系统浏览器设置后重试',
        login_cli_local_only:'请在运行 PicManager 的电脑上通过 localhost 或 127.0.0.1 登录'};
    const statuses = {queued:'排队中',running:'处理中',retry:'等待重试',caching:'正在缓存原图',ready:'等待确认入库',
        failed:'处理失败',importing:'正在入库',completed:'已完成',awaiting_duplicate:'需要查重确认',partial:'待继续'};
    async function request(path, options = {}) {
        const response = await fetch(`/api/pixiv-ol${path}`, {credentials:'same-origin',...options,
            headers:{'Content-Type':'application/json','X-Pixiv-OL':'1',...options.headers}});
        const data = await response.json();
        if (!response.ok) {
            if (response.status === 401 && window.__PICMANAGER_MODERN__) window.dispatchEvent(new Event('picmanager-session-expired'));
            throw new Error(errors[data.detail] || (typeof data.detail === 'string' ? data.detail : '请求失败'));
        }
        if (window.__PICMANAGER_MODERN__ && options.method && options.method !== 'GET') window.dispatchEvent(new CustomEvent('picmanager-data-changed',{detail:`/pixiv-ol${path}`}));
        return data;
    }
    const bytes = value => value >= 1024*1024 ? `${(value/1024/1024).toFixed(1)} MB` : `${Math.round(value/1024)} KB`;
    const galleryPageSize=20, galleryPreloadDistance=320;

    class MediaCache {
        constructor() {this.entries=new Map();this.bytes=0;}
        clear() {for(const entry of this.entries.values()){entry.controller?.abort();if(entry.url)URL.revokeObjectURL(entry.url);}this.entries.clear();this.bytes=0;}
        load(url,key=url,priority='high') {
            const hit=this.entries.get(key);
            if(hit) {this.entries.delete(key);this.entries.set(key,hit);return hit.promise;}
            const entry={url:null,size:0,controller:new AbortController()};this.entries.set(key,entry);
            const timeout=setTimeout(()=>entry.controller.abort(),12000);
            entry.promise=(async()=>{
                const response=await fetch(url,{credentials:'same-origin',priority,signal:entry.controller.signal});
                if(!response.ok)throw new Error('图片加载失败');
                const blob=await response.blob();if(!blob.type.startsWith('image/')||blob.size>12*1024*1024)throw new Error('图片格式无效');
                if(this.entries.get(key)!==entry)throw new Error('图片缓存已更新');
                entry.url=URL.createObjectURL(blob);entry.size=blob.size;this.bytes+=entry.size;
                for(const [oldKey,old] of this.entries) {
                    if(this.entries.size<=40&&this.bytes<=48*1024*1024)break;
                    if(oldKey===key||!old.url)continue;
                    URL.revokeObjectURL(old.url);this.bytes-=old.size;this.entries.delete(oldKey);
                }
                return entry.url;
            })().catch(error=>{if(this.entries.get(key)===entry)this.entries.delete(key);throw error;}).finally(()=>clearTimeout(timeout));
            return entry.promise;
        }
    }

    class PixivOL {
        constructor() {
            this.view='recommendations'; this.lastView=this.view; this.mode='personal'; this.offset=0;
            this.generation=0; this.batch=null; this.cartItems=[]; this.selection=new Set();
            this.importJobs=[];this.submittingCartIds=new Set();this.submittedCartIds=new Set();this.importSubmitting=false;
            this.media=new MediaCache();
            this.readingStates=new Map();this.readerPages=new Map();
            this.importReviewSeen=new Set();
            this.lookupItems=new Map();this.similarityPending=new Set();this.similaritySeen=new Set();this.similarityEpoch=0;
        }
        bind(node) {
            if (node.dataset.pixivBound) return;
            node.dataset.pixivBound='true';
            node.addEventListener('load',event=>{const image=event.target;if(image.matches?.('.px-image-button img'))this.queueSimilarity(image.closest('[data-pid]').dataset.pid);},true);
            node.addEventListener('click', event => this.click(event).catch(error => ui.showToast(error.message,'error')));
            node.addEventListener('change', event => {
                if (event.target.name==='pixiv-cart-check') {
                    event.target.checked ? this.selection.add(event.target.value) : this.selection.delete(event.target.value);
                    this.updateSelection();
                }
            });
            node.addEventListener('pointerover',event=>{
                const card=event.target.closest('.px-card');
                if(!card||card.contains(event.relatedTarget)||event.pointerType==='touch')return;
                clearTimeout(this.hoverTimer);
                this.hoverTimer=setTimeout(()=>{
                    const item=this.items?.find(item=>item.pid===card.querySelector('[data-pid]')?.dataset.pid);
                    if(!item)return;
                    this.media.load(item.author_avatar_url||`/api/pixiv-ol/artworks/${item.pid}/avatar`,`artist:${item.author_id}`,'low').catch(()=>{});
                    this.media.load(`${item.reader_preview_url||`/api/pixiv-ol/artworks/${item.pid}/reader-preview`}?page=0`,undefined,'low').catch(()=>{});
                },200);
            });
            node.addEventListener('pointerout',event=>{const card=event.target.closest('.px-card');if(card&&!card.contains(event.relatedTarget)){clearTimeout(this.hoverTimer);card.classList.remove('px-resting');delete card.dataset.readerHover;}});
            node.addEventListener('pointermove',event=>{const card=event.target.closest('.px-card');if(card?.dataset.readerHover==='false'){card.classList.remove('px-resting');delete card.dataset.readerHover;}});
            node.addEventListener('focusin',event=>{const card=event.target.closest('.px-card');if(card){card.classList.remove('px-resting');delete card.dataset.readerHover;}});
        }
        async loadAccount() {
            this.account=await request('/account');
            const scope=[window.auth.currentUser?.id,this.account.user_id,this.account.media_revision,this.account.connected].join(':');
            if(this.mediaScope!==scope){this.media.clear();this.readingStates.clear();this.readerPages.clear();this.lookupItems.clear();this.similarityPending.clear();this.similaritySeen.clear();this.similarityEpoch++;this.similarityAbort?.abort();this.mediaScope=scope;}
        }
        async loadCart({refreshTags=false}={}) {
            const generation=this.cartGeneration=(this.cartGeneration||0)+1;
            const items=(await request(refreshTags?'/cart/refresh-tags':'/cart',refreshTags?{method:'POST'}:undefined)).items;
            if(generation!==this.cartGeneration)return;
            const completed=(this.cartItems||[]).filter(row=>row.status==='importing'&&!items.some(item=>item.id===row.id));
            if(completed.length)await this.refreshLibraryStatus(completed.map(row=>row.artwork)).catch(()=>{});
            if(generation!==this.cartGeneration)return;
            this.cartItems=items;
            for(const id of this.submittedCartIds){
                const row=this.cartItems.find(item=>item.id===id);
                if(!row||row.status==='importing')this.submittedCartIds.delete(id);
            }
            const available=new Set(this.cartItems.filter(row=>row.status!=='importing'&&!this.submittedCartIds.has(row.id)).map(row=>row.id));
            for(const id of this.selection)if(!available.has(id))this.selection.delete(id);
            this.syncCartButtons();
        }
        async init() {
            if (!window.auth.isAdmin()) return;
            this.root=document.getElementById('pixiv-ol-root'); this.bind(this.root);
            await Promise.all([this.loadAccount(),this.loadCart({refreshTags:this.view==='cart'})]);
            await this.render(); this.watch();
            this.loadImportJobs().then(()=>this.updateImportTools()).catch(()=>{});
        }
        async initSettings() {
            if (!window.auth.isAdmin()) return;
            this.settingsRoot=document.getElementById('pixiv-settings-root'); this.bind(this.settingsRoot);
            await this.loadAccount(); await this.settings();
            if(window.auth.isRoot()&&!this.loginDialog?.isConnected) {
                const pending=await request('/account/login/pending');
                if(pending.session&&ui.currentPage==='settings') {
                    if(pending.session.automatic) this.automaticLogin(pending.session);
                    else this.manualLogin(pending.session);
                }
            }
        }
        async entities(force=false) {
            [this.groups,this.characters,this.features]=await Promise.all([ui.loadGroupsData(force,true),ui.loadCharactersData(force,true),ui.loadFeatureTagsData(force,true)]);
        }
        heading() {
            const count=this.cartCount();
            return `<header class="px-header"><div class="px-heading"><img src="/static/icon/pixiv-ol.svg" alt="" class="px-brand"><div><h2>Pixiv<span>-ol</span></h2></div></div>
                <button class="px-button px-cart-button ${this.view==='cart'?'is-active':''}" data-view="cart">${icon('bag')}优选夹<span class="px-count">${count}</span></button></header>
                <div class="px-navigation"><div class="px-tabs" role="tablist" aria-label="Pixiv 内容"><button role="tab" aria-selected="${this.view==='recommendations'}" data-view="recommendations">${icon('spark')}为你推荐</button><button role="tab" aria-selected="${this.view==='feed'}" data-view="feed">关注更新</button></div><button class="px-text-button" data-action="settings">${icon('settings')}设置</button></div>`;
        }
        async render() {
            const generation=++this.generation;
            this.toolsObserver?.disconnect();
            this.loadObserver?.disconnect();this.flowScrollAbort?.abort();this.flow=null;
            if (this.abort) this.abort.abort(); this.abort=new AbortController();
            this.root.innerHTML=this.heading()+'<div id="pixiv-content" class="px-content" aria-live="polite"></div>';
            const content=document.getElementById('pixiv-content');
            if (this.view==='cart') {this.renderCart(content); return;}
            if (!this.account.connected) {
                content.innerHTML=this.empty('把下一张喜欢的画作，留在这里。','连接 Pixiv 后，这里会为你推荐画作，也能查看关注作者的新发布。', '<button class="px-button px-primary" data-action="settings">前往设置登录 Pixiv</button>'); return;
            }
            const saved=this.readingStates.get(this.readingKey());
            if(saved) {
                this.readingStates.delete(this.readingKey());
                content.replaceWith(saved.content);this.items=saved.items;
                const flow=this.flow={...saved.flow,generation,seen:new Set(saved.flow.seen),busy:false};
                this.batch=flow.batch;this.syncCartButtons();this.updateRefreshButton();
                this.updateImportTools();await this.refreshLibraryStatus(this.items).catch(()=>{});
                await new Promise(resolve=>requestAnimationFrame(resolve));
                if(this.flow!==flow)return;
                this.root.closest('.main-content')?.scrollTo({top:saved.scrollTop,behavior:'instant'});
                this.positionTools();this.observeFlow(flow);this.root.querySelectorAll('.px-image-button img').forEach(image=>{if(image.complete&&image.naturalWidth)this.queueSimilarity(image.closest('[data-pid]').dataset.pid);});return;
            }
            this.items=[];
            content.innerHTML=`<div class="px-toolbar"><a class="px-account-profile" href="https://www.pixiv.net/users/${esc(this.account.user_id||'')}" target="_blank" rel="noopener noreferrer"><span class="px-artist-avatar"><span aria-hidden="true">${esc((this.account.name||'P').slice(0,1))}</span><img alt="" decoding="async"></span><span>${esc(this.account.name||'Pixiv')}</span></a><div class="px-toolbar-actions">${this.view==='feed'?'':`<select id="pixiv-mode" aria-label="推荐方式"><option value="personal">猜你喜欢</option><option value="stock">进货模式</option><option value="discovery">Pixiv 发现</option></select>`}</div></div><div class="px-showcase"><div class="px-gallery-flow"><div class="px-gallery"></div><div class="px-load-sentinel" role="status">正在加载画作…</div></div><aside class="px-floating-tools" aria-label="展柜操作"><div class="px-floating-actions"><button class="px-icon-button" data-action="lookup" aria-label="按 PID 查找" title="按 PID 查找">${icon('search')}</button><button class="px-icon-button" data-action="refresh" aria-label="${this.view==='feed'?'更新动态':'换一批'}" title="${this.view==='feed'?'更新动态':'换一批'}">${icon('refresh')}</button><button class="px-icon-button" data-action="top" aria-label="回到顶部" title="回到顶部">${icon('top')}</button></div><button class="px-icon-button px-floating-cart" data-view="cart" aria-label="打开优选夹" title="优选夹">${icon('bag')}</button>${this.importButton()}</aside></div>`;
            this.positionTools();this.updateImportTools();
            const avatar=content.querySelector('.px-account-profile img');
            if(this.account.avatar_url)this.media.load(this.account.avatar_url,'account-avatar').then(url=>{if(avatar.isConnected)avatar.src=url;}).catch(()=>avatar.remove());else avatar.remove();
            const flow=this.flow={generation,view:this.view,mode:this.mode,offset:0,batch:null,cursor:null,seen:new Set(),busy:false,more:true,upstreamMore:true,emptyRounds:0,lazyReady:false};
            const mode=document.getElementById('pixiv-mode');
            if(mode) {mode.value=this.mode; mode.onchange=()=>{this.saveReading();this.mode=mode.value;this.render().catch(e=>ui.showToast(e.message,'error'));};}
            this.updateRefreshButton();
            this.root.closest('.main-content')?.scrollTo({top:0,behavior:'instant'});
            await this.loadMore(flow);
            if(this.flow!==flow)return;
            this.root.closest('.main-content')?.scrollTo({top:0,behavior:'instant'});
            this.observeFlow(flow);
        }
        readingKey(view=this.view,mode=this.mode) {return view==='feed'?'feed':`${view}:${mode}`;}
        positionTools() {
            this.toolsObserver?.disconnect();
            const tools=this.root.querySelector('.px-floating-tools'),checkout=this.root.querySelector('.px-checkout'),gallery=this.root.querySelector('.px-gallery-flow,.px-cart-list');
            const scroll=this.root.closest('.main-content');
            if((!tools&&!checkout)||!gallery)return;
            const align=()=>{
                if(!gallery.isConnected||!gallery.getClientRects().length)return;
                const bounds=gallery.getBoundingClientRect();
                if(tools?.isConnected)tools.style.right=`${Math.max(6,innerWidth-bounds.right-12-tools.offsetWidth)}px`;
                if(checkout?.isConnected){
                    checkout.style.left=`${bounds.left}px`;
                    checkout.style.width=`${bounds.width}px`;
                    checkout.style.setProperty('--px-checkout-bottom',`${Math.max(0,innerHeight-(scroll?.getBoundingClientRect().bottom||innerHeight))}px`);
                    gallery.style.paddingBottom=`${checkout.offsetHeight+24}px`;
                }
            };
            this.toolsObserver=new ResizeObserver(align);
            this.toolsObserver.observe(gallery);
            if(scroll)this.toolsObserver.observe(scroll);
            if(checkout)this.toolsObserver.observe(checkout);
            align();
        }
        saveReading() {
            if(!this.flow||this.view==='cart')return;
            const content=this.root.querySelector('#pixiv-content');
            this.readingStates.set(this.readingKey(),{content,items:this.items,flow:{...this.flow,seen:new Set(this.flow.seen)},scrollTop:this.root.closest('.main-content')?.scrollTop||0});
        }
        observeFlow(flow) {
            this.flowScrollAbort?.abort();this.flowScrollAbort=new AbortController();
            const scroll=this.root.closest('.main-content');
            scroll?.addEventListener('scroll',()=>{if(scroll.scrollTop>0){flow.lazyReady=true;this.maybeLoadMore(flow);}},{passive:true,signal:this.flowScrollAbort.signal});
            this.loadObserver=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&ui.currentPage==='pixiv-ol'&&(flow.lazyReady||this.visibleGalleryCount(flow)<galleryPageSize))this.loadMore(flow);},{root:scroll,rootMargin:`0px 0px ${galleryPreloadDistance}px 0px`});
            this.loadObserver.observe(this.root.querySelector('.px-load-sentinel'));
        }
        maybeLoadMore(flow) {
            if(this.flow!==flow||ui.currentPage!=='pixiv-ol'||(!flow.lazyReady&&this.visibleGalleryCount(flow)>=galleryPageSize))return;
            const sentinel=this.root.querySelector('.px-load-sentinel'),root=this.root.closest('.main-content');
            if(sentinel&&!sentinel.querySelector('button')&&sentinel.getBoundingClientRect().top<(root?.getBoundingClientRect().bottom||innerHeight)+galleryPreloadDistance)this.loadMore(flow);
        }
        syncCartButtons() {
            this.root?.querySelectorAll?.('[data-action="add"]').forEach(button=>{
                const added=this.cartItems.some(row=>row.artwork.pid===button.dataset.pid);
                const item=this.items?.find(item=>item.pid===button.dataset.pid),library=this.libraryState(item);
                button.disabled=added||library.complete;button.classList.toggle('px-primary',!added&&!library.complete);button.classList.toggle('px-added',added||library.complete);
                button.innerHTML=icon(added||library.complete?'check':'plus')+(library.complete?'已入库':added?'已加入':'加入优选夹');
                const card=button.closest('.px-card'),image=card?.querySelector('.px-image-button');
                card?.querySelector('.px-library-status')?.remove();
                if(library.count)image?.insertAdjacentHTML('beforeend',this.libraryBadge(item));
            });
            this.syncRecommendationCards();
        }
        recommendationExcluded(item) {
            return !!item?.imported_pages?.length||this.cartItems.some(row=>row.artwork.pid===item?.pid);
        }
        visibleGalleryCount(flow) {
            return (this.items||[]).filter(item=>flow.view!=='recommendations'||!this.recommendationExcluded(item)).length;
        }
        syncRecommendationCards() {
            const views=[{content:this.root,flow:this.flow,items:this.items},...this.readingStates.values()];
            for(const state of views) {
                if(state.flow?.view!=='recommendations')continue;
                const items=new Map((state.items||[]).map(item=>[item.pid,item]));
                state.content?.querySelectorAll?.('.px-card').forEach(card=>{
                    const pid=card.querySelector('[data-action="detail"]')?.dataset.pid;
                    card.hidden=this.recommendationExcluded(items.get(pid));
                    card.style.display=card.hidden?'none':'';
                });
            }
            if(this.flow?.view==='recommendations'&&ui.currentPage==='pixiv-ol')this.maybeLoadMore(this.flow);
        }
        libraryState(item) {
            const total=Number(item?.page_count)||1;
            const count=new Set((item?.imported_pages||[]).filter(page=>Number.isInteger(page)&&page>=0&&page<total)).size;
            return {count,complete:count===total,label:count===total?'已入库':`已入库 ${count} / ${total} 页`};
        }
        libraryBadge(item) {
            const state=this.libraryState(item);
            return state.count?`<span class="px-library-status ${state.complete?'is-complete':''}">${icon('check')}${state.label}</span>`:'';
        }
        async refreshLibraryStatus(items) {
            const pids=[...new Set(items.map(item=>item.pid))],pages=new Map();
            for(let offset=0;offset<pids.length;offset+=100) {
                const params=new URLSearchParams();pids.slice(offset,offset+100).forEach(pid=>params.append('pid',pid));
                const data=await request(`/library-status?${params}`);
                for(const row of data.items||[])pages.set(row.pid,row.imported_pages);
            }
            const retained=[...items,...(this.items||[]),...[...this.readingStates.values()].flatMap(state=>state.items)];
            for(const item of retained)if(pages.has(item.pid))item.imported_pages=pages.get(item.pid);
            this.syncCartButtons();
        }
        async loadMore(flow=this.flow) {
            if(!flow||this.flow!==flow||flow.busy||flow.continueJob||flow.paused)return;
            if(!flow.more){await this.continueReading(flow);return;}
            flow.busy=true;const sentinel=this.root.querySelector('.px-load-sentinel');sentinel.textContent='正在加载画作…';
            const params=new URLSearchParams({limit:String(galleryPageSize),offset:String(flow.cursor?0:flow.offset)});
            if(flow.view==='feed'){if(flow.cursor)params.set('cursor',flow.cursor);}else{params.set('mode',flow.mode);if(flow.batch)params.set('batch_id',flow.batch);}
            try {
                const data=await request(`/${flow.view==='feed'?'feed':'recommendations'}?${params}`,{signal:this.abort.signal});
                if(this.flow!==flow)return;
                flow.batch=data.batch_id||flow.batch;this.batch=flow.batch;
                flow.offset=flow.view==='recommendations'&&Number.isInteger(data.next_offset)?data.next_offset:flow.offset+data.items.length;flow.cursor=data.next_cursor||data.tail_cursor||flow.cursor;
                const fresh=data.items.filter(item=>{if(flow.seen.has(item.pid))return false;flow.seen.add(item.pid);return flow.view!=='recommendations'||!this.recommendationExcluded(item);});
                const firstScreen=!this.items.length;this.items.push(...fresh);this.root.querySelector('.px-gallery').insertAdjacentHTML('beforeend',fresh.map((item,index)=>this.card(item,firstScreen&&index<5)).join(''));
                flow.more=flow.view==='recommendations'&&'has_more' in data?data.has_more:flow.view==='feed'&&'next_cursor' in data?!!data.next_cursor:flow.offset<data.total&&data.items.length>0;
                if(fresh.length)flow.emptyRounds=0;
                sentinel.textContent='继续下滑加载';
            } catch(error) {
                if(error.name!=='AbortError'&&this.flow===flow)sentinel.innerHTML=`<button class="px-text-button" data-action="load-more">加载失败，点击重试</button>`;
            } finally {flow.busy=false;}
            if(this.flow===flow&&!sentinel.querySelector('button')){
                const root=this.root.closest('.main-content');
                if((flow.lazyReady||this.visibleGalleryCount(flow)<galleryPageSize)&&sentinel.getBoundingClientRect().top<(root?.getBoundingClientRect().bottom||innerHeight)+galleryPreloadDistance)setTimeout(()=>this.maybeLoadMore(flow),0);
            }
        }
        async continueReading(flow) {
            const sentinel=this.root.querySelector('.px-load-sentinel');
            if(!flow.upstreamMore||flow.emptyRounds>=3){sentinel.textContent='暂时没有更多画作，稍后刷新试试';return;}
            flow.busy=true;sentinel.textContent='正在获取更多画作…';
            try {
                const payload={view:flow.view,mode:flow.mode};
                if(flow.view==='recommendations'&&['personal','stock','discovery'].includes(flow.mode))payload.seen_pids=[...flow.seen].slice(-2000);
                const job=await request('/browse',{method:'POST',body:JSON.stringify(payload)});
                // Keep the queued continuation in saved reading state when navigating during the request.
                const target=this.flow===flow?flow:this.readingStates.get(this.readingKey(flow.view,flow.mode))?.flow;
                if(target){target.continueJob=job.id;target.beforeContinue=target.seen.size;}
                this.watch();
            } catch(error) {
                flow.paused=true;
                if(this.flow===flow)sentinel.innerHTML='<button class="px-text-button" data-action="load-more">暂时无法获取更多，点击重试</button>';
            } finally {flow.busy=false;}
        }
        async finishContinuation(job,flow) {
            flow.continueJob=null;
            const content=this.flow===flow?this.root:this.readingStates.get(this.readingKey(flow.view,flow.mode))?.content;
            const sentinel=content?.querySelector('.px-load-sentinel');
            if(job.status==='completed') {
                flow.upstreamMore=job.result?.more!==false;
                flow.emptyRounds=flow.seen.size===flow.beforeContinue?flow.emptyRounds+1:0;
                if(flow.view==='recommendations') {
                    if(!job.result?.batch_id)flow.upstreamMore=false;
                    else {flow.batch=job.result.batch_id;flow.offset=0;flow.more=true;}
                } else flow.more=true;
                if(sentinel)sentinel.textContent='继续下滑加载';
                if(this.flow===flow)await this.loadMore(flow);
            } else {
                flow.paused=true;
                if(sentinel)sentinel.innerHTML='<button class="px-text-button" data-action="load-more">加载失败，点击重试</button>';
            }
        }
        scrollTop() {this.root.closest('.main-content')?.scrollTo({top:0,behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'instant':'smooth'});}
        updateRefreshButton() {const button=this.root?.querySelector('[data-action="refresh"]');if(button){const busy=!!this.pendingRefresh||!!this.refreshStarting;button.disabled=busy;button.classList.toggle('is-refreshing',busy);}}
        suspend() {this.saveReading();this.generation++;this.flow=null;this.abort?.abort();this.loadObserver?.disconnect();this.flowScrollAbort?.abort();this.toolsObserver?.disconnect();clearTimeout(this.hoverTimer);clearTimeout(this.timer);}
        empty(title,description,action='') {
            return `<div class="px-empty"><div class="px-empty-art"><img src="/static/icon/pixiv-ol.svg" alt=""></div><h3>${esc(title)}</h3><p>${esc(description)}</p>${action}</div>`;
        }
        similarityBadge(item) {
            return item?.similarity?.length?`<span class="px-similarity-status" title="图库中有高度相似的无 PID 图片，可在详情中查看">${icon('search')}高相似</span>`:'';
        }
        similaritySummary(item) {
            return item?.similarity?.length?`<p>图库中有高度相似图片</p><div>${item.similarity.map(row=>`<button type="button" class="px-text-button" data-similar-image="${esc(row.image_id)}">查看库图 ${esc(row.image_id)}</button>`).join('')}</div><small>仅作相似提示，需人工确认来源与页码。</small>`:'';
        }
        queueSimilarity(pid) {
            if(!this.account?.connected||this.similaritySeen.has(pid))return;
            this.similarityPending.add(pid);
            clearTimeout(this.similarityTimer);this.similarityTimer=setTimeout(()=>this.flushSimilarity(),350);
        }
        async flushSimilarity() {
            if(this.similarityBusy||!this.similarityPending.size||ui.currentPage!=='pixiv-ol')return;
            const pids=[...this.similarityPending].slice(0,24),epoch=this.similarityEpoch;
            pids.forEach(pid=>{this.similarityPending.delete(pid);this.similaritySeen.add(pid);});
            const params=new URLSearchParams();pids.forEach(pid=>params.append('pid',pid));
            this.similarityBusy=true;this.similarityAbort=new AbortController();
            const timeout=setTimeout(()=>this.similarityAbort?.abort(),10000);
            try {
                const data=await request(`/similarity?${params}`,{signal:this.similarityAbort.signal});
                if(epoch!==this.similarityEpoch)return;
                const items=[...(this.items||[]),...this.lookupItems.values(),...[...this.readingStates.values()].flatMap(state=>state.items)];
                const roots=[this.root,...[...this.readingStates.values()].map(state=>state.content)];
                for(const row of data.items||[]) {
                    items.filter(item=>item.pid===row.pid).forEach(item=>item.similarity=row.matches);
                    const item=items.find(item=>item.pid===row.pid);if(!item)continue;
                    for(const root of roots)root?.querySelectorAll(`.px-image-button[data-pid="${row.pid}"]`).forEach(node=>{node.querySelector('.px-similarity-status')?.remove();node.insertAdjacentHTML('beforeend',this.similarityBadge(item));});
                    document.querySelectorAll(`.px-artwork-reader[data-work-pid="${row.pid}"] .px-similar-summary`).forEach(node=>{node.innerHTML=this.similaritySummary(item);node.hidden=!item.similarity?.length;});
                }
            } catch (_) {pids.forEach(pid=>this.similaritySeen.delete(pid));}
            finally {clearTimeout(timeout);this.similarityBusy=false;if(this.similarityPending.size)this.similarityTimer=setTimeout(()=>this.flushSimilarity(),350);}
        }
        async lookup() {
            if(this.lookupDialog?.isConnected){this.lookupDialog.querySelector('input').focus();return;}
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-lookup-dialog';
            dialog.innerHTML=`<div class="px-detail-body"><div class="px-lookup-heading"><span class="px-lookup-symbol" aria-hidden="true">${icon('search')}</span><div><h3 id="pixiv-lookup-title">按 PID 查找</h3><p>找到作品，再决定是否加入优选夹</p></div><button type="button" class="px-icon-button" data-lookup-close aria-label="关闭">${icon('close')}</button></div><form><label for="pixiv-lookup-pid">作品编号或 Pixiv 链接</label><div class="px-lookup-input"><input id="pixiv-lookup-pid" type="text" inputmode="url" maxlength="256" placeholder="例如 144129324" required autocomplete="off" aria-describedby="pixiv-lookup-hint"></div><p class="px-lookup-hint" id="pixiv-lookup-hint">指定页码可输入 144129324_p0</p><p class="px-error" role="alert"></p><div class="px-lookup-footer"><button type="button" class="px-button" data-lookup-close>取消</button><button type="submit" class="px-button px-primary">${icon('search')}查找作品</button></div></form></div>`;
            dialog.setAttribute('aria-labelledby','pixiv-lookup-title');
            this.lookupDialog=dialog;let controller=null;const previous=document.activeElement;
            const close=()=>{controller?.abort();dialog.close();dialog.remove();if(this.lookupDialog===dialog)this.lookupDialog=null;if(previous?.isConnected)previous.focus({preventScroll:true});};
            document.body.append(dialog);dialog.showModal();dialog.querySelector('input').focus();
            dialog.querySelectorAll('[data-lookup-close]').forEach(button=>button.onclick=close);dialog.addEventListener('click',event=>{if(event.target===dialog)close();});dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
            dialog.querySelector('form').onsubmit=async event=>{
                event.preventDefault();const button=dialog.querySelector('[type="submit"]');if(button.disabled)return;
                const error=dialog.querySelector('.px-error');error.textContent='';
                let value=dialog.querySelector('input').value.trim(),match=value.match(/^([0-9]{1,30})(?:_p([0-9]{1,3}))?$/);
                if(!match)try {const url=new URL(value);if(url.protocol==='https:'&&['www.pixiv.net','pixiv.net'].includes(url.hostname)&&!url.username&&!url.password)match=url.pathname.match(/^\/(?:[a-z]{2}\/)?artworks\/([0-9]{1,30})\/?$/);}catch(_){}
                if(!match){error.textContent='请输入有效的数字 PID 或 Pixiv 作品链接。';return;}
                const pid=match[1].replace(/^0+(?=\d)/,''),epoch=this.similarityEpoch;button.disabled=true;button.innerHTML='<span class="px-small-spinner" aria-hidden="true"></span>查找中';controller=new AbortController();
                const timeout=setTimeout(()=>controller.abort(),15000);
                try {
                    const item=await request('/lookup',{method:'POST',body:JSON.stringify({pid}),signal:controller.signal});
                    if(!dialog.isConnected)return;
                    if(epoch!==this.similarityEpoch)throw new Error('账号状态已变化，请重新查找。');
                    if(match[2]!==undefined&&Number(match[2])>=item.page_count)throw new Error('所给页码超出作品范围。');
                    this.lookupItems.set(pid,item);if(this.lookupItems.size>30)this.lookupItems.delete(this.lookupItems.keys().next().value);
                    if(match[2]!==undefined)this.readerPages.set(pid,Number(match[2]));
                    close();await this.detail(pid);
                } catch(exc){if(dialog.isConnected)error.textContent=exc.name==='AbortError'?'查找超时，请稍后重试。':exc.message;}
                finally{clearTimeout(timeout);if(dialog.isConnected){button.disabled=false;button.innerHTML=icon('search')+'查找作品';}}
            };
        }
        card(item,eager=false) {
            const added=this.cartItems.some(row=>row.artwork.pid===item.pid);
            const library=this.libraryState(item);
            return `<article class="px-card"><button class="px-image-button" data-action="detail" data-pid="${esc(item.pid)}" aria-label="查看 ${esc(item.title)}"><img src="${esc(item.preview_url)}" alt="${esc(item.title)}" loading="${eager?'eager':'lazy'}" decoding="async" fetchpriority="${eager?'high':'low'}">${item.page_count>1?`<span class="px-page-count">${item.page_count} P</span>`:''}${this.libraryBadge(item)}${this.similarityBadge(item)}</button><div class="px-card-body"><h4 title="${esc(item.title)}">${esc(item.title)}</h4><p class="px-author">${esc(item.author)}</p><div class="px-card-actions"><button class="px-button ${added||library.complete?'px-added':'px-primary'}" data-action="add" data-pid="${esc(item.pid)}" ${added||library.complete?'disabled':''}>${icon(added||library.complete?'check':'plus')}${library.complete?'已入库':added?'已加入':'加入优选夹'}</button><button class="px-icon-button ${item.liked?'is-liked':''}" data-action="like" data-pid="${esc(item.pid)}" aria-pressed="${!!item.liked}" aria-label="${item.liked?'取消喜欢':'喜欢'}">${icon('heart')}</button></div></div></article>`;
        }
        async click(event) {
            const button=event.target.closest('button'); if(!button) return;
            if(button.dataset.view) {
                if(button.dataset.view===this.view)return;
                this.saveReading();
                this.flow=null;this.abort?.abort();this.loadObserver?.disconnect();
                if(button.dataset.view!=='cart') this.lastView=button.dataset.view;
                this.view=button.dataset.view;
                await this.loadCart({refreshTags:this.view==='cart'});await this.render();if(this.view==='cart')this.root.closest('.main-content')?.scrollTo({top:0,behavior:'instant'});return;
            }
            const action=button.dataset.action; if(!action) return;
            button.disabled=true;
            try {
                if(action==='settings') ui.switchPage('settings');
                else if(action==='reload') await this.init();
                else if(action==='refresh') {
                    if(this.pendingRefresh||this.refreshStarting)return;
                    const view=this.view,mode=this.mode;this.refreshStarting=true;this.updateRefreshButton();
                    try {
                        const job=await request('/sync',{method:'POST',body:JSON.stringify({kind:view==='feed'?'sync':'recommendations',mode,first_page:true})});
                        this.pendingRefresh={id:job.id,view,mode};this.watch();
                    } finally {this.refreshStarting=false;this.updateRefreshButton();}
                } else if(action==='top') this.scrollTop();
                else if(action==='lookup') await this.lookup();
                else if(action==='load-more') {if(this.flow)this.flow.paused=false;await this.loadMore();}
                else if(action==='detail') await this.detail(button.dataset.pid,null,button);
                else if(action==='add') await this.add(button.dataset.pid);
                else if(action==='like') {await this.toggleLike(button.dataset.pid,button);}
                else if(action==='cart-edit') await this.detail(null,this.cartItems.find(row=>row.id===button.dataset.id),button.closest('.px-cart-page,.px-cart-row')?.querySelector('img'),button.dataset.page===undefined?null:Number(button.dataset.page));
                else if(action==='cart-remove') {
                    const row=this.cartItems.find(row=>row.id===button.dataset.id);
                    if(!confirm(`确认将“${row?.artwork.title||'这幅作品'}”移出优选夹？\n缓存原图和标签草稿将被清理，已入库图片和喜欢状态会保留。`))return;
                    const removed=await request(`/cart/${button.dataset.id}`,{method:'DELETE'});
                    await this.loadCart();await this.render();
                    if(removed.liked)this.askRemoveLike(removed.pid,row?.artwork.title);
                }
                else if(action==='cart-all') {
                    const ready=this.cartItems.filter(row=>row.status==='ready'&&!this.submittingCartIds.has(row.id));
                    const all=ready.every(row=>this.selection.has(row.id));ready.forEach(row=>all?this.selection.delete(row.id):this.selection.add(row.id));this.renderCart(document.getElementById('pixiv-content'));
                } else if(action==='cart-import') {
                    await this.importSelected();
                } else if(action==='import-progress') {
                    await this.showImportProgress();
                } else if(action==='retry') {await request(`/jobs/${Number(button.dataset.id)}/retry`,{method:'POST'});this.watch();}
                else if(action==='merge-review') {await this.reviewImportJob(Number(button.dataset.id));}
                else if(action==='resolve') {if(button.dataset.choice?.startsWith('merge')&&!confirm('确认合并并删除另一份重复图片？\n只保留选定的文件，此操作无法恢复。'))return;await request(`/imports/${Number(button.dataset.id)}/resolve`,{method:'POST',body:JSON.stringify({action:button.dataset.choice,image_id:button.dataset.image || null})});this.watch();}
                else if(action==='login') await this.login();
                else if(action==='disconnect') {if(!confirm(`确认解除 Pixiv 账号“${this.account.name||'当前账号'}”的绑定？\n登录凭据、优选夹缓存及 Pixiv 喜欢记录将被清理，已入库图片会保留。`))return;await request('/account',{method:'DELETE'});await this.loadAccount();await this.loadCart();await this.settings();}
                else if(action==='save-settings') await this.saveSettings();

            } finally {button.disabled=button.classList.contains('px-added');this.updateRefreshButton();}
        }
        chooseImportMode(item,pages) {
            return new Promise(resolve=>{
                const dialog=document.createElement('dialog');dialog.className='px-dialog px-confirm-dialog px-import-mode';
                dialog.innerHTML=`<div class="px-detail-body"><span class="px-eyebrow">MULTI-PAGE ARTWORK</span><h3>这幅作品如何加入？</h3><p>${esc(item.title)} · ${pages?.length||Math.min(item.page_count,100)} 页</p><div class="px-mode-options"><button class="px-mode-choice" data-import-mode="split"><strong>分 P 加入 <small>推荐</small></strong><span>每页单独确认分组、角色和特征，适合各页角色不同的作品。</span></button><button class="px-mode-choice" data-import-mode="merged"><strong>合并加入</strong><span>所选页共用一套标签，适合内容一致的作品。图片仍按 _pN 分页保存。</span></button></div><button class="px-text-button" data-cancel>取消</button></div>`;
                const previous=document.activeElement,finish=mode=>{dialog.close();dialog.remove();previous?.isConnected&&previous.focus({preventScroll:true});resolve(mode);};
                dialog.querySelectorAll('[data-import-mode]').forEach(button=>button.onclick=()=>finish(button.dataset.importMode));
                dialog.querySelector('[data-cancel]').onclick=()=>finish(null);
                dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null);});
                dialog.addEventListener('click',event=>{if(event.target===dialog)finish(null);});
                document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-import-mode="split"]').focus();
            });
        }
        async add(pid,pages,notify=true) {
            const existing=this.cartItems.some(row=>row.artwork.pid===pid);
            const item=this.items?.find(row=>row.pid===pid)||this.lookupItems.get(pid)||(!existing?await request(`/artworks/${encodeURIComponent(pid)}`):null);
            const selected=pages||Array.from({length:Math.min(item?.page_count||1,100)},(_,index)=>index).filter(page=>!(item?.imported_pages||[]).includes(page));
            const mode=!existing&&item.page_count>1?(selected.length===1?'split':await this.chooseImportMode(item,selected)):'merged';
            if(!mode)return false;
            await request('/cart',{method:'POST',body:JSON.stringify({pid,import_mode:mode,...(pages?{pages}:{})})});
            await this.loadCart();
            this.setLiked(pid,true);
            const count=this.root.querySelector('.px-count');if(count)count.textContent=this.cartCount();
            this.root.querySelectorAll(`[data-action="add"][data-pid="${pid}"]`).forEach(button=>{button.disabled=true;button.classList.remove('px-primary');button.classList.add('px-added');button.innerHTML=icon('check')+'已加入';});
            this.watch();if(notify)ui.showToast('已加入优选夹，正在缓存原图','success');return true;
        }
        renderCart(content) {
            const rows=this.cartItems.filter(row=>row.status!=='importing'&&!this.submittingCartIds.has(row.id)&&!this.submittedCartIds.has(row.id));
            content.innerHTML=`<div class="px-toolbar"><div><h3>优选夹</h3><p>先挑选，再整理。原图缓存完成后可统一入库。</p></div><button class="px-text-button" data-view="${this.lastView}">${icon('arrow')}继续发现</button></div>
                ${rows.length?`<div class="px-cart-list">${rows.map(row=>this.cartRow(row)).join('')}</div><div class="px-checkout"><button class="px-text-button" data-action="cart-all">全选 / 取消</button><span id="pixiv-selection-count"></span><span class="px-cart-storage">已缓存 ${bytes(rows.reduce((n,row)=>n+row.bytes,0))}</span><button id="pixiv-checkout-button" class="px-button px-primary" data-action="cart-import"></button></div>`:this.empty(this.cartItems.length?'已提交后台入库':'优选夹还是空的',this.cartItems.length?'点击悬浮球查看进度，也可以继续挑选画作。':'喜欢的画作先加入这里，确认标签后一起入库。',`<button class="px-button px-primary" data-view="${this.lastView}">去发现画作</button>`)}`;
            content.insertAdjacentHTML('beforeend',`<aside class="px-floating-tools px-cart-import-tools" aria-label="入库任务">${this.importButton()}</aside>`);
            this.updateSelection();this.updateImportTools();this.positionTools();
        }
        cartRow(row) {
            const item=row.artwork;const job=row.job;
            const split=row.draft.import_mode==='split',confirmed=row.draft.pages.filter(page=>(row.draft.confirmed_pages||[]).includes(page)).length;
            const label=row.status==='ready'?(split?`已确认 ${confirmed} / ${row.draft.pages.length} 页`:!row.draft.group_ids.length?'待确认分组':statuses.ready):(statuses[job?.status==='awaiting_duplicate'?'awaiting_duplicate':row.status]||row.status);
            const tags=split?['分 P 加入']:row.draft.group_ids.map(id=>this.groups?.find(g=>g.id===id)?.name || item.match.evidence.find(g=>g.type==='group'&&g.id===id)?.name || '作品分组');
            return `<article class="px-cart-row ${split?'px-cart-split':''}"><label class="px-cart-select"><input type="checkbox" name="pixiv-cart-check" value="${row.id}" ${this.selection.has(row.id)?'checked':''} ${row.status==='ready'?'':'disabled'} aria-label="选择 ${esc(item.title)}"></label><img class="px-cart-preview" src="${esc(row.preview_url)}" alt="${esc(item.title)}" loading="lazy"><div class="px-cart-info"><h4>${esc(item.title)}</h4><p>${esc(item.author)}${row.pages.length>1?` · ${row.pages.length} 页`:''} · ${bytes(row.bytes)}</p><div class="px-tags">${tags.map(tag=>`<span>${esc(tag)}</span>`).join('')}<span class="px-state ${row.status==='ready'?'is-ready':''}">${esc(label)}</span></div>${split?this.cartPageRows(row):''}${job?.error?`<p class="px-error">${esc(errors[job.error]||job.error)}</p>`:''}${job?.status==='awaiting_duplicate'?`<div class="px-duplicate"><p>第 ${job.result.page+1} 页 · 有 ${job.result.duplicates.length} 张相似库图</p><button class="px-button" data-action="merge-review" data-id="${job.id}">比对并合并</button></div>`:''}</div><div class="px-cart-controls">${row.status!=='importing'?`${!split?`<button class="px-text-button" data-action="cart-edit" data-id="${row.id}">确认标签</button>`:''}<button class="px-text-button px-remove" data-action="cart-remove" data-id="${row.id}">移除</button>`:''}${job&&['failed','partial'].includes(job.status)?`<button class="px-text-button" data-action="retry" data-id="${job.id}">重试</button>`:''}</div></article>`;
        }
        cartPageRows(row) {
            return `<div class="px-cart-page-list">${row.draft.pages.map(page=>{
                const draft=row.draft.page_drafts?.[page]||{},confirmed=(row.draft.confirmed_pages||[]).includes(page);
                const tags=[['分组',draft.group_ids,this.groups||ui.allGroups],['角色',draft.character_ids,this.characters||ui.allCharacters],['特征',draft.feature_tag_ids,this.features||ui.allFeatureTags]].flatMap(([type,ids,entities])=>(ids||[]).map(id=>`${type} · ${entities?.find(tag=>tag.id===id)?.name||id}`));
                return `<div class="px-cart-page"><img src="${row.cached_pages.includes(page)?`/api/pixiv-ol/cart/${row.id}/preview?page=${page}`:'/static/images/placeholder.png'}" alt="第 ${page+1} 页" loading="lazy" decoding="async"><div><strong>第 ${page+1} 页 <small class="${confirmed?'is-confirmed':''}">${confirmed?'已确认':'待确认'}</small></strong><p>${esc(tags.join(' / ')||'未选择标签')}</p></div>${row.status!=='importing'?`<button class="px-text-button" data-action="cart-edit" data-id="${row.id}" data-page="${page}">${confirmed?'编辑本页':'确认本页'}</button>`:''}</div>`;
            }).join('')}</div>`;
        }
        updateSelection() {
            const count=this.cartItems.filter(row=>this.selection.has(row.id)&&row.status==='ready').length;
            const text=document.getElementById('pixiv-selection-count'),button=document.getElementById('pixiv-checkout-button');
            if(text) text.textContent=`已选 ${count} 个作品`;
            if(button) {button.textContent=`统一入库${count?`（${count}）`:''}`;button.disabled=!count;}
        }
        selectTaggedCartItem(row) {
            const draft=row.draft;
            const confirmed=draft.import_mode==='split'
                ?draft.pages.every(page=>(draft.confirmed_pages||[]).includes(page)&&(draft.page_drafts?.[page]?.group_ids||[]).length)
                :(draft.group_ids||[]).length>0;
            if(confirmed&&row.status!=='importing'&&!this.submittingCartIds.has(row.id)&&!this.submittedCartIds.has(row.id))this.selection.add(row.id);
        }
        async importSelected() {
            if(this.importSubmitting)return;
            const rows=this.cartItems.filter(row=>this.selection.has(row.id)&&row.status==='ready'&&!this.submittingCartIds.has(row.id));
            if(!rows.length)throw new Error('请先选择缓存完成的作品');
            if(rows.some(row=>row.draft.import_mode==='split'&&row.draft.pages.some(page=>!(row.draft.confirmed_pages||[]).includes(page))))throw new Error('请逐页确认分 P 作品的标签后再入库');
            if(rows.some(row=>row.draft.import_mode!=='split'&&!row.draft.group_ids.length))throw new Error('请先为标记“待确认分组”的作品选择分组');
            this.importSubmitting=true;this.selection.clear();
            rows.forEach(row=>this.submittingCartIds.add(row.id));
            this.renderCart(document.getElementById('pixiv-content'));
            try {
                const result=await request('/cart/imports',{method:'POST',body:JSON.stringify({item_ids:rows.map(row=>row.id)})});
                this.cartGeneration=(this.cartGeneration||0)+1;
                for(const job of result.jobs)this.importJobs=this.importJobs.filter(old=>old.id!==job.id).concat(job);
                rows.forEach(row=>this.submittedCartIds.add(row.id));
                rows.forEach(row=>row.status='importing');
                this.cartItems.filter(row=>this.submittedCartIds.has(row.id)).forEach(row=>row.status='importing');
                ui.showToast(`已提交 ${rows.length} 个作品，可在悬浮球查看入库进度`,'success');
                this.watch();
            }catch(error){
                rows.forEach(row=>this.selection.add(row.id));
                throw error;
            }finally{
                rows.forEach(row=>this.submittingCartIds.delete(row.id));this.importSubmitting=false;
                if(this.view==='cart')this.renderCart(document.getElementById('pixiv-content'));
                this.updateImportTools();
            }
        }
        async loadImportJobs() {
            const jobs=await request('/jobs'),previous=new Map(this.currentImportJobs().map(job=>[job.id,job]));
            if (window.__PICMANAGER_MODERN__ && jobs.some(job=>job.kind==='import'&&['completed','partial'].includes(job.status)&&previous.get(job.id)?.status!==job.status)) window.dispatchEvent(new CustomEvent('picmanager-data-changed',{detail:'/pixiv-ol/imports'}));
            this.importJobs=jobs.filter(job=>job.kind==='import').map(job=>({...previous.get(job.id),...job}));return jobs;
        }
        currentImportJobs() {
            const jobs=new Map();
            for(const row of this.cartItems)if(row.job?.kind==='import')jobs.set(row.job.id,{...row.job,title:row.artwork.title,pid:row.artwork.pid,page_count:row.draft.pages.length});
            for(const job of this.importJobs){
                const row=this.cartItems.find(item=>item.artwork.pid===job.pid);
                jobs.set(job.id,{title:row?.artwork.title,...jobs.get(job.id),...job});
            }
            return Array.from(jobs.values()).sort((a,b)=>b.id-a.id);
        }
        cartCount() {
            return this.cartItems.filter(row=>row.status!=='importing'&&!this.submittingCartIds.has(row.id)&&!this.submittedCartIds.has(row.id)).length;
        }
        importButton() {
            return `<button class="px-icon-button px-floating-import" data-action="import-progress" aria-label="入库进度" title="入库进度" hidden>${icon('upload')}<span class="px-task-count" hidden></span></button>`;
        }
        updateImportTools() {
            const count=this.root?.querySelector('.px-count');if(count)count.textContent=this.cartCount();
            const jobs=this.currentImportJobs(),pending=this.submittingCartIds.size;
            const active=jobs.filter(job=>['queued','running','retry','awaiting_duplicate','failed','partial'].includes(job.status)).length+pending;
            this.root?.querySelectorAll('.px-floating-import').forEach(button=>{
                button.hidden=!jobs.length&&!pending;
                button.classList.toggle('has-attention',jobs.some(job=>['awaiting_duplicate','failed','partial'].includes(job.status)));
                button.classList.toggle('is-importing',pending>0||jobs.some(job=>['queued','running','retry'].includes(job.status)));
                const badge=button.querySelector('.px-task-count');badge.hidden=!active;badge.textContent=active;
            });
            const tools=this.root?.querySelector('.px-cart-import-tools');if(tools)tools.hidden=!jobs.length&&!pending;
            if(this.importDialog?.isConnected)this.renderImportProgress();
        }
        async showImportProgress() {
            if(this.importDialog?.isConnected)return;
            const dialog=this.importDialog=document.createElement('dialog');dialog.className='px-dialog px-confirm-dialog px-import-progress';
            dialog.innerHTML=`<button class="px-icon-button px-dialog-close" data-close aria-label="关闭入库进度">${icon('close')}</button><div class="px-detail-body"><span class="px-eyebrow">COLLECTION QUEUE</span><h3>入库进度</h3><p>后台继续处理，你可以关闭窗口继续浏览。</p><div data-import-jobs aria-live="polite"></div></div>`;
            const close=()=>{dialog.close();dialog.remove();this.importDialog=null;};
            dialog.querySelector('[data-close]').onclick=close;
            dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
            dialog.addEventListener('click',event=>{if(event.target===dialog)close();});
            document.body.append(dialog);dialog.showModal();this.renderImportProgress();
            await this.loadImportJobs();this.updateImportTools();this.watch();
        }
        renderImportProgress() {
            const list=this.importDialog.querySelector('[data-import-jobs]'),jobs=this.currentImportJobs();
            list.innerHTML=(this.submittingCartIds.size?'<p class="px-help">正在提交入库任务…</p>':'')+jobs.map(job=>{
                const total=Number(job.page_count)||0,done=job.result?.done?.length||0;
                return `<article class="px-import-task"><div class="px-import-task-heading"><strong>${esc(job.title||job.pid||`入库任务 ${job.id}`)}</strong><span class="px-state">${esc(statuses[job.status]||job.status)}</span></div>${total?`<progress max="${total}" value="${done}"></progress><p>${done} / ${total} 页</p>`:''}${job.error?`<p class="px-error">${esc(errors[job.error]||job.error)}</p>`:''}${job.status==='awaiting_duplicate'?`<div class="px-import-duplicates"><p>第 ${Number(job.result.page)+1} 页 · 需要确认相似图片</p><button class="px-button" data-import-choice="review" data-job="${Number(job.id)}">比对并合并</button></div>`:''}${['failed','partial'].includes(job.status)?`<button class="px-button" data-import-choice="retry" data-job="${Number(job.id)}">重试入库</button>`:''}</article>`;
            }).join('')||'<p class="px-help">暂无入库任务。</p>';
            list.querySelectorAll('[data-import-choice]').forEach(button=>button.onclick=async()=>{
                if(this.importJobAction)return;this.importJobAction=true;button.disabled=true;
                try {
                    const id=Number(button.dataset.job),action=button.dataset.importChoice;
                    if(action==='review')await this.reviewImportJob(id);
                    else if(action==='retry')await request(`/jobs/${id}/retry`,{method:'POST'});
                    else await request(`/imports/${id}/resolve`,{method:'POST',body:JSON.stringify({action,image_id:button.dataset.image||null})});
                    await this.loadImportJobs();this.updateImportTools();this.watch();
                }catch(error){ui.showToast(error.message,'error');}
                finally{this.importJobAction=false;button.disabled=false;}
            });
        }
        importReviewKey(job) { return `${job.id}:${job.result?.page}:${job.result?.review_key||'legacy'}`; }
        offerImportReviews() {
            if(this.importReviewBusy||ui.currentPage!=='pixiv-ol'||document.getElementById('modal-overlay')?.style.display==='flex'||document.querySelector('dialog[open]:not(.px-import-progress)'))return;
            const job=this.currentImportJobs().find(job=>job.status==='awaiting_duplicate'&&!this.importReviewSeen.has(this.importReviewKey(job)));
            if(job)this.reviewImportJob(job.id).catch(error=>ui.showToast(error.message,'error'));
        }
        async reviewImportJob(id) {
            if(this.importReviewBusy)return;
            const job=this.currentImportJobs().find(job=>job.id===id);if(!job)return;
            this.importReviewBusy=true;this.importReviewSeen.add(this.importReviewKey(job));
            const epoch=this.similarityEpoch;
            try {
                const [upload,comparison]=await Promise.all([window.auth.loadFeature('upload'),request(`/imports/${id}/comparison`)]);
                if(ui.currentPage!=='pixiv-ol'||epoch!==this.similarityEpoch)return;
                this.importReviewSeen.add(`${id}:${comparison.page}:${comparison.review_key||'legacy'}`);
                const decision=await upload.resolveDuplicateChoice(comparison,comparison.incoming.thumbnail_url,{pixiv:true,title:`第 ${Number(comparison.page)+1} 页 · 相似图片合并`});
                if(!decision||decision.action==='later')return;
                if(epoch!==this.similarityEpoch)throw new Error('账号已变化，请重新比对');
                const action=decision.action==='distinct'?'different':decision.keep==='new'?'merge_new':'merge_existing';
                await request(`/imports/${id}/resolve`,{method:'POST',body:JSON.stringify({action,image_id:decision.action==='distinct'||decision.keep==='new'?decision.otherImageId:decision.keep||null,metadata_sources:decision.metadataSources||{},page:comparison.page,review_key:comparison.review_key})});
                await this.loadImportJobs();this.updateImportTools();this.watch();
            } finally {this.importReviewBusy=false;}
        }
        setLiked(pid,liked) {
            const lists=[this.items||[],[...this.lookupItems.values()],...Array.from(this.readingStates.values(),state=>state.items),this.cartItems.map(row=>row.artwork)];
            lists.forEach(items=>items.filter(item=>item.pid===pid).forEach(item=>item.liked=liked));
            const roots=[document,...Array.from(this.readingStates.values(),state=>state.content)];
            roots.forEach(root=>root.querySelectorAll(`[data-action="like"][data-pid="${pid}"]`).forEach(node=>{
                node.classList.toggle('is-liked',liked);node.setAttribute('aria-pressed',String(liked));node.setAttribute('aria-label',liked?'取消喜欢':'喜欢');
            }));
        }
        askRemoveLike(pid,title) {
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-confirm-dialog';
            dialog.innerHTML=`<div class="px-detail-body"><h3>是否同时取消喜欢？</h3><p>${esc(title||'这幅作品')}已移出优选夹。你可以保留喜欢，或同时移出喜欢。</p><p class="px-error" role="alert"></p><div class="px-dialog-actions"><button class="px-button" data-keep-like>保留喜欢</button><button class="px-button px-primary" data-clear-like>取消喜欢</button></div></div>`;
            const close=()=>{dialog.close();dialog.remove();};
            dialog.querySelector('[data-keep-like]').onclick=close;
            dialog.querySelector('[data-clear-like]').onclick=async()=>{
                dialog.querySelectorAll('button').forEach(button=>button.disabled=true);
                try {await request('/feedback',{method:'POST',body:JSON.stringify({pid,value:'clear'})});this.setLiked(pid,false);close();}
                catch(error){dialog.querySelector('.px-error').textContent=error.message;dialog.querySelectorAll('button').forEach(button=>button.disabled=false);}
            };
            dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
            dialog.addEventListener('click',event=>{if(event.target===dialog)close();});
            document.body.append(dialog);dialog.showModal();dialog.querySelector('[data-keep-like]').focus();
        }
        async toggleLike(pid, button) {
            const liked=button.getAttribute('aria-pressed')==='true';
            if(liked&&!confirm('确认取消这幅作品的喜欢状态？\n作品仍保留在图库或优选夹中。'))return;
            button.disabled=true;
            try {
                await request('/feedback',{method:'POST',body:JSON.stringify({pid,value:liked?'clear':'like'})});
                this.setLiked(pid,!liked);
            } finally {button.disabled=false;}
        }
        expandReader(dialog,sourceRect,parts={}) {
            if(matchMedia('(prefers-reduced-motion:reduce)').matches)return Promise.resolve();
            const cover=parts.cover||dialog.querySelector('.px-detail-cover'),target=cover.getBoundingClientRect();
            const from=sourceRect?.width&&sourceRect?.height?`translate(${sourceRect.left-target.left}px,${sourceRect.top-target.top}px) scale(${sourceRect.width/target.width},${sourceRect.height/target.height})`:'scale(.92)';
            const picture=cover.animate([{transform:from,opacity:.7},{transform:'none',opacity:1}],{duration:380,easing:'cubic-bezier(.2,.8,.2,1)'});
            const details=(parts.details||dialog.querySelector('.px-detail-body')).animate([{transform:'translateY(14px) scale(.97)',opacity:0},{transform:'none',opacity:1}],{duration:280,delay:100,fill:'backwards',easing:'ease-out'});
            dialog.addEventListener('close',()=>{picture.cancel();details.cancel();},{once:true});
            return picture.finished.catch(()=>{});
        }
        async detail(pid,cartRow=null,source=null,cartPage=null) {
            source=source||(pid?this.root?.querySelector(`[data-action="detail"][data-pid="${pid}"]`):null);
            const sourceImage=source?.matches('img')?source:source?.querySelector('img');
            const sourceRect=sourceImage?.getBoundingClientRect();
            const cartReady=this.loadCart().then(()=>true).catch(()=>false);
            if(cartRow) await this.entities();
            const item=cartRow?cartRow.artwork:(this.items?.find(item=>item.pid===pid)||this.lookupItems.get(pid)||await request(`/artworks/${encodeURIComponent(pid)}`));
            if(!cartRow)await this.refreshLibraryStatus([item]).catch(()=>{});
            const library=this.libraryState(item);
            const split=cartRow?.draft.import_mode==='split';
            const editPage=cartPage??cartRow?.draft.pages.find(page=>!(cartRow.draft.confirmed_pages||[]).includes(page))??cartRow?.draft.pages[0];
            const draft=(split?cartRow.draft.page_drafts?.[editPage]:cartRow?.draft) || {group_ids:item.match.group_ids,character_ids:item.match.character_ids,feature_tag_ids:item.match.feature_tag_ids,new_tags:[],age_rating:item.x_restrict?'r18':'r12'};
            const allPages=split?[editPage]:cartRow?cartRow.pages:Array.from({length:Math.min(item.page_count,1000)},(_,index)=>index);
            const pages=allPages.filter(page=>cartRow||!(item.imported_pages||[]).includes(page));
            const added=!cartRow&&this.cartItems.some(row=>row.artwork.pid===item.pid);
            let tagDraft=null;
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-reader px-artwork-reader';
            dialog.dataset.workPid=item.pid;
            dialog.innerHTML=`<button class="px-icon-button px-dialog-close" aria-label="关闭" data-close>${icon('close')}</button><div class="px-detail-cover is-loading"><img class="px-reader-image" alt="${esc(item.title)}"><img class="px-reader-thumb" alt="" aria-hidden="true"><div class="px-preview-loader" role="status" aria-label="正在加载清晰预览"><span class="px-loading-orbit" aria-hidden="true"><i></i><i></i><i></i></span>${icon('spark')}</div><button class="px-reader-arrow px-reader-prev" aria-label="上一页">‹</button><button class="px-reader-arrow px-reader-next" aria-label="下一页">›</button><span class="px-reader-status" aria-live="polite">正在加载预览…</span></div><div class="px-detail-body"><div class="px-detail-info"><span class="px-eyebrow">${split?`第 ${editPage+1} 页 · 独立标签`:cartRow?'READY FOR YOUR COLLECTION':'ARTWORK DETAILS'}</span><h3><a class="px-artwork-title" href="https://www.pixiv.net/artworks/${item.pid}" target="_blank" rel="noopener noreferrer" aria-label="在 Pixiv 打开 ${esc(item.title)}">${esc(item.title)}</a></h3><a class="px-artist" href="https://www.pixiv.net/users/${esc(item.author_id)}" target="_blank" rel="noopener noreferrer"><span class="px-artist-avatar"><span class="px-avatar-fallback" aria-hidden="true"><img src="/static/icon/Pic.png" alt=""></span><img class="px-artist-photo" alt="" decoding="async"></span><span class="px-artist-name">${esc(item.author)}</span></a><div class="px-tags">${item.tags.map(tag=>`<span>${esc(tag.translated_name||tag.name)}</span>`).join('')}</div>
                ${cartRow?`<section class="px-cart-tag-section"><h4>入库标签</h4><div id="pixiv-cart-tag-selector"></div><div class="px-legacy-tags"></div><h4>Pixiv 原始标签</h4><p class="px-help">拖到上方已选标签上建立关联，也可点击标签选择关联对象。</p><div class="px-source-tags" aria-label="Pixiv 原始标签"></div><p class="px-tag-feedback" role="status" aria-live="polite"></p>${item.match.conflicts.length?`<p class="px-help">需确认：${esc(item.match.conflicts.join('、'))}</p>`:''}</section><label>年龄分级<select id="pixiv-draft-rating"><option value="all">全年龄</option><option value="r12">R12</option><option value="r16">R16</option><option value="r18">R18</option></select></label>`:''}
                ${library.count?`<p class="px-imported-summary">${icon('check')}${library.label}</p>`:''}${split?'<p class="px-help">本页标签独立保存，请按当前图片确认角色。</p>':item.page_count>1?`<p class="px-help">当前展示清晰预览。勾选需要${cartRow?'保留入库':'加入优选夹'}的页，最多一次选择 100 页。</p>`:(cartRow?'<p class="px-help">这里展示清晰预览，原图用于统一入库。</p>':'')}<div class="px-pages" ${item.page_count>1&&!split?'':'hidden'}>${allPages.map(page=>`<label><input type="checkbox" name="pixiv-page" value="${page}" ${pages.includes(page)?'':'disabled'} ${(cartRow?(split?page===editPage:draft.pages.includes(page)):page===pages[0]&&pages.includes(page))?'checked':''}><span>第 ${page+1} 页${pages.includes(page)?'':' · 已入库'}</span></label>`).join('')}</div></div><div class="px-reader-actions"><button class="px-button ${added||library.complete?'px-added':'px-primary'} px-detail-submit" id="pixiv-draft-submit" ${pages.length&&!added?'':'disabled'}>${cartRow?(split?`确认第 ${editPage+1} 页标签`:'保存标签草稿'):(library.complete?icon('check')+'已入库':added?icon('check')+'已加入':icon('bag')+'加入优选夹')}</button><button class="px-icon-button ${item.liked?'is-liked':''}" data-action="like" data-pid="${item.pid}" aria-pressed="${!!item.liked}" aria-label="${item.liked?'取消喜欢':'喜欢'}">${icon('heart')}</button></div></div>`;
            dialog.querySelector('.px-detail-cover').append(dialog.querySelector('[data-close]'));
            const similar=document.createElement('section');similar.className='px-similar-summary';similar.hidden=!item.similarity?.length;similar.innerHTML=this.similaritySummary(item);dialog.querySelector('.px-detail-info').append(similar);
            similar.onclick=event=>{const button=event.target.closest('[data-similar-image]');if(button)ui.showImageDetail(button.dataset.similarImage);};
            const cover=dialog.querySelector('.px-detail-cover');
            cover.insertAdjacentHTML('beforeend',`<button type="button" class="px-original-island" aria-label="查看原图" disabled>${icon('eye')}<span>查看原图</span></button>`);
            const thumbnail=cover.querySelector('.px-reader-thumb');
            const thumbnailUrl=sourceImage?.currentSrc||sourceImage?.src||cartRow?.preview_url||item.preview_url;
            if(thumbnailUrl)thumbnail.src=thumbnailUrl;else thumbnail.hidden=true;
            thumbnail.onerror=()=>thumbnail.hidden=true;
            if(sourceImage?.naturalWidth&&sourceImage?.naturalHeight)dialog.style.setProperty('--px-reader-image-ratio',String(sourceImage.naturalWidth/sourceImage.naturalHeight));
            document.body.appendChild(dialog);dialog.showModal();
            const opening=this.expandReader(dialog,sourceRect);
            const avatar=dialog.querySelector('.px-artist-photo');
            const avatarUrl=item.author_avatar_url||`/api/pixiv-ol/artworks/${item.pid}/avatar`;
            avatar.removeAttribute('src');
            this.media.load(avatarUrl,`artist:${item.author_id}`).then(async url=>{if(!dialog.isConnected)return;avatar.src=url;await avatar.decode();if(dialog.isConnected)avatar.parentElement.classList.add('is-ready');}).catch(()=>avatar.remove());
            cartReady.then(ok=>{
                if(!ok||!dialog.isConnected||cartRow||dialog.dataset.submitting)return;
                const added=this.cartItems.some(row=>row.artwork.pid===item.pid),submit=dialog.querySelector('#pixiv-draft-submit');
                submit.disabled=library.complete||added||!pages.length;submit.classList.toggle('px-added',added||library.complete);submit.classList.toggle('px-primary',!added&&!library.complete);
                submit.innerHTML=icon(added||library.complete?'check':'bag')+(library.complete?'已入库':added?'已加入':'加入优选夹');
            });
            dialog.querySelectorAll('.px-reader-arrow').forEach(node=>node.hidden=allPages.length<2);
            const close=()=>{
                tagDraft?.destroy();
                dialog.close();dialog.remove();
                const card=source?.closest('.px-card');
                if(card?.isConnected){card.classList.add('px-resting');card.dataset.readerHover=String(card.matches(':hover'));}
            };
            dialog.querySelector('[data-close]').onclick=close;dialog.addEventListener('cancel',event=>{event.preventDefault();close();},{once:true});
            let backdropPress=false;dialog.addEventListener('pointerdown',event=>backdropPress=event.target===dialog);
            dialog.addEventListener('click',event=>{if(backdropPress&&event.target===dialog)close();backdropPress=false;});
            let position=0, pageGeneration=0;
            const image=dialog.querySelector('.px-reader-image'), status=dialog.querySelector('.px-reader-status'),loader=dialog.querySelector('.px-preview-loader'),originalButton=dialog.querySelector('.px-original-island');
            const originalState=(full,state)=>{
                const busy=state==='loading',ready=state==='ready';
                originalButton.disabled=busy||(full&&ready);
                originalButton.classList.toggle('is-loading',full&&busy);
                originalButton.classList.toggle('is-original',full&&ready);
                const label=full?(busy?'加载原图':ready?'原图':'重试原图'):'查看原图';
                originalButton.setAttribute('aria-label',full&&ready?'已显示原图':label);
                originalButton.setAttribute('aria-busy',String(full&&busy));
                originalButton.innerHTML=icon(full&&ready?'check':full&&busy?'refresh':'eye')+`<span>${label}</span>`;
            };
            dialog.addEventListener('close',()=>{pageGeneration++;image.removeAttribute('src');},{once:true});
            const showPage=async (index,full=false)=>{
                const generation=++pageGeneration;
                position=Math.max(0,Math.min(allPages.length-1,index));const page=allPages[position];
                this.readerPages.set(item.pid,page);
                if(cover.classList.contains('is-ready')&&image.currentSrc){thumbnail.hidden=false;thumbnail.src=image.currentSrc;}
                image.removeAttribute('src');
                originalState(full,'loading');
                cover.classList.remove('is-ready');cover.classList.add('is-loading');loader.hidden=false;
                loader.setAttribute('aria-label',full?'正在加载原图':'正在加载清晰预览');
                const pageLabel=item.page_count>1?`第 ${page+1} / ${item.page_count} 页 · `:'';
                status.textContent=pageLabel+(full?'正在加载原图…':'正在加载预览…');status.hidden=false;status.onclick=null;
                dialog.querySelectorAll('.px-reader-prev').forEach(node=>node.disabled=position===0);
                dialog.querySelectorAll('.px-reader-next').forEach(node=>node.disabled=position===allPages.length-1);
                try {
                    if(!dialog.isConnected||generation!==pageGeneration)return;
                    const base=item.reader_preview_url||`/api/pixiv-ol/${cartRow?`cart/${cartRow.id}`:`artworks/${item.pid}`}/reader-preview`;
                    // Originals load directly through authenticated endpoints without the
                    // preview cache's 12 MB blob limit.
                    const originalBase=cartRow?`/api/pixiv-ol/cart/${cartRow.id}/original`:`/api/pixiv-ol/artworks/${item.pid}/original`;
                    const url=full?`${originalBase}?page=${page}`:await this.media.load(`${base}?page=${page}`);
                    if(!dialog.isConnected||generation!==pageGeneration)return;
                    image.src=url;await image.decode();await opening;
                    if(generation!==pageGeneration||!dialog.isConnected)return;
                    dialog.style.setProperty('--px-reader-image-ratio',String(image.naturalWidth/image.naturalHeight));
                    cover.classList.remove('is-loading');cover.classList.add('is-ready');loader.hidden=true;
                    originalState(full,'ready');
                    if(page===0){this.similaritySeen.delete(item.pid);this.queueSimilarity(item.pid);}
                    status.textContent=pageLabel+(full?'原图':'清晰预览');status.hidden=item.page_count===1;
                    const next=allPages[position+1];if(!full&&next!==undefined)this.media.load(`${base}?page=${next}`,undefined,'low').catch(()=>{});
                } catch(error) {if(generation===pageGeneration&&dialog.isConnected){cover.classList.remove('is-loading');loader.hidden=true;originalState(full,'error');status.hidden=false;status.textContent=(full?'原图':'预览')+'加载失败，点击这里重试';status.onclick=()=>showPage(position,full);}}
            };
            originalButton.onclick=()=>showPage(position,true);
            dialog.querySelectorAll('.px-reader-prev').forEach(node=>node.onclick=()=>showPage(position-1));
            dialog.querySelectorAll('.px-reader-next').forEach(node=>node.onclick=()=>showPage(position+1));
            dialog.addEventListener('keydown',event=>{
                if(event.target.matches('input,textarea,select')) return;
                if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();showPage(position+(event.key==='ArrowLeft'?-1:1));}
            });
            dialog.querySelector('[data-action="like"]').onclick=event=>this.toggleLike(item.pid,event.currentTarget).catch(error=>ui.showToast(error.message,'error'));
            if(allPages.length) showPage(Math.max(0,allPages.indexOf(this.readerPages.get(item.pid))));
            if(cartRow) {
                dialog.querySelector('#pixiv-draft-rating').value=draft.age_rating;
                dialog.querySelector('.px-detail-info > .px-tags').remove();
                tagDraft=this.cartTagEditor(dialog,item,draft);
            }
            dialog.querySelector('#pixiv-draft-submit').onclick=async event=>{
                const submit=event.currentTarget;if(submit.disabled)return;submit.disabled=true;
                dialog.dataset.submitting='true';
                const original=submit.innerHTML;
                try {
                    const selectedPages=Array.from(dialog.querySelectorAll('[name="pixiv-page"]:checked'),node=>Number(node.value));
                    if(!selectedPages.length) throw new Error('请至少选择一页');
                    if(selectedPages.length>100) throw new Error('每次最多选择 100 页，请分批加入');
                    if(cartRow) {
                        const payload={pages:selectedPages,...tagDraft.selector.getValue(),new_tags:tagDraft.newTags,age_rating:dialog.querySelector('#pixiv-draft-rating').value};
                        const updated=await request(split?`/cart/${cartRow.id}/pages/${editPage}`:`/cart/${cartRow.id}`,{method:'PUT',body:JSON.stringify(payload)});this.selectTaggedCartItem(updated);close();await this.loadCart();await this.render();ui.showToast(split?`第 ${editPage+1} 页标签已确认`:'标签草稿已保存','success');
                    } else {
                        submit.textContent='正在加入…';const added=await this.add(item.pid,selectedPages,false);
                        if(!added){delete dialog.dataset.submitting;submit.innerHTML=original;submit.disabled=false;return;}
                        if(!dialog.isConnected)return;
                        submit.innerHTML=icon('check')+'已加入';submit.classList.remove('px-primary');submit.classList.add('px-added','is-added');submit.setAttribute('aria-live','polite');
                        await new Promise(resolve=>setTimeout(resolve,550));
                        if(!dialog.isConnected)return;
                        dialog.classList.add('is-leaving');
                        await new Promise(resolve=>setTimeout(resolve,matchMedia('(prefers-reduced-motion:reduce)').matches?0:240));
                        close();
                    }
                } catch(error) {delete dialog.dataset.submitting;ui.showToast(error.message,'error');submit.innerHTML=original;submit.disabled=false;}
            };
        }
        cartTagEditor(reader,item,draft,options={}) {
            const pool=reader.querySelector(`#${options.selectorId||'pixiv-cart-tag-selector'}`),source=reader.querySelector('.px-source-tags');
            const feedback=reader.querySelector('.px-tag-feedback'),root=window.auth.isRoot();
            const selector=new ImageTagSelector(pool.id,{title:options.title||'添加优选夹图片标签',addLabel:'+ 添加标签',allowCreate:true,onChange:()=>renderSource()});
            window.imageTagSelectors[pool.id]=selector;
            selector.setData(options.data||{groups:this.groups,characters:this.characters,featureTags:this.features});
            // Cart drafts start with the server's matches. Respect saved edits on
            // reopening, including tags the user deliberately removed.
            selector.setSelected(draft);
            let newTags=[...(draft.new_tags||[])],chooser=null,dragIndex=null,suppressClickUntil=0;
            const associations=new Map();
            for(const row of item.match.evidence||[]){
                if(row.type==='ignore'||row.basis&&row.basis!=='confirmed_mapping')continue;
                const values=associations.get(row.pixiv_tag)||[];
                values.push({type:row.type==='feature'?'feature_tag':row.type,id:row.id});associations.set(row.pixiv_tag,values);
            }
            const isAssociated=(name,target)=>(associations.get(name)||[]).some(row=>row.type===target.type&&row.id===target.id);
            const busy=new Set();
            const targets=()=>[['group',selector.groups],['character',selector.characters],['feature_tag',selector.featureTags]].flatMap(([type,items])=>items.filter(entity=>selector.getValue()[`${type}_ids`].includes(entity.id)).map(entity=>({type,id:entity.id,name:entity.name,group:entity.group_id})));
            const targetLabel=target=>`${{group:'分组',character:'角色',feature_tag:'特征'}[target.type]} · ${target.name}${target.type==='character'?`（${selector.getLabel('group',target.group)}）`:''}`;
            const renderSource=()=>{
                const current=targets();
                source.innerHTML=item.tags.map((tag,index)=>{
                    const linked=current.filter(row=>isAssociated(tag.name,row));
                    const label=linked.map(targetLabel).join('、');
                    return `<button type="button" class="px-source-tag ${linked.length?'is-associated':''}" data-source-index="${index}" draggable="${root&&!busy.has(tag.name)}" ${!root||busy.has(tag.name)?'disabled':''} title="${esc([tag.translated_name,linked.length?`已关联 ${label}；可继续添加关联`:'点击或拖拽关联'].filter(Boolean).join(' · '))}" aria-label="${esc(tag.name)}${linked.length?`，已关联 ${esc(label)}`:'，关联到入库标签'}"><span>${esc(tag.name)}</span>${linked.length?`${icon('check')}<small>${esc(linked.map(row=>row.name).join(' + '))}</small>`:''}</button>`;
                }).join('');
                if(!root)feedback.textContent='由 Root 建立 Pixiv 标签关联';
            };
            const renderLegacy=()=>{
                const container=reader.querySelector('.px-legacy-tags');
                container.hidden=!newTags.length;
                container.innerHTML=newTags.map((tag,index)=>`<button type="button" class="pm-tag pm-tag-feature_tag" data-legacy-index="${index}" title="原有草稿中的待创建特征标签"><span>${esc(tag)}</span><small>待创建</small><b aria-hidden="true">×</b></button>`).join('');
            };
            reader.querySelector('.px-legacy-tags').onclick=event=>{const tag=event.target.closest('[data-legacy-index]');if(tag){const index=Number(tag.dataset.legacyIndex);if(!confirm(`确认移除待创建标签“${newTags[index]}”？`))return;newTags.splice(index,1);renderLegacy();}};
            const associateMany=async(index,chosen)=>{
                const tag=item.tags[index];
                if(!root||!tag||busy.has(tag.name))return;
                const available=targets(),pending=chosen.filter(target=>!isAssociated(tag.name,target));
                if(!pending.length)return;
                if(pending.some(target=>!available.some(row=>row.type===target.type&&row.id===target.id)))throw new Error('标签池已变化，请重新选择关联');
                busy.add(tag.name);renderSource();feedback.textContent='正在保存关联…';
                try {
                    await request('/tag-mappings/batch',{method:'POST',body:JSON.stringify({bindings:pending.map(target=>({tag:tag.name,target_type:target.type==='feature_tag'?'feature':target.type,target_id:target.id}))})});
                    associations.set(tag.name,[...(associations.get(tag.name)||[]),...pending.map(target=>({type:target.type,id:target.id}))]);this.readingStates.clear();
                    if(reader.isConnected){feedback.textContent=`${tag.name} 已关联到 ${available.filter(target=>isAssociated(tag.name,target)).map(row=>row.name).join(' + ')}`;for(const target of pending){const chip=pool.querySelector(`[data-tag-type="${target.type}"][data-tag-id="${target.id}"]`);chip?.animate([{transform:'scale(1)',opacity:.65},{transform:'scale(1.08)',opacity:1},{transform:'scale(1)',opacity:1}],{duration:350});}}
                } catch(error) {if(reader.isConnected)feedback.textContent=error.message;throw error;}
                finally {busy.delete(tag.name);if(reader.isConnected)renderSource();}
            };
            const associate=(index,target)=>associateMany(index,[target]);
            const clearDrop=()=>pool.querySelectorAll('.is-drop-target').forEach(node=>node.classList.remove('is-drop-target'));
            source.addEventListener('dragstart',event=>{
                const bubble=event.target.closest('[data-source-index]');if(!root||!bubble||bubble.disabled){event.preventDefault();return;}
                dragIndex=Number(bubble.dataset.sourceIndex);event.dataTransfer.setData('application/x-picmanager-pixiv-tag',String(dragIndex));event.dataTransfer.effectAllowed='link';
            });
            source.addEventListener('dragend',()=>{dragIndex=null;clearDrop();});
            const dropTarget=event=>root&&dragIndex!==null&&event.dataTransfer?.types.includes('application/x-picmanager-pixiv-tag')?event.target.closest('[data-tag-type]'):null;
            pool.addEventListener('dragover',event=>{const target=dropTarget(event);clearDrop();if(target){event.preventDefault();event.dataTransfer.dropEffect='link';target.classList.add('is-drop-target');}});
            pool.addEventListener('dragleave',event=>{if(!pool.contains(event.relatedTarget))clearDrop();});
            pool.addEventListener('drop',event=>{
                const chip=dropTarget(event);clearDrop();if(!chip)return;
                event.preventDefault();suppressClickUntil=Date.now()+400;
                associate(dragIndex,{type:chip.dataset.tagType,id:Number(chip.dataset.tagId),name:selector.getLabel(chip.dataset.tagType,Number(chip.dataset.tagId))}).catch(()=>{});dragIndex=null;
            });
            pool.addEventListener('click',event=>{if(Date.now()<suppressClickUntil){event.preventDefault();event.stopImmediatePropagation();}},true);
            source.onclick=event=>{
                const bubble=event.target.closest('[data-source-index]');if(!root||!bubble||bubble.disabled)return;
                const index=Number(bubble.dataset.sourceIndex),options=targets();
                if(!options.length){feedback.textContent='请先用“添加标签”选择入库标签，再建立关联。';return;}
                chooser?.close();chooser?.remove();chooser=document.createElement('dialog');chooser.className='px-dialog px-mapping-dialog px-cart-associate';
                chooser.innerHTML=`<div class="px-detail-body"><button class="px-icon-button px-dialog-close" aria-label="关闭">${icon('close')}</button><span class="px-eyebrow">TAG CONNECTIONS</span><h3>${esc(item.tags[index].name)}</h3><p class="px-help">可同时选择多个标签，例如角色 + 泳装，或两个角色。已有的关联保留，可在标签管理中移除。</p><div class="px-associate-targets">${options.map((target,i)=>{const linked=isAssociated(item.tags[index].name,target);return `<button type="button" class="pm-tag pm-tag-${target.type} ${linked?'is-selected':''}" data-target-index="${i}" aria-pressed="${linked}" ${linked?'disabled':''}>${esc(targetLabel(target))}${linked?'<small>已关联</small>':''}</button>`;}).join('')}</div><p class="px-error" role="alert"></p><button type="button" class="px-button px-primary" data-associate-save disabled>保存关联</button></div>`;
                const popup=chooser,close=()=>{popup.close();popup.remove();if(chooser===popup)chooser=null;};
                document.body.append(popup);popup.showModal();popup.querySelector('.px-dialog-close').onclick=close;popup.addEventListener('cancel',event=>{event.preventDefault();close();});
                const selected=new Set(),save=popup.querySelector('[data-associate-save]');
                popup.querySelectorAll('[data-target-index]').forEach(button=>button.onclick=()=>{
                    const value=Number(button.dataset.targetIndex);if(selected.has(value))selected.delete(value);else selected.add(value);
                    button.classList.toggle('is-selected',selected.has(value));button.setAttribute('aria-pressed',String(selected.has(value)));save.disabled=!selected.size;
                });
                save.onclick=async()=>{
                    save.disabled=true;popup.querySelectorAll('[data-target-index]').forEach(node=>node.disabled=true);
                    try{await associateMany(index,[...selected].map(value=>options[value]));close();}catch(error){popup.querySelector('.px-error').textContent=error.message;save.disabled=false;popup.querySelectorAll('[data-target-index]').forEach(node=>node.disabled=isAssociated(item.tags[index].name,options[Number(node.dataset.targetIndex)]));}
                };
            };
            renderLegacy();renderSource();
            return {selector,get newTags(){return newTags;},destroy(){chooser?.close();chooser?.remove();clearTimeout(selector.searchTimer);delete window.imageTagSelectors[pool.id];}};
        }
        async settings() {
            await this.entities(true);this.preferences=await request('/preferences');
            const root=window.auth.isRoot(),pref=this.preferences,content=this.settingsRoot;
            const rows=this.groups.map(group=>{const p=(pref.groups||{})[group.id]||{},enabled=p.enabled??((pref.inventory||{})[group.id]>0),characters=this.characters.filter(c=>c.group_id===group.id);return `<div class="px-preference-group" data-group="${group.id}"><label><input type="checkbox" ${enabled?'checked':''}><span>${esc(group.name)}</span><small>${((pref.quotas||{})[group.id]*100||0).toFixed(1)}%</small></label><p>${pref.inventory?.[group.id]||0} 张库存</p>${characters.length?`<details class="px-preference-character-fold"><summary>${characters.length} 个角色<span>展开全部</span></summary><div class="px-preference-characters">${characters.map(c=>`<span class="pm-tag pm-tag-character">${esc(c.name)}</span>`).join('')}</div></details>`:'<p class="px-group-no-characters">暂无角色</p>'}</div>`;}).join('');
            content.innerHTML=`<div class="px-preference-layout"><section class="px-preference-panel px-account-panel"><span class="px-eyebrow">PIXIV ACCOUNT</span><a class="px-settings-identity" ${this.account.connected?`href="https://www.pixiv.net/users/${esc(this.account.user_id)}" target="_blank" rel="noopener noreferrer"`:''}><span class="px-settings-avatar"><img src="/static/icon/Pic.png" alt="" data-account-avatar></span><div><h3>${this.account.connected?esc(this.account.name):'连接你的 Pixiv'}</h3>${this.account.connected?`<span class="px-settings-user-id">Pixiv ID · ${esc(this.account.user_id)}</span>`:''}</div></a><p id="pixiv-account-status" class="px-account-status ${this.account.status==='connected'?'is-connected':''}">${this.account.connected?(this.account.status==='connected'?'已连接':'需要重新登录'):'尚未连接'}</p><p class="px-help">${this.account.connected?'推荐与关注更新会使用此账号，偏好与标签关联由你的图库共同决定。':'使用 Pixiv 本站登录，开始发现画作。'}</p><div class="px-account-actions">${root?`<button class="px-button px-primary" data-action="login">${this.account.connected?'重新登录':'登录 Pixiv'}</button>${this.account.connected?'<button class="px-text-button px-remove" data-action="disconnect">解除绑定</button>':''}`:'<span class="px-help">由 Root 连接账号</span>'}</div></section>
                <section class="px-preference-panel px-content-panel"><h3>推荐与内容偏好</h3><fieldset ${root&&this.account.connected?'':'disabled'}><div class="px-preferences"><label>AI 作品<select id="pixiv-ai"><option value="exclude">排除已标记 AI</option><option value="include">包含 AI 作品</option><option value="only">只看 AI 作品</option></select></label><label><input id="pixiv-r18" type="checkbox" ${pref.include_r18?'checked':''}>包含 R18</label><label><input id="pixiv-r18g" type="checkbox" ${pref.include_r18g?'checked':''}>包含 R18G</label><label><input id="pixiv-private" type="checkbox" ${pref.private_following?'checked':''}>同步私密关注</label></div><button class="px-button px-primary" data-action="save-settings">保存偏好与分组选择</button></fieldset></section></div><details class="px-preference-panel px-group-panel"><summary class="px-group-panel-toggle"><h3>参与推荐的分组</h3><span class="px-group-fold-hint" aria-hidden="true"></span></summary><div class="px-group-panel-body"><div class="px-group-panel-heading"><p class="px-help">角色默认收起，展开可查看该分组的全部角色。</p><label>筛选分组或角色<input id="pixiv-group-search" type="search" placeholder="输入名称"></label></div><fieldset ${root&&this.account.connected?'':'disabled'}><div class="px-preference-groups">${rows||'<p class="px-help">请先在分组管理页创建分组。</p>'}</div></fieldset></div></details>`;
            const avatar=content.querySelector('[data-account-avatar]');
            if(this.account.avatar_url)this.media.load(this.account.avatar_url,'account-avatar').then(url=>{if(avatar.isConnected)avatar.src=url;}).catch(()=>{});
            document.getElementById('pixiv-ai').value=pref.ai||'exclude';
            document.getElementById('pixiv-group-search').oninput=event=>{
                const query=event.target.value.trim().toLocaleLowerCase();
                this.settingsRoot.querySelectorAll('[data-group]').forEach(row=>{row.hidden=!row.textContent.toLocaleLowerCase().includes(query);const fold=row.querySelector('details');if(fold){if(query){if(!('beforeSearch' in fold.dataset))fold.dataset.beforeSearch=String(fold.open);fold.open=!row.hidden;}else if('beforeSearch' in fold.dataset){fold.open=fold.dataset.beforeSearch==='true';delete fold.dataset.beforeSearch;}}});
            };
        }
        async saveSettings() {
            const groups={};this.settingsRoot.querySelectorAll('[data-group]').forEach(row=>{groups[row.dataset.group]={enabled:row.querySelector('[type="checkbox"]').checked};});
            await request('/preferences',{method:'PUT',body:JSON.stringify({...this.preferences,groups,ai:document.getElementById('pixiv-ai').value,include_r18:document.getElementById('pixiv-r18').checked,include_r18g:document.getElementById('pixiv-r18g').checked,private_following:document.getElementById('pixiv-private').checked})});this.media.clear();this.readingStates.clear();ui.showToast('推荐偏好已保存','success');await this.settings();
        }
        async editMappings(kind=null,id=null,name='',tags=[],onSaved=null) {
            await this.entities(true);
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-mapping-dialog';
            const choices=[['group','分组',this.groups],['character','角色',this.characters],['feature','特征',this.features]].flatMap(([type,label,items])=>items.map(item=>`<option value="${type}:${item.id}">${label} · ${esc(item.name)}${type==='character'?`（${esc(item.group_name)}）`:''}</option>`)).join('');
            dialog.innerHTML=`<div class="px-detail-body"><button class="px-icon-button px-dialog-close" aria-label="关闭">${icon('close')}</button><span class="px-eyebrow">TAG CONNECTIONS</span><h3>${kind?esc(name)+' · Pixiv 标签':'关联 Pixiv 标签'}</h3><p class="px-help">同一个 Pixiv 标签可关联多个角色或特征。添加关联会保留已有标签，推荐和优选夹共同复用。</p><section class="px-mapping-saved"><h4>已关联标签</h4><div class="px-mapping-list pm-tag-box" aria-live="polite"></div></section><section class="px-mapping-add"><h4>添加关联</h4><label>Pixiv 原始标签${tags.length?`<select data-map-tag>${tags.map(tag=>`<option value="${esc(tag.name)}">${esc(tag.name)}</option>`).join('')}</select>`:'<input data-map-tag type="text" maxlength="255" placeholder="输入原始名称，如 白髪">'}</label>${kind?`<p class="px-help">对应本地${kind==='group'?'分组':kind==='character'?'角色':'特征'}：${esc(name)}</p>`:`<label>筛选本地标签<input data-map-search type="search" placeholder="分组、角色或特征名称"></label><label>对应本地标签<select data-map-target>${choices}<option value="ignore:0">忽略该标签</option></select></label>`}<p class="px-error" role="alert"></p><button class="px-button px-primary" data-map-save>${icon('plus')}添加关联</button></section></div>`;
            document.body.append(dialog);dialog.showModal();
            const close=()=>{dialog.close();dialog.remove();};dialog.querySelector('.px-dialog-close').onclick=close;dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
            const reload=async()=>{const rows=await request(`/tag-mappings${kind?`?target_type=${kind}&target_id=${id}`:''}`);if(!dialog.isConnected)return;const list=dialog.querySelector('.px-mapping-list');list.innerHTML=rows.map(row=>`<span class="pm-tag pm-tag-pixiv" title="${esc(row.tag)} · ${row.source==='exact'?'精确同名':'手动关联'}"><span>${esc(row.tag)}</span><small>${row.source==='exact'?'同名':'关联'}${kind?'':` · ${esc((row.target_type==='group'?this.groups:row.target_type==='character'?this.characters:this.features).find(item=>item.id===row.target_id)?.name||(row.target_type==='ignore'?'忽略':''))}`}</small><button type="button" data-map-delete="${row.id}" aria-label="移除 ${esc(row.tag)}">×</button></span>`).join('')||'<p class="px-help">暂无关联，添加一个 Pixiv 原始标签即可。</p>';list.querySelectorAll('[data-map-delete]').forEach(button=>button.onclick=async()=>{const row=rows.find(row=>String(row.id)===button.dataset.mapDelete);if(!confirm(`确认移除 Pixiv 标签“${row?.tag||'此标签'}”的这条关联？\n该标签的其他关联和已入库图片不会被修改。`))return;button.disabled=true;try{await request(`/tag-mappings/${button.dataset.mapDelete}`,{method:'DELETE'});this.readingStates.clear();await reload();if(onSaved)await onSaved();}catch(error){dialog.querySelector('.px-error').textContent=error.message;button.disabled=false;}});};
            const target=dialog.querySelector('[data-map-target]');if(target){const all=Array.from(target.options).map(option=>({value:option.value,text:option.textContent}));dialog.querySelector('[data-map-search]').oninput=event=>{const q=event.target.value.toLocaleLowerCase();target.replaceChildren(...all.filter(option=>option.text.toLocaleLowerCase().includes(q)).map(option=>new Option(option.text,option.value)));};}
            dialog.querySelector('[data-map-save]').onclick=async event=>{const button=event.currentTarget;button.disabled=true;dialog.querySelector('.px-error').textContent='';try{const tag=dialog.querySelector('[data-map-tag]').value.trim();if(!tag)throw new Error('请输入 Pixiv 原始标签');if(!kind&&!target.value)throw new Error('请先选择对应的本地标签');const [type,value]=kind?[kind,id]:target.value.split(':');if(type==='ignore'&&!confirm(`确认忽略 Pixiv 标签“${tag}”？\n该标签在当前范围内的已有本地关联将被移除。`))return;await request('/tag-mappings',{method:'POST',body:JSON.stringify({tag,target_type:type,target_id:Number(value)||null})});this.readingStates.clear();await reload();if(onSaved)await onSaved();ui.showToast('Pixiv 标签关联已保存','success');if(!tags.length)dialog.querySelector('[data-map-tag]').value='';}catch(error){dialog.querySelector('.px-error').textContent=error.message;}finally{button.disabled=false;}};
            dialog.querySelector('[data-map-tag]').addEventListener('keydown',event=>{if(event.key==='Enter'&&event.target.tagName==='INPUT'){event.preventDefault();dialog.querySelector('[data-map-save]').click();}});
            await reload();
        }
        authorizationInput(value) {
            let input=String(value??'').trim();
            if(input.length>8192)throw new Error('授权内容过长，请只复制本次 callback 链接或授权码。');
            if(input.length>=2&&['""',"''",'“”','‘’'].includes(input[0]+input.at(-1)))input=input.slice(1,-1).trim();
            if(!input)throw new Error('请先粘贴本次登录返回的 callback 链接或授权码。');
            if(/[\s\x00-\x1f\x7f]/.test(input))throw new Error('授权内容包含额外文字或空格，请只复制 callback 链接。');
            input=input.replace(/^https\/\/(?=app-api\.pixiv\.net(?:[/?]|$))/i,'https://');
            if(/^app-api\.pixiv\.net\//i.test(input))input=`https://${input}`;
            if(/^[a-zA-Z0-9._-]{1,2048}$/.test(input))return input;
            try {
                const url=new URL(input),codes=url.searchParams.getAll('code');
                const destination=(url.protocol==='https:'&&url.hostname==='app-api.pixiv.net'&&(!url.port||url.port==='443')&&url.pathname==='/web/v1/users/auth/pixiv/callback')||(url.protocol==='pixiv:'&&url.host==='account'&&url.pathname==='/login');
                if(destination&&!url.username&&!url.password&&!url.hash&&codes.length===1&&/^[a-zA-Z0-9._-]{1,2048}$/.test(codes[0]))return input;
            } catch {}
            throw new Error('未识别到有效授权结果。请复制带 code 的 callback 链接；登录页、/start 和 /post-redirect 地址不能用于连接。');
        }
        async login(mode='default_browser') {
            if(this.loginBusy) return;
            this.loginBusy=true;
            try {
                const session=await request('/account/login',{method:'POST',body:JSON.stringify({mode})});
                if(session.automatic) this.automaticLogin(session);
                else this.manualLogin(session);
            } finally {this.loginBusy=false;}
        }
        automaticLogin(session) {
            clearTimeout(this.loginTimer);this.loginDialog?.remove();this.loginSession=session.id;
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-login-dialog';
            dialog.innerHTML=`<div class="px-detail-body"><h3>连接 Pixiv</h3><p>在默认浏览器中完成 Pixiv 登录。如果浏览器询问是否打开 Pixiv 应用，请允许打开。完成授权后会自动连接，随后回到这里查看结果。</p><p id="pixiv-login-progress" role="status" aria-live="polite">正在准备登录…</p><p id="pixiv-login-error" class="px-error" role="alert"></p><div class="px-dialog-actions"><button class="px-button px-primary" id="pixiv-login-restart" hidden>重新开始登录</button><button class="px-button" id="pixiv-login-cancel">取消登录</button></div></div>`;
            this.loginDialog=dialog;document.body.appendChild(dialog);dialog.showModal();
            const close=async()=>{
                const button=dialog.querySelector('#pixiv-login-cancel');button.disabled=true;
                try {
                    if(!dialog.dataset.terminal) await request(`/account/login/${session.id}`,{method:'DELETE'});
                    if(this.loginSession===session.id) {clearTimeout(this.loginTimer);this.loginSession=null;}
                    dialog.remove();
                } catch(error) {dialog.querySelector('#pixiv-login-error').textContent=error.message;button.disabled=false;}
            };
            dialog.querySelector('#pixiv-login-cancel').onclick=close;
            dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
            dialog.querySelector('#pixiv-login-restart').onclick=async event=>{
                event.currentTarget.disabled=true;
                try {await this.login();}
                catch(error) {dialog.querySelector('#pixiv-login-error').textContent=error.message;event.currentTarget.disabled=false;}
            };
            this.pollLogin(session);
        }
        manualLogin(session) {
            clearTimeout(this.loginTimer);this.loginSession=null;
            this.loginDialog?.remove();
            const dialog=document.createElement('dialog');dialog.className='px-dialog px-login-dialog';
            dialog.innerHTML=`<div class="px-detail-body"><h3>等待提交 Pixiv 授权回调</h3><p>${session.opened?'已请求默认浏览器打开 Pixiv 登录页。':'在浏览器中完成 Pixiv 登录。'}本模式需要手动提交回调。Pixiv 登录后出现白页或“协议未知”时，请返回本窗口，把本次授权回跳链接粘贴到下面。</p><button class="px-button" id="pixiv-login-reopen">重新用默认浏览器打开</button><a class="px-text-button" id="pixiv-login-current" href="${esc(session.url)}" target="_blank" rel="noopener noreferrer">在当前浏览器中打开</a><label>授权回跳链接<input id="pixiv-login-code" type="password" autocomplete="off" placeholder="粘贴 callback 链接或授权码"></label><p class="px-help">登录前按 F12，在 Network 中开启 Preserve log 并筛选 callback，登录后复制带 code 的回跳链接。即使最后显示“协议未知”，仍可复制 callback 请求提交。只复制回调链接，不要打开它；直接粘贴到这里并立即提交。开源实现提示授权码约 30 秒失效，这与本地十分钟登录会话的期限不同；/start 地址和 code_challenge 不是授权结果。</p><p id="pixiv-login-error" class="px-error" role="alert"></p><div class="px-dialog-actions"><button class="px-button px-primary" id="pixiv-login-complete">完成连接</button><button class="px-button px-primary" id="pixiv-login-restart" hidden>重新开始登录</button><button class="px-button" id="pixiv-login-cancel">取消</button></div></div>`;
            this.loginDialog=dialog;document.body.appendChild(dialog);dialog.showModal();
            const terminal=()=>{
                dialog.querySelector('#pixiv-login-complete').disabled=true;
                dialog.querySelector('#pixiv-login-reopen').disabled=true;
                dialog.querySelector('#pixiv-login-code').disabled=true;
                dialog.querySelector('#pixiv-login-current').hidden=true;
                dialog.querySelector('#pixiv-login-restart').hidden=false;
            };
            dialog.querySelector('#pixiv-login-restart').onclick=async event=>{
                const button=event.currentTarget;button.disabled=true;
                try {await this.login();}
                catch(error) {dialog.querySelector('#pixiv-login-error').textContent=error.message;button.disabled=false;}
            };
            dialog.querySelector('#pixiv-login-reopen').onclick=async event=>{
                const button=event.currentTarget;button.disabled=true;
                try {const result=await request(`/account/login/${session.id}/open`,{method:'POST'});dialog.querySelector('#pixiv-login-error').textContent=result.opened?'已请求默认浏览器打开，继续使用本次授权。':'当前环境无法打开系统默认浏览器，请点击“在当前浏览器中打开”。';}
                catch(error) {dialog.querySelector('#pixiv-login-error').textContent=error.message;terminal();}
                finally {button.disabled=!dialog.querySelector('#pixiv-login-restart').hidden;}
            };
            const cancel=()=>{request(`/account/login/${session.id}`,{method:'DELETE'}).catch(()=>{});dialog.remove();};
            dialog.querySelector('#pixiv-login-cancel').onclick=cancel;dialog.addEventListener('cancel',cancel,{once:true});
            dialog.querySelector('#pixiv-login-complete').onclick=async event=>{
                const submit=event.currentTarget,input=dialog.querySelector('#pixiv-login-code'),errorNode=dialog.querySelector('#pixiv-login-error');
                errorNode.textContent='';
                let code;
                try {code=this.authorizationInput(input.value);}
                catch(error) {errorNode.textContent=error.message;input.focus();return;}
                submit.disabled=true;input.value='';
                try {await request(`/account/login/${session.id}/complete`,{method:'POST',body:JSON.stringify({code})});dialog.remove();await this.initSettings();ui.showToast('Pixiv 已连接','success');}
                catch(error) {
                    errorNode.textContent=error.message;
                    try {
                        const result=await request(`/account/login/${session.id}`);
                        if(['failed','expired','cancelled'].includes(result.status)) {terminal();return;}
                        if(result.status==='completed') {dialog.remove();await this.initSettings();ui.showToast('Pixiv 已连接','success');return;}
                    } catch {}
                    submit.disabled=false;
                }
            };
        }
        pollLogin(session) {
            clearTimeout(this.loginTimer);
            this.loginTimer=setTimeout(async()=>{
                if(this.loginSession!==session.id) return;
                const dialog=this.loginDialog;
                try {
                    const result=await request(`/account/login/${session.id}`);
                    if(this.loginSession!==session.id) return;
                    if(result.status==='completed') {dialog?.remove();this.loginSession=null;await this.loadAccount();if(ui.currentPage==='settings') await this.settings();ui.showToast('Pixiv 已连接','success');}
                    else if(['failed','expired','cancelled'].includes(result.status)) {
                        this.loginSession=null;
                        if(dialog?.isConnected) {
                            dialog.dataset.terminal='1';dialog.querySelector('#pixiv-login-progress').textContent='本次登录已结束';
                            dialog.querySelector('#pixiv-login-error').textContent=errors[result.error]||'登录未完成，请重试';
                            dialog.querySelector('#pixiv-login-restart').hidden=false;dialog.querySelector('#pixiv-login-cancel').textContent='关闭';
                        }
                    } else {
                        if(dialog?.isConnected) {
                            dialog.querySelector('#pixiv-login-error').textContent='';
                            dialog.querySelector('#pixiv-login-progress').textContent=result.status==='exchanging'?'正在连接账号…':result.phase==='browser'?'等待你在浏览器中完成授权…':'正在准备登录…';
                        }
                        this.pollLogin(session);
                    }
                } catch(error) {
                    if(this.loginSession===session.id) {
                        if(dialog?.isConnected) dialog.querySelector('#pixiv-login-error').textContent=`${error.message}，正在重新检查登录状态…`;
                        this.pollLogin(session);
                    }
                }
            },1500);
        }
        watch() {
            clearTimeout(this.timer);
            this.timer=setTimeout(async()=>{
                if(ui.currentPage!=='pixiv-ol') return;
                try {
                    const jobs=await this.loadImportJobs();const before=JSON.stringify(this.cartItems.map(row=>[row.id,row.status,row.cached_pages,row.job?.status]));
                    const flows=new Set([this.flow,...Array.from(this.readingStates.values(),state=>state.flow)]);
                    for(const flow of flows) {
                        if(!flow?.continueJob)continue;
                        const job=jobs.find(job=>job.id===flow.continueJob);
                        if(job&&!['queued','running','retry'].includes(job.status))await this.finishContinuation(job,flow);
                    }
                    await this.loadCart();const changed=before!==JSON.stringify(this.cartItems.map(row=>[row.id,row.status,row.cached_pages,row.job?.status]));
                    if(this.view==='cart'&&changed) await this.render();
                    this.updateImportTools();this.offerImportReviews();
                    const count=this.root.querySelector('.px-count');if(count) count.textContent=this.cartCount();
                    const active=jobs.some(job=>['queued','running','retry'].includes(job.status));
                    if(this.pendingRefresh) {
                        const pending=this.pendingRefresh,job=jobs.find(job=>job.id===pending.id);
                        if(job&&!['queued','running','retry'].includes(job.status)) {
                            this.pendingRefresh=null;this.updateRefreshButton();
                            if(job.status==='completed') {
                                this.readingStates.delete(this.readingKey(pending.view,pending.mode));
                                if(this.view===pending.view&&(pending.view==='feed'||this.mode===pending.mode)) {await this.loadAccount();await this.render();}
                            }
                            else if(['failed','partial','cancelled'].includes(job.status))ui.showToast(errors[job.error]||'刷新未完成，可重试','error');
                        }
                    }
                    this.wasActive=active;this.watch();
                } catch(error) {ui.showToast(error.message,'error');}
            },this.pendingRefresh?700:2500);
        }
    }
    window.pixivOL=new PixivOL();
})();
