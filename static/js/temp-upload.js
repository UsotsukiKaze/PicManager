(function () {
    'use strict';
    class TempUploadWorkbench {
        constructor(upload) { this.upload=upload; }
        matchedDraft(result) {
            const match=result?.artwork?.match||{},multiple=result?.artwork?.page_count>1&&(match.character_ids||[]).length>1;
            return {group_ids:match.group_ids||[],character_ids:multiple?[]:match.character_ids||[],feature_tag_ids:match.feature_tag_ids||[],pid:result?.pid||'',age_rating:result?.artwork?.x_restrict?'r18':'r12',description:'',confirmed:false};
        }
        async open(encodedName,source={}) {
            const name=decodeURIComponent(encodedName),upload=this.upload;
            const [groups,characters,featureTags,pixiv]=await Promise.all([api.getGroups(),api.getCharacters(),api.getFeatureTags(),window.auth.loadFeature('pixiv')]);
            if(!upload.tempVisible())return;
            await window.auth.loadStyle('/static/css/pixiv-ol.css?v=20261004l');
            if(!upload.tempVisible())return;
            this.editor?.destroy();
            this.name=name;this.dirty=false;this.closed=false;this.catalogs={groups,characters,featureTags};this.pixiv=pixiv;
            const esc=value=>upload.escapeHtml(value),result=upload.tempResults.get(name),saved=upload.tempDrafts.get(name);
            this.label=upload.tempLabels.get(name)?.display_name||name;
            this.draft=saved&&(saved.touched||saved.confirmed)?saved:this.matchedDraft(result);
            ui.showModal('确认入库标签', `<form id="temp-upload-form" data-image-name="${esc(encodedName)}" class="temp-workbench">
                <section class="temp-workbench-image is-loading" aria-busy="true">
                    <button type="button" class="temp-preview-close" aria-label="关闭详情">×</button>
                    <img class="px-reader-image" alt="${esc(this.label)}" decoding="async">
                    <img class="px-reader-thumb" alt="" aria-hidden="true">
                    <div class="px-preview-loader" role="status" aria-label="正在加载原图"><span class="px-loading-orbit" aria-hidden="true"><i></i><i></i><i></i></span><svg class="px-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.6 6.4L21 12l-6.4 2.6L12 21l-2.6-6.4L3 12l6.4-2.6Z"/></svg></div>
                    <button type="button" class="temp-preview-status" hidden>原图加载失败，点击重试</button>
                </section>
                <section class="temp-workbench-info">
                    <div class="temp-workbench-fields">
                    <header><span class="px-eyebrow">TEMP COLLECTION</span><h3 class="temp-art-title">${esc(this.label)}</h3><p class="temp-art-author"></p><p class="temp-check-note" role="status"></p></header>
                    <div class="px-cart-tag-section"><h4>入库标签</h4><div id="temp-tag-selector"></div><div class="px-legacy-tags"></div><h4>Pixiv 原始标签</h4><p class="px-help">点击标签或拖到已选标签上建立关联。</p><div class="px-source-tags"></div><p class="px-tag-feedback" role="status"></p></div>
                    <div class="temp-pid-fields"><label>PID<input id="temp-pid" class="form-input" value="${esc(this.draft.pid)}" placeholder="作品ID_p0"></label><label class="temp-page-field" hidden>对应页<select id="temp-page-select" class="form-select"></select></label></div>
                    <label class="temp-identity-confirm" hidden><input type="checkbox" id="temp-identity-confirm"> 我已核对当前文件与选定的 Pixiv 页一致</label>
                    <label>年龄分级<select id="temp-age-rating" class="form-select">${['all','r12','r16','r18'].map(value=>`<option value="${value}" ${this.draft.age_rating===value?'selected':''}>${value==='all'?'全年龄':value.toUpperCase()}</option>`).join('')}</select></label>
                    <label>备注<textarea id="temp-description" class="form-textarea">${esc(this.draft.description)}</textarea></label>
                    </div>
                    <footer class="temp-workbench-actions"><button type="submit" class="btn btn-primary">确定信息</button><button type="button" class="temp-delete-button" id="temp-upload-delete" title="删除图片" aria-label="删除图片"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V4h6v2M5 6l1 14h12l1-14M10 10v6M14 10v6"/></svg></button></footer>
                </section>
            </form>`);
            this.form=document.getElementById('temp-upload-form');
            this.layer=this.form.closest('.modal-layer');
            const modal=this.form.closest('.modal');modal.classList.add('temp-workbench-modal');
            this.renderResult(result,this.draft);
            const stopPreview=this.loadPreview(encodedName,source);
            this.form.querySelector('.temp-preview-close').onclick=()=>ui.closeModal();
            this.form.addEventListener('input',()=>{this.dirty=true;});
            this.form.onsubmit=event=>{event.preventDefault();this.confirm();};
            this.form.querySelector('#temp-page-select').onchange=event=>{
                const current=upload.tempResults.get(name);
                if(current?.artwork)this.form.querySelector('#temp-pid').value=event.target.value===''?current.artwork.pid:`${current.artwork.pid}_p${event.target.value}`;
                this.form.querySelector('#temp-identity-confirm').checked=false;
                this.form.querySelector('.temp-identity-confirm').hidden=false;
            };
            document.getElementById('temp-upload-delete')?.addEventListener('click',()=>upload.deleteTempImageFromModal(encodedName));
            upload.tempResultChanged=(changed,next)=>{
                if(changed!==name||!this.form.isConnected)return;
                const selected=this.dirty||saved?.touched||saved?.confirmed?this.values():this.matchedDraft(next);
                this.renderResult(next,selected);
            };
            this.layer._onModalClose=()=>{
                this.closed=true;stopPreview();
                const selected=this.values();
                const confirmed=!!upload.tempDrafts.get(name)?.confirmed&&!this.dirty;
                upload.tempDrafts.set(name,{...upload.tempDrafts.get(name),...selected,confirmed,touched:this.dirty||!!saved?.touched});
                if(!confirmed)upload.tempSelection.delete(name);
                this.editor?.destroy();upload.tempResultChanged=null;modal.classList.remove('temp-workbench-modal');
                upload.updateTempCard(name);upload.updateTempSelection();
            };
        }
        loadPreview(encodedName,source) {
            const form=this.form,cover=form.querySelector('.temp-workbench-image'),image=cover.querySelector('.px-reader-image'),thumbnail=cover.querySelector('.px-reader-thumb');
            const loader=cover.querySelector('.px-preview-loader'),status=cover.querySelector('.temp-preview-status');
            cover.style.setProperty('--temp-image-ratio',String(source.ratio||1));
            if(source.url)thumbnail.src=source.url;else thumbnail.hidden=true;
            thumbnail.onerror=()=>thumbnail.hidden=true;
            const opening=this.pixiv.expandReader(form,source.rect,{cover,details:form.querySelector('.temp-workbench-info')});
            let generation=0,stopped=false;
            const active=()=>!stopped&&this.form===form&&!this.closed&&this.upload.tempVisible();
            const load=async()=>{
                if(!active())return;
                const current=++generation;
                cover.classList.remove('is-ready');cover.classList.add('is-loading');cover.setAttribute('aria-busy','true');loader.hidden=false;status.hidden=true;
                try {
                    image.src='/api/upload/temp-original?filename='+encodedName;
                    await image.decode();await opening;
                    if(!active()||current!==generation)return;
                    cover.style.setProperty('--temp-image-ratio',String(image.naturalWidth/image.naturalHeight));
                    cover.classList.remove('is-loading');cover.classList.add('is-ready');cover.setAttribute('aria-busy','false');loader.hidden=true;
                } catch(error) {
                    if(!active()||current!==generation)return;
                    cover.classList.remove('is-loading');cover.setAttribute('aria-busy','false');loader.hidden=true;status.hidden=false;
                }
            };
            status.onclick=load;load();
            return ()=>{stopped=true;generation++;form.dispatchEvent(new Event('close'));image.removeAttribute('src');thumbnail.removeAttribute('src');};
        }
        renderResult(result,draft) {
            const form=this.form,art=result?.artwork,esc=value=>this.upload.escapeHtml(value);
            this.editor?.destroy();
            const empty={tags:[],match:{evidence:[]}},item=art||empty;
            this.editor=this.pixiv.cartTagEditor(form,item,draft,{selectorId:'temp-tag-selector',title:'添加待处理图片标签',data:this.catalogs});
            const original=this.editor.selector.onChange;
            this.editor.selector.onChange=value=>{this.dirty=true;original?.(value);};
            form.querySelector('.temp-art-title').innerHTML=art?`<a href="https://www.pixiv.net/artworks/${esc(art.pid)}" target="_blank" rel="noopener">${esc(art.title||this.label)}</a>`:esc(this.label);
            form.querySelector('.temp-art-author').textContent=art?`${art.author} · ${this.label}`:this.label;
            const multiple=art?.page_count>1&&(art.match.character_ids||[]).length>1;
            form.querySelector('.temp-check-note').textContent=result?.status==='verified'?'已核对对应页，确认标签后入库。':result?.status==='review'?'页码或画面尚需确认，请核对后勾选下方确认。':result?.status==='ordinary'?'未识别到 Pixiv PID，请手动选择标签。':result?.status==='unavailable'?'Pixiv 暂时不可用，可手动处理或刷新后重试。':'预校验进行中，结果会自动补充。';
            if(multiple)form.querySelector('.temp-check-note').textContent+=' 多角色作品请只选择当前图片的角色。';
            form.querySelector('#temp-pid').value=draft.pid||'';
            form.querySelector('#temp-age-rating').value=draft.age_rating||'r12';
            const parsed=new RegExp(`^${art?.pid}_p(\\d+)$`).exec(draft.pid||''),page=parsed?Number(parsed[1]):result?.page;
            const selector=form.querySelector('#temp-page-select');
            form.querySelector('.temp-page-field').hidden=!art||art.page_count<=1;
            selector.innerHTML='<option value="">请选择对应页</option>'+(art?Array.from({length:art.page_count},(_,index)=>`<option value="${index}" ${page===index?'selected':''}>第 ${index+1} 页</option>`).join(''):'');
            form.querySelector('.temp-identity-confirm').hidden=!art||(result?.status!=='review'&&page===result.page);
            form.querySelector('#temp-identity-confirm').checked=!!draft.identity_confirmed;
        }
        values() {
            return {...this.editor.selector.getValue(),filename:this.name,pid:this.form.querySelector('#temp-pid').value.trim()||null,age_rating:this.form.querySelector('#temp-age-rating').value,description:this.form.querySelector('#temp-description').value||null,identity_confirmed:this.form.querySelector('#temp-identity-confirm').checked};
        }
        confirm() {
            if(!this.form?.isConnected)return;
            const data=this.values(),result=this.upload.tempResults.get(this.name);
            if(!data.group_ids.length||!data.character_ids.length){ui.showToast('请至少选择一个分组和当前图片的角色','warning');return;}
            if(result?.artwork&&data.pid) {
                const parsed=/^(\d+)_p(\d+)$/.exec(data.pid);
                if(!parsed||parsed[1]!==result.artwork.pid||Number(parsed[2])>=result.artwork.page_count){ui.showToast('请选择正确的 Pixiv 对应页；手动处理可清空 PID','warning');return;}
                if((result.status==='review'||Number(parsed[2])!==result.page)&&!data.identity_confirmed){ui.showToast('请先核对图片与对应页，并勾选确认','warning');return;}
                data.pixiv_token=result.token;
            }
            this.upload.tempDrafts.set(this.name,{...data,confirmed:true,touched:true});
            this.upload.tempSelection.add(this.name);this.dirty=false;
            ui.closeModal();this.upload.updateTempCard(this.name);this.upload.updateTempSelection();
            ui.showToast('标签已确认，已选中待入库','success');
        }
    }
    window.TempUploadWorkbench=TempUploadWorkbench;
})();
