(function(){
'use strict';
window.PicManagerShell={
 init(){
  const toggle=document.getElementById('sidebar-toggle'),sidebar=document.querySelector('.sidebar');
  if(!toggle||toggle.dataset.bound)return;toggle.dataset.bound='true';
  const apply=collapsed=>{document.documentElement.classList.toggle('sidebar-collapsed',collapsed);toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',collapsed?'展开侧栏':'收起侧栏');toggle.querySelector('.shell-toggle-label').textContent=collapsed?'展开侧栏':'收起侧栏';try{localStorage.setItem('picmanager.sidebarCollapsed',String(collapsed));}catch{};window.setTimeout(()=>ui.updateSidebarIndicator(),260);};
  let collapsed=false;try{collapsed=localStorage.getItem('picmanager.sidebarCollapsed')==='true';}catch{};apply(collapsed);
  toggle.onclick=()=>apply(!document.documentElement.classList.contains('sidebar-collapsed'));
  sidebar.addEventListener('transitionend',()=>ui.updateSidebarIndicator());
  sidebar.querySelectorAll('.menu-item').forEach(link=>link.title=link.querySelector('.menu-text')?.textContent||'');
  const auto=document.getElementById('pixiv-check-auto');if(auto){try{auto.checked=localStorage.getItem('picmanager.pixivAutoReview')==='true';}catch{};auto.onchange=()=>{try{localStorage.setItem('picmanager.pixivAutoReview',String(auto.checked));}catch{}};}
  window.addEventListener('message',async event=>{if(event.origin!==location.origin||event.source!==document.getElementById('profile-frame')?.contentWindow||event.data?.type!=='picmanager-profile-updated')return;await auth.checkAuth();auth.updateUI();});
 },
 enhanceTagEditor(formId,kind,id){
  const form=document.getElementById(formId);if(!form||form.dataset.enhanced)return;form.dataset.enhanced='true';form.classList.add('tag-editor');
  const safe=value=>ui.escapeHomeRankingText(value??''),label={group:'分组',character:'角色',feature:'特征'}[kind];
  const fields=Array.from(form.children).filter(node=>node.classList.contains('form-group')),actions=form.querySelector('.form-actions');
  const basic=document.createElement('section');basic.className='tag-editor-panel';basic.id=`${formId}-basic`;basic.setAttribute('role','tabpanel');
  const layout=document.createElement('div');layout.className='tag-editor-fields';const main=document.createElement('div');main.className='tag-editor-main';const side=document.createElement('aside');side.className='tag-editor-avatar';
  fields.forEach(field=>{if(field.querySelector('.avatar-upload-field')){side.append(field);field.querySelector('.avatar-upload-actions small').textContent='上传图片后可选择头像裁剪范围。';}else if(field.querySelector('textarea')||field.querySelector('[id$="feature-selector"]')){field.classList.add('tag-editor-wide');layout.append(field);}else main.append(field);});
  layout.prepend(main);if(side.children.length)main.after(side);else layout.classList.add('tag-editor-no-avatar');basic.append(layout);
  const intro=document.createElement('p');intro.className='tag-editor-intro';intro.textContent=`${label}名称用于图库展示；别称用于识别同一标签，Pixiv 原始标签可单独建立关联。`;
  form.prepend(intro,basic);if(actions){actions.classList.add('tag-editor-actions');actions.querySelector('[type=submit]').textContent='保存资料';}
  const commits=[];
  form.querySelectorAll('input[id$="aliases"],input[id$="nicknames"]').forEach(original=>{
   const values=[...new Set(original.value.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean))];original.type='hidden';
   const box=document.createElement('div');box.className='tag-editor-alias-box pm-tag-box';const tokens=document.createElement('span');tokens.className='tag-editor-alias-tokens';const entry=document.createElement('input');entry.type='text';entry.id=`${original.id}-entry`;entry.placeholder='输入别称，按 Enter 添加';entry.maxLength=255;entry.autocomplete='off';box.append(tokens,entry);original.after(box);original.closest('.form-group').querySelector('label').htmlFor=entry.id;
   const render=()=>{original.value=values.join(', ');tokens.innerHTML=values.map((value,index)=>`<button type="button" class="pm-tag" data-alias-index="${index}" aria-label="移除别称 ${safe(value)}"><span>${safe(value)}</span><b aria-hidden="true">×</b></button>`).join('');tokens.querySelectorAll('button').forEach(button=>{button.onpointerdown=event=>event.preventDefault();button.onclick=()=>{const index=Number(button.dataset.aliasIndex);commit();values.splice(index,1);render();};});};
   const commit=()=>{if(!entry.value.trim())return;for(const value of entry.value.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean)){if(!values.includes(value))values.push(value);}entry.value='';render();};commits.push(commit);render();entry.onblur=commit;entry.onkeydown=event=>{if(event.isComposing)return;if(['Enter',',','，'].includes(event.key)){event.preventDefault();commit();}else if(event.key==='Backspace'&&!entry.value&&values.length){values.pop();render();}};
   const help=document.createElement('small');help.className='tag-editor-field-help';help.textContent='支持逗号分隔多个别称，点击标签可移除。';box.after(help);
  });
  form.addEventListener('submit',()=>commits.forEach(commit=>commit()),true);
  if(!id||!auth.isRoot())return;
  const tabs=document.createElement('div');tabs.className='tag-editor-tabs';tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',`${label}编辑`);tabs.innerHTML=`<button type="button" role="tab" id="${formId}-basic-tab" aria-controls="${basic.id}" aria-selected="true">基本资料</button><button type="button" role="tab" id="${formId}-pixiv-tab" aria-controls="${formId}-pixiv" aria-selected="false" tabindex="-1">Pixiv 标签</button>`;
  basic.setAttribute('aria-labelledby',`${formId}-basic-tab`);const panel=document.createElement('section');panel.className='tag-editor-panel tag-editor-pixiv';panel.id=`${formId}-pixiv`;panel.hidden=true;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby',`${formId}-pixiv-tab`);panel.innerHTML='<h3>关联的 Pixiv 标签</h3><p class="tag-editor-intro">这些原始标签会匹配到当前本地标签。关联立即保存，基本资料需单独保存。</p><div class="tag-editor-mapping-chips pm-tag-box" aria-live="polite"></div><button type="button" class="btn btn-secondary" data-editor-map>添加或调整关联</button>';
  basic.before(tabs);basic.after(panel);
  const load=async()=>{const chips=panel.querySelector('.tag-editor-mapping-chips');chips.textContent='正在加载关联…';try{await auth.loadStyle('/static/css/pixiv-ol.css?v=20261004f');const rows=await api.request(`/pixiv-ol/tag-mappings?target_type=${kind}&target_id=${id}`);if(!panel.isConnected)return;chips.innerHTML=rows.map(row=>`<span class="pm-tag pm-tag-pixiv"><span>${safe(row.tag)}</span><small>${row.source==='exact'?'同名关联':'手动关联'}</small></span>`).join('')||'<span class="tag-editor-empty">还没有关联，添加 Pixiv 原始标签后即可复用。</span>';}catch(error){chips.textContent=error.message;}};
  const select=selected=>{const pixiv=selected===1;basic.hidden=pixiv;panel.hidden=!pixiv;tabs.querySelectorAll('button').forEach((button,index)=>{button.setAttribute('aria-selected',String(index===selected));button.tabIndex=index===selected?0:-1;});if(actions){actions.querySelector('[type=submit]').hidden=pixiv;actions.querySelector('[type=button]').textContent=pixiv?'关闭':'取消';}if(pixiv)load();};
  tabs.querySelectorAll('button').forEach((button,index)=>{button.onclick=()=>select(index);button.onkeydown=event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const selected=event.key==='Home'?0:event.key==='End'?1:1-index;select(selected);tabs.children[selected].focus();}};});
  panel.querySelector('[data-editor-map]').onclick=async()=>{try{await auth.loadStyle('/static/css/pixiv-ol.css?v=20261004f');const feature=await auth.loadFeature('pixiv');const name=form.querySelector('input[id$="name"]').value;await feature.editMappings(kind,id,name,[],load);}catch(error){ui.showToast(error.message,'error');}};
 },
 openProfile(){
  const frame=document.getElementById('profile-frame');if(frame.dataset.loaded)return;frame.dataset.loaded='true';
  frame.onload=()=>{const doc=frame.contentDocument;if(!doc)return;doc.documentElement.dataset.theme=document.documentElement.dataset.theme||'light';const fit=()=>{const height=Math.ceil(doc.querySelector('.profile-container')?.getBoundingClientRect().height||600);if(Math.abs(frame.clientHeight-height)>2)frame.style.height=`${height}px`;};this.profileResize?.disconnect();this.profileResize=new ResizeObserver(fit);this.profileResize.observe(doc.body);fit();};
  frame.src='/profile?embedded=1&v=20261004f';
 }
};
window.managePixivMappings=async(kind,id)=>{try{await auth.loadStyle('/static/css/pixiv-ol.css?v=20261004f');const pixiv=await auth.loadFeature('pixiv');await pixiv.entities(true);const entity=(kind==='group'?pixiv.groups:kind==='character'?pixiv.characters:pixiv.features).find(item=>item.id===id);if(!entity)throw new Error('标签已删除，请刷新列表');await pixiv.editMappings(kind,id,entity.name);}catch(error){ui.showToast(error.message,'error');}};
window.runLocalValidation=async()=>{
 if(!auth.isAdmin())return;
 const button=document.getElementById('local-check-button'),stop=document.getElementById('local-check-stop'),status=document.getElementById('local-check-status');if(button.disabled)return;
 button.disabled=true;stop.hidden=false;window.localValidationStop=false;
 let cursor='',processed=0,failed=0,archived=0,moved=0;
 try{
  do{if(window.localValidationStop){status.textContent=`已停止，本次检查 ${processed} 张；已完成的校验保留。`;return;}
   status.textContent=`正在检查文件和缩略图… ${processed} 张`;
   const result=await api.request(`/system/local-check?after_id=${encodeURIComponent(cursor)}&limit=200`,{method:'POST'});cursor=result.cursor;processed+=result.processed;failed+=result.failed.length;archived+=result.archived;moved+=result.orphans_moved;if(!result.remaining)break;
  }while(true);
  if(window.localValidationStop){status.textContent='文件检查已停止，稍后可重新运行。';return;}
  status.textContent='文件检查完成，正在审核疑似重复图片…';
  const duplicates=await scanExistingDuplicates(true);
  status.textContent=`${duplicates?.status==='complete'?'本地校验完成':'本地校验待继续'}：检查 ${processed} 张，失败 ${failed} 张，归档 ${archived} 条，移回 ${moved} 个孤立文件${duplicates?.deferred?`，${duplicates.deferred} 对重复图片待确认`:''}。`;
  await ui.loadSystemStatus();
 }catch(error){status.textContent=`本地校验失败：${error.message}`;ui.showToast(status.textContent,'error');}
 finally{button.disabled=false;stop.hidden=true;}
};
})();
