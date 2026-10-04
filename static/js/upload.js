// 上传管理类
class UploadManager {
    constructor() {
        this.initializeEventListeners();
        this.batchFiles = [];
        this.singleFile = null;
        this.singleCharacterSelector = null;
        this.singleTagSelector = null;
        this.singlePreviewUrl = null;
        this.singleSubmitting = false;
        this.batchSubmitting = false;
        this.batchWorkerCount = 3;
        this.nextBatchItemId = 1;
        this.batchOptions = null;
        this.duplicateChoiceQueue = Promise.resolve();
        this.tempResults = new Map();
        this.tempLabels = new Map();
        this.tempDrafts = new Map();
        this.tempSelection = new Set();
        this.tempUploading = new Set();
        this.tempGeneration = 0;
        this.tempFilter = 'all';
        this.tempSearch = '';
        window.addEventListener('pagehide', () => this.suspendTemp());
    }

    initializeEventListeners() {
        // 单张上传
        const singleUploadArea = document.getElementById('single-upload-area');
        const singleFileInput = document.getElementById('single-file-input');

        singleUploadArea.addEventListener('click', () => {
            singleFileInput.click();
        });

        singleUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            singleUploadArea.classList.add('dragover');
        });

        singleUploadArea.addEventListener('dragleave', () => {
            singleUploadArea.classList.remove('dragover');
        });

        singleUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            singleUploadArea.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            if (files.length > 0) {
                this.handleSingleFile(files[0]);
            }
        });

        singleFileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                this.handleSingleFile(e.target.files[0]);
            }
        });

        // 批量上传
        const batchUploadArea = document.getElementById('batch-upload-area');
        const batchFileInput = document.getElementById('batch-file-input');

        batchUploadArea.addEventListener('click', () => {
            batchFileInput.click();
        });

        batchFileInput.addEventListener('change', (e) => {
            const files = Array.from(e.target.files);
            this.handleBatchFiles(files);
        });

        batchUploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            batchUploadArea.classList.add('dragover');
        });

        batchUploadArea.addEventListener('dragleave', () => {
            batchUploadArea.classList.remove('dragover');
        });

        batchUploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            batchUploadArea.classList.remove('dragover');
            const files = Array.from(e.dataTransfer.files);
            this.handleBatchFiles(files);
        });
    }

    handleSingleFile(file) {
        if (!this.isValidImageFile(file)) {
            ui.showToast('请选择有效的图片文件', 'error');
            return;
        }

        // 保存文件对象
        this.singleFile = file;
        
        // 显示预览
        this.showSinglePreview(file);
        
        // 显示表单并初始化角色选择器
        document.getElementById('single-upload-form').style.display = 'block';
        
        // 显示文件名和大小信息
        this.showSingleFileInfo(file);
        
        // 初始化角色标签选择器
        if (!this.singleTagSelector) {
            this.singleTagSelector = new ImageTagSelector('single-tag-selector', { title: '添加图片标签' });
            window.imageTagSelectors['single-tag-selector'] = this.singleTagSelector;
        }
        if (window.ui) {
            this.singleTagSelector.setData({
                groups: ui.allGroups || [],
                characters: ui.allCharacters || [],
                featureTags: ui.allFeatureTags || []
            });
        }
    }

    showSinglePreview(file) {
        const preview = document.getElementById('single-preview');
        const img = document.getElementById('single-preview-img');
        const filename = document.getElementById('single-filename');
        const placeholder = document.querySelector('#single-upload-area .upload-placeholder');

        if (this.singlePreviewUrl) {
            URL.revokeObjectURL(this.singlePreviewUrl);
        }
        this.singlePreviewUrl = URL.createObjectURL(file);
        img.src = this.singlePreviewUrl;
        filename.textContent = `文件名: ${file.name}`;
        placeholder.style.display = 'none';
        preview.style.display = 'flex';
    }

    showSingleFileInfo(file) {
        const filenameInfo = document.getElementById('single-filename-info');
        const fileSizeMB = (file.size / 1024 / 1024).toFixed(2);
        filenameInfo.textContent = `(${fileSizeMB} MB) ${file.name}`;
    }

    handleBatchFiles(files) {
        const validFiles = files.filter(file => this.isValidImageFile(file));

        if (validFiles.length === 0) {
            ui.showToast('请选择有效的图片文件', 'error');
            return;
        }

        const newItems = validFiles.map(file => ({
            id: this.nextBatchItemId++,
            file,
            previewUrl: URL.createObjectURL(file),
            status: 'ready',
            progress: 0,
            message: '',
            tags: { group_ids: [], character_ids: [], feature_tag_ids: [] },
            pid: '',
            ageRating: 'r12',
            description: ''
        }));
        this.batchFiles.push(...newItems);
        document.getElementById('tab-batch-upload')?.classList.add('has-batch-files');

        if (!document.querySelector('#batch-upload-list .batch-items')) {
            this.renderBatchList();
        } else {
            newItems.forEach(item => this.appendBatchItem(item));
            this.initializeBatchForms(newItems);
            this.updateBatchControls();
        }
        const input = document.getElementById('batch-file-input');
        if (input) input.value = '';
    }

    renderBatchList() {
        const container = document.getElementById('batch-upload-list');
        container.innerHTML = `
            <div class="batch-header">
                <p id="batch-upload-summary" aria-live="polite"></p>
                <div class="batch-header-actions">
                    <button type="button" id="batch-clear-success" class="btn btn-secondary btn-sm" onclick="upload.clearSuccessfulBatchItems()" hidden>清理已完成</button>
                    <button type="button" id="batch-submit" class="btn btn-primary btn-sm" onclick="upload.processBatchUpload()">开始提交</button>
                </div>
            </div>
            <div class="batch-items"></div>
        `;
        this.batchFiles.forEach(item => this.appendBatchItem(item));
        this.initializeBatchForms(this.batchFiles);
        this.updateBatchControls();
    }

    appendBatchItem(item) {
        const container = document.querySelector('#batch-upload-list .batch-items');
        if (!container) return;
        const safeName = this.escapeHtml(item.file.name);
        const selectorId = `batch-tag-selector-${item.id}`;
        container.insertAdjacentHTML('beforeend', `
            <article class="batch-item" data-batch-id="${item.id}" data-status="${item.status}">
                <div class="batch-preview">
                    <img src="${item.previewUrl}" alt="${safeName} 的预览图" width="120" height="120">
                </div>
                <div class="batch-info">
                    <div class="batch-filename">(${(item.file.size / 1024 / 1024).toFixed(2)} MB) ${safeName}</div>
                    <div class="batch-item-status" role="status" aria-live="polite">
                        <span class="batch-status-badge">待提交</span>
                        <progress class="batch-progress" max="100" value="0" aria-label="上传进度" hidden></progress>
                        <span class="batch-status-message"></span>
                    </div>
                    <div class="batch-form">
                        <div class="batch-form-group">
                            <label class="batch-label" id="batch-tags-label-${item.id}">标签</label>
                            <div class="batch-tag-selector" id="${selectorId}" aria-labelledby="batch-tags-label-${item.id}"></div>
                        </div>
                        <div class="batch-form-group">
                            <label class="batch-label" for="batch-pid-${item.id}">PID</label>
                            <input id="batch-pid-${item.id}" type="text" class="batch-pid form-input" placeholder="可选" value="${this.escapeHtml(item.pid)}">
                        </div>
                        <div class="batch-form-group">
                            <label class="batch-label" for="batch-age-${item.id}">年龄分级</label>
                            <select id="batch-age-${item.id}" class="batch-age-rating form-select">
                                <option value="all">全年龄</option>
                                <option value="r12">R12</option>
                                <option value="r16">R16</option>
                                <option value="r18">R18</option>
                            </select>
                        </div>
                        <div class="batch-form-group">
                            <label class="batch-label" for="batch-description-${item.id}">备注</label>
                            <input id="batch-description-${item.id}" type="text" class="batch-description form-input" placeholder="可不填" value="${this.escapeHtml(item.description)}">
                        </div>
                    </div>
                </div>
                <div class="batch-actions">
                    <button type="button" class="btn btn-primary btn-sm batch-retry" onclick="upload.retryBatchItem(${item.id})" hidden>重试</button>
                    <button type="button" class="btn btn-danger btn-sm batch-remove" onclick="upload.removeBatchItem(${item.id})">删除</button>
                </div>
            </article>
        `);
        const element = this.getBatchElement(item.id);
        element.querySelector('.batch-age-rating').value = item.ageRating;
        element.querySelector('.batch-pid').addEventListener('input', event => { item.pid = event.target.value; });
        element.querySelector('.batch-age-rating').addEventListener('change', event => { item.ageRating = event.target.value; });
        element.querySelector('.batch-description').addEventListener('input', event => { item.description = event.target.value; });
    }

    async initializeBatchForms(items = this.batchFiles) {
        try {
            if (!this.batchOptions) {
                const [groups, characters, featureTags] = await Promise.all([
                    api.getGroups(),
                    api.getCharacters(),
                    api.getFeatureTags()
                ]);
                this.batchOptions = { groups, characters, featureTags };
            }
            items.forEach((item, itemIndex) => {
                if (!this.getBatchElement(item.id)) return;
                const selectorId = `batch-tag-selector-${item.id}`;
                let selector = window.imageTagSelectors[selectorId];
                if (!selector) {
                    selector = new ImageTagSelector(selectorId, {
                        title: `添加第 ${itemIndex + 1} 张图片的标签`,
                        onChange: value => { item.tags = value; }
                    });
                    window.imageTagSelectors[selectorId] = selector;
                }
                selector.setData(this.batchOptions);
                selector.setSelected(item.tags);
            });
        } catch (error) {
            ui.showToast('加载分组信息失败', 'error');
        }
    }

    getBatchElement(itemId) {
        return document.querySelector(`.batch-item[data-batch-id="${itemId}"]`);
    }

    removeBatchItem(itemId) {
        if (this.batchSubmitting) return;
        const index = this.batchFiles.findIndex(item => item.id === Number(itemId));
        if (index < 0) return;
        const [item] = this.batchFiles.splice(index, 1);
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        delete window.imageTagSelectors[`batch-tag-selector-${item.id}`];
        this.getBatchElement(item.id)?.remove();
        this.updateBatchControls();
        if (this.batchFiles.length === 0) {
            document.getElementById('batch-upload-list').innerHTML = '';
            document.getElementById('tab-batch-upload')?.classList.remove('has-batch-files');
        }
    }

    retryBatchItem(itemId) {
        if (this.batchSubmitting) return;
        const item = this.batchFiles.find(candidate => candidate.id === Number(itemId));
        if (!item || item.status !== 'failed') return;
        item.status = 'ready';
        item.message = '';
        item.progress = 0;
        this.updateBatchItemStatus(item);
        this.processBatchUpload([item.id]);
    }

    clearSuccessfulBatchItems() {
        if (this.batchSubmitting) return;
        this.batchFiles
            .filter(item => item.status === 'success' || item.status === 'pending-review')
            .map(item => item.id)
            .forEach(itemId => this.removeBatchItem(itemId));
    }

    syncBatchItemFromDom(item) {
        const element = this.getBatchElement(item.id);
        if (!element) return;
        const selector = window.imageTagSelectors[`batch-tag-selector-${item.id}`];
        item.tags = selector ? selector.getValue() : item.tags;
        item.pid = element.querySelector('.batch-pid')?.value || '';
        item.ageRating = element.querySelector('.batch-age-rating')?.value || 'r12';
        item.description = element.querySelector('.batch-description')?.value || '';
    }

    updateBatchItemStatus(item) {
        const element = this.getBatchElement(item.id);
        if (!element) return;
        const labels = {
            ready: '待提交',
            uploading: '上传中',
            success: '已完成',
            'pending-review': '待审核',
            failed: '失败'
        };
        element.dataset.status = item.status;
        element.querySelector('.batch-status-badge').textContent = labels[item.status] || item.status;
        element.querySelector('.batch-status-message').textContent = item.message || '';
        const progress = element.querySelector('.batch-progress');
        progress.value = item.progress || 0;
        progress.hidden = item.status !== 'uploading';
        element.querySelector('.batch-retry').hidden = item.status !== 'failed';
    }

    updateBatchControls() {
        const counts = this.batchFiles.reduce((result, item) => {
            result[item.status] = (result[item.status] || 0) + 1;
            return result;
        }, {});
        const summary = document.getElementById('batch-upload-summary');
        if (summary) {
            summary.textContent = `共 ${this.batchFiles.length} 张 · 待提交 ${(counts.ready || 0) + (counts.failed || 0)} · 已完成 ${(counts.success || 0) + (counts['pending-review'] || 0)}`;
        }
        const submit = document.getElementById('batch-submit');
        if (submit) {
            submit.disabled = this.batchSubmitting || !this.batchFiles.some(item => item.status === 'ready' || item.status === 'failed');
            submit.textContent = this.batchSubmitting ? '正在提交…' : '提交待处理项';
        }
        const clear = document.getElementById('batch-clear-success');
        if (clear) {
            clear.hidden = !this.batchFiles.some(item => item.status === 'success' || item.status === 'pending-review');
            clear.disabled = this.batchSubmitting;
        }
        document.querySelectorAll('#batch-upload-list button, #batch-upload-list input, #batch-upload-list select')
            .forEach(control => {
                if (!control.matches('#batch-submit, #batch-clear-success')) control.disabled = this.batchSubmitting;
            });
    }

    escapeHtml(value) {
        const element = document.createElement('span');
        element.textContent = String(value || '');
        return element.innerHTML;
    }

    isValidImageFile(file) {
        const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp'];
        return validTypes.includes(file.type);
    }

    formatDuplicateFileSize(bytes) {
        const value = Number(bytes || 0);
        if (!value) return '未知';
        if (value < 1024) return `${value} B`;
        if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`;
        return `${(value / 1024 / 1024).toFixed(2)} MiB`;
    }

    duplicateMetadataRows(item) {
        const text = value => this.escapeHtml(value || '—');
        const list = values => text((values || []).join('、'));
        return `
            <dl class="duplicate-metadata">
                <div><dt>文件</dt><dd>${text(item.original_filename)}</dd></div>
                <div><dt>大小</dt><dd>${this.formatDuplicateFileSize(item.file_size)}</dd></div>
                <div><dt>分辨率</dt><dd>${item.width && item.height ? `${item.width} × ${item.height}` : '未知'}</dd></div>
                <div><dt>PID</dt><dd>${text(item.pid)}</dd></div>
                <div><dt>年龄分级</dt><dd>${text((item.age_rating || 'all').toUpperCase())}</dd></div>
                <div><dt>分组</dt><dd>${list(item.group_names)}</dd></div>
                <div><dt>角色</dt><dd>${list(item.character_names)}</dd></div>
                <div><dt>特征标签</dt><dd>${list(item.feature_tag_names)}</dd></div>
                <div class="duplicate-description"><dt>描述</dt><dd>${text(item.description)}</dd></div>
            </dl>
        `;
    }

    mergedDuplicateItem(items, layer) {
        const keepId = layer.querySelector('input[name="duplicate-file-keep"]:checked')?.value;
        const kept = items.find(item => String(item.image_id) === String(keepId)) || items[0];
        const other = items.find(item => item !== kept) || items[1];
        const sourceFor = field => layer.querySelector(`[data-merge-field="${field}"]`)?.value || 'merge';
        const pick = (field, keepValue, otherValue) => {
            const source = sourceFor(field);
            if (source === 'keep') return keepValue;
            if (source === 'other') return otherValue;
            if (field === 'pid' || field === 'description') {
                return [...new Set([keepValue, otherValue].map(value => String(value || '').trim()).filter(Boolean))].join('\n');
            }
            if (field === 'age_rating') {
                const rank = { all: 0, r12: 1, r16: 2, r18: 3 };
                return rank[otherValue || 'all'] > rank[keepValue || 'all'] ? otherValue : keepValue;
            }
            return [...new Set([...(keepValue || []), ...(otherValue || [])])];
        };
        return {
            ...kept,
            pid: pick('pid', kept.pid, other.pid),
            description: pick('description', kept.description, other.description),
            age_rating: pick('age_rating', kept.age_rating || 'all', other.age_rating || 'all'),
            group_names: pick('groups', kept.group_names, other.group_names),
            character_names: pick('characters', kept.character_names, other.character_names),
            feature_tag_names: pick('feature_tags', kept.feature_tag_names, other.feature_tag_names),
        };
    }

    renderMergedDuplicatePreview(items, layer) {
        const container = layer.querySelector('[data-duplicate-merge-preview]');
        if (!container) return;
        const merged = this.mergedDuplicateItem(items, layer);
        layer.querySelectorAll('[data-image-id]').forEach(card=>card.classList.toggle('is-kept',card.dataset.imageId===String(merged.image_id)));
        container.innerHTML=`<div class="duplicate-result-summary"><span>最终保留</span><strong>${merged.image_id==='new'?'新图片':`库图 ${this.escapeHtml(merged.image_id)}`}</strong><small>${merged.width||'—'} × ${merged.height||'—'} · ${this.formatDuplicateFileSize(merged.file_size)}</small></div>${this.duplicateMetadataRows(merged)}`;
    }

    resolveDuplicateChoice(result, newPreviewUrl = '', options = {}) {
        const choose = () => new Promise(resolve => {
            const incoming=result.incoming;
            const candidates=result.duplicates||[];
            let items=incoming?[candidates[0],{...incoming,image_id:'new',thumbnail_url:newPreviewUrl||incoming.thumbnail_url}]:candidates.slice(0,2);
            if(items.length!==2||items.some(item=>!item)){resolve(null);return;}
            const esc=value=>this.escapeHtml(value);
            const fileCard=(item,index)=>`<article class="duplicate-compare-card" data-image-id="${esc(item.image_id)}"><header><label class="duplicate-keep-option"><input type="radio" name="duplicate-file-keep" value="${esc(item.image_id)}" ${index===0?'checked':''}><span><strong>${item.image_id==='new'?(options.pixiv?'Pixiv 原图':'新图片'):`库内图片${incoming?'':index===0?' A':' B'}`}</strong><small>${esc(item.original_filename||item.image_id)}</small></span></label></header><div class="duplicate-image-frame"><img src="${esc(item.comparison_url||item.thumbnail_url||newPreviewUrl)}" alt="${esc(item.original_filename||item.image_id)}" decoding="async" ${item.image_id!=='new'?`data-original-src="/resource/originals/${esc(item.image_id)}"`:''}></div><p class="duplicate-file-spec">${item.width||'—'} × ${item.height||'—'} <span>${this.formatDuplicateFileSize(item.file_size)}</span></p><details class="duplicate-file-details"><summary>查看原有标签与信息</summary>${this.duplicateMetadataRows(item)}</details></article>`;
            const fields=[['pid','PID'],['description','备注'],['age_rating','年龄分级'],['groups','分组'],['characters','角色'],['feature_tags','特征']];
            const controls=fields.map(([field,label])=>`<label><span>${label}</span><select data-merge-field="${field}" ${field==='pid'&&options.pixiv?'disabled':''}>${field==='pid'&&options.pixiv?'<option value="other">采用本次 Pixiv PID</option>':`<option value="keep" ${field==='characters'?'selected':''}>采用保留图</option><option value="other">采用另一张</option><option value="merge" ${field==='characters'?'':'selected'}>合并两侧</option>`}</select></label>`).join('');
            const overlay=document.getElementById('modal-overlay'),nested=overlay?.style.display==='flex'&&overlay.getAttribute('aria-hidden')!=='true';
            ui.showModal(options.title||'相似图片合并',`<div class="duplicate-review duplicate-review-large duplicate-workbench" role="group" aria-label="相似图片比对"><header class="duplicate-review-heading"><div><span class="temp-eyebrow">COMPARE & MERGE</span><h3>选择保留的图片</h3><p data-duplicate-match-label></p></div>${incoming&&candidates.length>1?`<label class="duplicate-candidate-picker">相似候选<select data-existing-choice>${candidates.map((item,index)=>`<option value="${index}">库图 ${esc(item.image_id)}${item.score?' · '+item.score+'%':''}</option>`).join('')}</select></label>`:''}</header><div class="duplicate-workspace"><div class="duplicate-compare-grid" data-comparison-cards>${items.map(fileCard).join('')}</div><section class="duplicate-merge-panel"><h4>信息来源</h4><p class="duplicate-panel-hint">角色默认采用保留图，可按当前图片调整。</p><div class="duplicate-merge-fields">${controls}</div><h4 class="duplicate-result-title">合并结果</h4><div class="duplicate-merge-preview" data-duplicate-merge-preview></div></section></div><footer class="duplicate-workbench-footer"><p>确认合并后，只保留选定的文件，另一份文件将被删除。</p><div class="duplicate-decision-actions"><button type="button" class="btn btn-secondary" data-duplicate-action="later">稍后处理</button><button type="button" class="btn btn-secondary" data-duplicate-action="distinct">保留两张</button><button type="button" class="btn btn-primary" data-duplicate-action="confirm-merge">确认合并</button></div></footer></div>`,nested);
            const layer=document.getElementById('modal-body')?.lastElementChild;
            let settled=false;
            const finish=value=>{if(settled)return;settled=true;if(layer)delete layer._onModalClose;ui.closeModal();resolve(value);};
            layer._onModalClose=()=>{if(!settled){settled=true;resolve(null);}};
            const render=()=>{
                const match=items[0],hint=layer.querySelector('[data-duplicate-match-label]');
                hint.textContent=match.algorithm==='visual64-grid-v1'?`画面相似度 ${match.score}% · 请核对截图边缘与对应页`:`dHash 差异 ${match.distance??items[1].distance??0} / 64 · 请确认是否为同一张图片`;
                if(options.pixiv){const keep=layer.querySelector('input[name="duplicate-file-keep"]:checked')?.value;const pid=layer.querySelector('[data-merge-field="pid"]');pid.innerHTML=`<option value="${keep==='new'?'keep':'other'}">采用本次 Pixiv PID</option>`;}
                this.renderMergedDuplicatePreview(items,layer);
            };
            const bindFiles=()=>{
                layer.querySelectorAll('input[name="duplicate-file-keep"]').forEach(input=>input.onchange=render);
                layer.querySelectorAll('.duplicate-image-frame img[data-original-src]').forEach(image=>{
                    const fallback=()=>{image.onerror=null;image.src=image.dataset.originalSrc;};
                    image.onerror=fallback;if(image.complete&&!image.naturalWidth)fallback();
                });
            };
            bindFiles();render();
            layer.querySelector('[data-existing-choice]')?.addEventListener('change',event=>{items=[candidates[Number(event.target.value)],items[1]];layer.querySelector('[data-comparison-cards]').innerHTML=items.map(fileCard).join('');bindFiles();render();});
            layer.querySelectorAll('[data-merge-field]').forEach(select=>select.onchange=render);
            layer.querySelector('[data-duplicate-action="later"]').onclick=()=>finish({action:'later'});
            layer.querySelector('[data-duplicate-action="distinct"]').onclick=()=>finish({action:'distinct',otherImageId:items.find(item=>item.image_id!=='new')?.image_id});
            layer.querySelector('[data-duplicate-action="confirm-merge"]').onclick=()=>{
                const keep=layer.querySelector('input[name="duplicate-file-keep"]:checked').value,metadataSources={};
                layer.querySelectorAll('[data-merge-field]').forEach(select=>metadataSources[select.dataset.mergeField]=select.value);
                finish({action:'merge',keep,otherImageId:items.find(item=>item.image_id!=='new')?.image_id,metadataSources});
            };
        });
        const queued=this.duplicateChoiceQueue.then(choose, choose);this.duplicateChoiceQueue=queued.catch(()=>null);return queued;
    }

    async uploadWithDuplicateChoice(file, metadata, onProgress, previewUrl = '', onStage = null) {
        if (onStage) onStage('uploading');
        const firstResult = await api.uploadSingleImage(file, metadata, onProgress);
        if (onStage) onStage('processing');
        if (firstResult?.status !== 'duplicate') return firstResult;
        if (onStage) onStage('attention');
        const decision = await this.resolveDuplicateChoice(firstResult, previewUrl);
        if (!decision) {
            await api.resolveDuplicateImage(firstResult.duplicate_token, 'cancel');
            return { status: 'cancelled', message: '已取消提交' };
        }
        if (onStage) onStage('processing');
        const keep = decision.action === 'merge'
            ? (decision.keep === 'new' ? 'merge-new' : `merge-existing:${decision.keep}`)
            : decision.action;
        return api.resolveDuplicateImage(firstResult.duplicate_token, keep, decision.metadataSources || {});
    }

    duplicateDecisionRequest(decision) {
        if (!decision) return { keep: 'cancel', metadataSources: {} };
        return {
            keep: decision.action === 'merge'
                ? (decision.keep === 'new' ? 'merge-new' : `merge-existing:${decision.keep}`)
                : decision.action,
            metadataSources: decision.metadataSources || {},
        };
    }

    queueStage(taskId, stage) {
        if (!window.uploadQueue || !taskId) return;
        const messages = {
            uploading: '正在发送图片',
            processing: '校验、查重并入库',
            attention: '请处理查重结果',
        };
        uploadQueue.update(taskId, { status: stage, message: messages[stage] || '' });
        if (stage === 'attention') uploadQueue.setOpen(true);
    }

    detachSingleUploadForQueue() {
        // Transfer ownership of the preview URL to the queued task before the
        // form resets, so another single image can be submitted immediately.
        this.singlePreviewUrl = null;
        this.clearSingleUpload();
    }

    async uploadSingleImage(queueContext = null) {
        let context = queueContext;
        try {
            if (!context) {
                const fileInput = document.getElementById('single-file-input');
                const file = this.singleFile || fileInput?.files?.[0];
                if (!file) {
                    ui.showToast('请选择图片文件', 'error');
                    return;
                }

                const selectedTags = this.singleTagSelector ? this.singleTagSelector.getValue() : { group_ids: [], character_ids: [], feature_tag_ids: [] };
                const selectedCharacters = selectedTags.character_ids || [];
                if (selectedCharacters.length === 0) {
                    ui.showToast('请至少选一个角色', 'error');
                    return;
                }
                if ((selectedTags.group_ids || []).length === 0) {
                    ui.showToast('请至少添加一个分组标签', 'error');
                    return;
                }

                context = {
                    file,
                    previewUrl: this.singlePreviewUrl || '',
                    metadata: {
                        character_ids: selectedCharacters,
                        group_ids: selectedTags.group_ids || [],
                        feature_tag_ids: selectedTags.feature_tag_ids || [],
                        age_rating: document.getElementById('single-age-rating')?.value || 'r12',
                        pid: document.getElementById('single-pid').value || null,
                        description: document.getElementById('single-description').value || null
                    },
                    taskId: null,
                };
                if (window.uploadQueue) {
                    context.taskId = uploadQueue.add({
                        name: file.name,
                        size: file.size,
                        retry: () => this.uploadSingleImage(context),
                        dispose: () => {
                            if (context.previewUrl) URL.revokeObjectURL(context.previewUrl);
                            context.previewUrl = '';
                            context.file = null;
                        },
                    });
                }
                this.detachSingleUploadForQueue();
                ui.showToast('上传任务已收进队列，可以继续选择图片', 'info');
            }

            this.queueStage(context.taskId, 'uploading');
            const result = await this.uploadWithDuplicateChoice(context.file, context.metadata, (progress) => {
                if (window.uploadQueue && context.taskId) {
                    uploadQueue.update(context.taskId, { progress, message: progress >= 100 ? '等待服务器处理' : `已上传 ${progress}%` });
                }
            }, context.previewUrl || '', stage => this.queueStage(context.taskId, stage));
            if (result.status === 'cancelled') {
                if (window.uploadQueue && context.taskId) {
                    uploadQueue.update(context.taskId, { status: 'cancelled', message: result.message, retry: null });
                }
                ui.showToast(result.message, 'info');
                return;
            }
            if (window.uploadQueue && context.taskId) {
                uploadQueue.update(context.taskId, { status: 'success', progress: 100, message: result.message, retry: null });
            }
            ui.showToast(result.message, result.status === 'kept_existing' ? 'info' : 'success');
            ui.loadImages(null);
            ui.loadSystemStatus();
        } catch (error) {
            if (window.uploadQueue && context?.taskId) {
                uploadQueue.update(context.taskId, { status: 'failed', message: error.message || '上传失败' });
                uploadQueue.setOpen(true);
            }
            ui.showToast(`上传失败: ${error.message}`, 'error');
        } finally {
            if (context && ['success', 'cancelled'].includes(window.uploadQueue?.get(context.taskId)?.status)) {
                if (context.previewUrl) URL.revokeObjectURL(context.previewUrl);
                context.previewUrl = '';
                context.file = null;
            }
        }
    }

    async processBatchUpload(itemIds = null) {
        if (this.batchSubmitting) return;
        const requestedIds = itemIds ? new Set(itemIds.map(Number)) : null;
        const pendingItems = this.batchFiles.filter(item =>
            (!requestedIds || requestedIds.has(item.id)) &&
            (item.status === 'ready' || item.status === 'failed')
        );
        if (pendingItems.length === 0) {
            ui.showToast('没有待提交或可重试的图片', 'info');
            return;
        }

        this.batchSubmitting = true;
        this.updateBatchControls();
        let successCount = 0;
        let pendingCount = 0;
        let failedCount = 0;

        const processItem = async (item) => {
            this.syncBatchItemFromDom(item);
            if (window.uploadQueue) {
                if (!item.queueTaskId) {
                    item.queueTaskId = uploadQueue.add({
                        name: item.file.name,
                        size: item.file.size,
                        retry: () => this.processBatchUpload([item.id]),
                    });
                } else {
                    uploadQueue.update(item.queueTaskId, { status: 'queued', progress: 0, message: '等待重试' });
                }
            }
            try {
                const selectedTags = item.tags || { group_ids: [], character_ids: [], feature_tag_ids: [] };
                const selectedCharacters = selectedTags.character_ids || [];

                if (selectedCharacters.length === 0) {
                    item.status = 'failed';
                    item.message = '请至少选择一个角色';
                    failedCount++;
                    if (window.uploadQueue && item.queueTaskId) uploadQueue.update(item.queueTaskId, { status: 'failed', message: item.message });
                    this.updateBatchItemStatus(item);
                    return;
                }
                if ((selectedTags.group_ids || []).length === 0) {
                    item.status = 'failed';
                    item.message = '请至少添加一个分组标签';
                    failedCount++;
                    if (window.uploadQueue && item.queueTaskId) uploadQueue.update(item.queueTaskId, { status: 'failed', message: item.message });
                    this.updateBatchItemStatus(item);
                    return;
                }

                const metadata = {
                    character_ids: selectedCharacters,
                    group_ids: selectedTags.group_ids || [],
                    feature_tag_ids: selectedTags.feature_tag_ids || [],
                    age_rating: item.ageRating || 'r12',
                    pid: item.pid || null,
                    description: item.description || null
                };

                item.status = 'uploading';
                item.progress = 0;
                item.message = '';
                const batchElement = this.getBatchElement(item.id);
                if (batchElement) batchElement.dataset.queueCollapsed = 'true';
                this.updateBatchItemStatus(item);
                this.queueStage(item.queueTaskId, 'uploading');
                const result = await this.uploadWithDuplicateChoice(item.file, metadata, (progress) => {
                    item.progress = progress;
                    if (window.uploadQueue && item.queueTaskId) {
                        uploadQueue.update(item.queueTaskId, { progress, message: progress >= 100 ? '等待服务器处理' : `已上传 ${progress}%` });
                    }
                    this.updateBatchItemStatus(item);
                }, item.previewUrl || '', stage => this.queueStage(item.queueTaskId, stage));
                if (result.status === 'cancelled') {
                    item.status = 'ready';
                    item.message = result.message;
                    if (batchElement) delete batchElement.dataset.queueCollapsed;
                    if (window.uploadQueue && item.queueTaskId) uploadQueue.update(item.queueTaskId, { status: 'cancelled', message: result.message });
                    this.updateBatchItemStatus(item);
                    return;
                }
                const message = result && result.message ? result.message : '上传成功';
                const isPending = message.includes('审核');
                item.status = isPending ? 'pending-review' : 'success';
                item.progress = 100;
                item.message = message;
                if (window.uploadQueue && item.queueTaskId) {
                    uploadQueue.update(item.queueTaskId, { status: 'success', progress: 100, message, retry: null });
                }
                this.updateBatchItemStatus(item);
                if (isPending) {
                    pendingCount++;
                } else {
                    successCount++;
                }
            } catch (error) {
                console.error(`上传 ${item.file.name} 失败:`, error);
                item.status = 'failed';
                item.message = error.message || '上传失败，请重试';
                const batchElement = this.getBatchElement(item.id);
                if (batchElement) delete batchElement.dataset.queueCollapsed;
                if (window.uploadQueue && item.queueTaskId) {
                    uploadQueue.update(item.queueTaskId, { status: 'failed', message: item.message });
                    uploadQueue.setOpen(true);
                }
                failedCount++;
                this.updateBatchItemStatus(item);
            }
        };

        // 固定大小的 worker 池避免逐项串行，同时限制并发以保护服务端和带宽。
        let nextItemIndex = 0;
        const worker = async () => {
            while (nextItemIndex < pendingItems.length) {
                const itemIndex = nextItemIndex++;
                await processItem(pendingItems[itemIndex]);
            }
        };
        const activeWorkerCount = Math.min(this.batchWorkerCount, pendingItems.length);
        await Promise.all(Array.from({ length: activeWorkerCount }, () => worker()));

        this.batchSubmitting = false;
        this.updateBatchControls();
        ui.showToast(
            `批量处理完成：成功 ${successCount}，待审核 ${pendingCount}，失败 ${failedCount}`,
            failedCount ? 'warning' : 'success'
        );
        if (successCount + pendingCount > 0) {
            ui.loadImages(null);
            ui.loadSystemStatus();
        }
    }

    clearSingleUpload() {
        // 清空文件输入
        const fileInput = document.getElementById('single-file-input');
        if (fileInput) fileInput.value = '';
        
        // 隐藏预览
        const preview = document.getElementById('single-preview');
        if (preview) preview.style.display = 'none';
        if (this.singlePreviewUrl) {
            URL.revokeObjectURL(this.singlePreviewUrl);
            this.singlePreviewUrl = null;
        }
        
        const placeholder = document.querySelector('#single-upload-area .upload-placeholder');
        if (placeholder) placeholder.style.display = 'flex';
        
        // 隐藏表单
        const form = document.getElementById('single-upload-form');
        if (form) form.style.display = 'none';
        
        // 清空表单内容
        const groupSelect = document.getElementById('single-group-select');
        if (groupSelect) groupSelect.value = '';
        if (this.singleTagSelector) {
            this.singleTagSelector.setSelected({ group_ids: [], character_ids: [], feature_tag_ids: [] });
        }
        
        // 清空角色选择器（使用正确的容器 ID）
        if (this.singleCharacterSelector) {
            this.singleCharacterSelector.clear();
        }
        
        const pidInput = document.getElementById('single-pid');
        if (pidInput) pidInput.value = '';
        const ageRatingInput = document.getElementById('single-age-rating');
        if (ageRatingInput) ageRatingInput.value = 'r12';
        
        const descInput = document.getElementById('single-description');
        if (descInput) descInput.value = '';
        
        // 重置文件引用
        this.singleFile = null;
    }

    tempVisible() { return this.tempActive && ui.currentPage === 'upload' && ui.currentTab === 'temp-upload'; }

    async enterTemp() {
        if (this.tempVisible()) return;
        this.tempActive = true;
        await this.loadTempImages();
    }

    stopTempRun(runId) {
        if (!runId) return;
        fetch('/api/upload/temp-pixiv/stop', {method:'POST', credentials:'same-origin', keepalive:true,
            headers:{'Content-Type':'application/json','X-Pixiv-OL':'1'}, body:JSON.stringify({run_id:runId})}).catch(()=>{});
    }

    suspendTemp() {
        this.tempActive = false;
        this.tempGeneration++;
        this.tempAbort?.abort();
        this.stopTempRun(this.tempRun);
        this.tempRun = null;
        if(document.getElementById('temp-upload-form'))ui.closeModal();
    }

    async loadTempImages() {
        if (!this.tempVisible()) return;
        const oldRun=this.tempRun;
        this.tempAbort?.abort();this.stopTempRun(oldRun);this.tempRun=null;
        const generation=++this.tempGeneration,controller=this.tempAbort=new AbortController();
        try {
            const result=await api.request('/upload/temp-images',{signal:controller.signal});
            if(generation!==this.tempGeneration||!this.tempVisible())return;
            this.tempNames=result.images||[];
            this.tempLabels=new Map((result.items||[]).map(item=>[item.filename,item]));
            const present=new Set(this.tempNames);
            for(const name of this.tempSelection)if(!present.has(name))this.tempSelection.delete(name);
            for(const name of this.tempDrafts.keys())if(!present.has(name))this.tempDrafts.delete(name);
            this.renderTempImages(this.tempNames);
            document.getElementById('temp-image-count').textContent=this.tempNames.length;
            this.precheckTemp(generation,controller).catch(()=>{});
        } catch(error) {
            if(error.name!=='AbortError'&&generation===this.tempGeneration)ui.showToast('加载待处理图片失败','error');
        }
    }

    async precheckTemp(generation,controller) {
        const status=document.getElementById('temp-precheck-status');
        if(status)status.textContent='准备 Pixiv 预校验…';
        let runId;
        try {
            // Let a late start return its ID so it can still be stopped after navigation.
            const started=await api.request('/upload/temp-pixiv/start',{method:'POST',headers:{'Content-Type':'application/json','X-Pixiv-OL':'1'}});
            runId=started.run_id;
            if(generation!==this.tempGeneration||!this.tempVisible()){this.stopTempRun(runId);return;}
            this.tempRun=runId;
            let done=0;
            const names=[...this.tempNames];
            for(const name of names) {
                if(generation!==this.tempGeneration||!this.tempVisible())break;
                if(this.tempUploading.has(name)){done++;continue;}
                if(status)status.textContent=`按列表顺序预校验 ${done} / ${names.length} · 已完成的可立即编辑`;
                try {
                    const result=await api.request('/upload/temp-pixiv/check',{method:'POST',headers:{'Content-Type':'application/json','X-Pixiv-OL':'1'},signal:controller.signal,body:JSON.stringify({run_id:runId,filename:name})});
                    if(generation!==this.tempGeneration||!this.tempVisible())break;
                    this.tempResults.set(name,result);this.updateTempCard(name);
                    this.tempResultChanged?.(name,result);
                } catch(error) {
                    if(error.name==='AbortError'||generation!==this.tempGeneration)break;
                    if(['account_changed','auth_required','permission_revoked','temp_precheck_stopped'].includes(error.message))throw error;
                    this.tempResults.set(name,{filename:name,status:'unavailable',error:error.message});this.updateTempCard(name);
                }
                done++;
            }
            if(generation===this.tempGeneration&&this.tempVisible()&&status)status.textContent=`预校验完成 · ${done} 张`;
        } catch(error) {
            if(generation===this.tempGeneration&&this.tempVisible()&&status)status.textContent='Pixiv 未连接或暂时不可用，可继续手动确认标签';
        } finally {
            this.stopTempRun(runId);
            if(this.tempRun===runId)this.tempRun=null;
        }
    }

    renderTempImages(images) {
        const grid=document.getElementById('temp-image-grid');
        if(!grid)return;
        grid.innerHTML=images.length?images.map(imageName=>{
            const label=this.tempLabels.get(imageName)?.display_name||imageName,encodedName=this.escapeHtml(encodeURIComponent(imageName));
            const escapedName = this.escapeHtml(label);
            return `<article class="temp-image-item" data-image-name="${encodedName}"><label class="temp-select"><input type="checkbox" ${this.tempSelection.has(imageName)?'checked':''} aria-label="选择 ${escapedName}"></label><button type="button" class="temp-image-submit temp-cover" aria-label="确认 ${escapedName} 的标签"><img src="/api/upload/temp-preview?filename=${encodedName}" alt="${escapedName}" loading="lazy" decoding="async"></button><div class="temp-card-footer"><div class="temp-image-name">${escapedName}</div><span class="temp-pixiv-state"></span><div class="temp-image-actions"><button type="button" class="temp-card-edit temp-image-submit">处理标签 <span aria-hidden="true">↗</span></button><button type="button" class="temp-image-delete" aria-label="删除 ${escapedName}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5m4-5v5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button></div></div></article>`;
        }).join(''):'<div class="empty-state">待处理文件夹里没有图片</div>';
        this.tempCards=new Map(Array.from(grid.querySelectorAll('.temp-image-item'),card=>[decodeURIComponent(card.dataset.imageName),card]));
        grid.querySelectorAll('.temp-image-item').forEach(item=>{
            const encodedName=item.dataset.imageName,name=decodeURIComponent(encodedName);
            item.querySelector('.temp-image-submit')?.addEventListener('click', () => this.uploadTempImage(encodedName));
            item.querySelector('.temp-image-actions .temp-image-submit')?.addEventListener('click',()=>this.uploadTempImage(encodedName));
            item.querySelector('.temp-image-delete')?.addEventListener('click',()=>this.deleteTempFile(encodedName));
            item.querySelector('input').onchange=event=>{
                if(event.target.checked&&!this.tempDrafts.get(name)?.confirmed){event.target.checked=false;this.uploadTempImage(encodedName);return;}
                event.target.checked?this.tempSelection.add(name):this.tempSelection.delete(name);this.updateTempCard(name);this.updateTempSelection();
            };
            this.updateTempCard(name);
        });
        this.bindTempBrowse();this.applyTempFilter();this.updateTempSelection();
    }

    bindTempBrowse() {
        const search=document.getElementById('temp-search');
        if(search){search.value=this.tempSearch;search.oninput=()=>{this.tempSearch=search.value;this.applyTempFilter();};}
        document.querySelectorAll('[data-temp-filter]').forEach(button=>{button.onclick=()=>{this.tempFilter=button.dataset.tempFilter;this.applyTempFilter();};});
    }

    applyTempFilter() {
        const query=this.tempSearch.trim().toLocaleLowerCase();let visible=0;
        document.querySelectorAll('#temp-image-grid .temp-image-item').forEach(card=>{
            const name=decodeURIComponent(card.dataset.imageName),result=this.tempResults.get(name),draft=this.tempDrafts.get(name);
            const text=[name,result?.artwork?.pid,result?.artwork?.title,result?.artwork?.author].filter(Boolean).join(' ').toLocaleLowerCase();
            const matches=(!query||text.includes(query))&&(this.tempFilter==='selected'?this.tempSelection.has(name):this.tempFilter==='pending'?!draft?.confirmed:true);
            card.hidden=!matches;if(matches)visible++;
        });
        document.querySelectorAll('[data-temp-filter]').forEach(button=>{const active=button.dataset.tempFilter===this.tempFilter;button.classList.toggle('is-active',active);button.setAttribute('aria-pressed',String(active));});
        const empty=document.getElementById('temp-filter-empty');if(empty)empty.hidden=!!visible||!this.tempNames?.length;
    }

    updateTempCard(name) {
        const card=this.tempCards?.get(name);
        if(!card)return;
        const result=this.tempResults.get(name),draft=this.tempDrafts.get(name);
        const importing=this.tempUploading.has(name),selected=this.tempSelection.has(name);
        card.querySelector('.temp-pixiv-state').textContent=importing?'后台入库中':selected?'已选 · 待入库':draft?.confirmed?'标签已确认':({verified:'Pixiv 已核对 · 可编辑',review:'对应页待确认',ordinary:'手动选择标签',unavailable:'可手动处理'}[result?.status]||'等待预校验');
        card.querySelector('input').checked=selected;card.querySelector('input').disabled=importing;
        card.classList.toggle('is-importing',importing);card.classList.toggle('is-selected',selected);card.classList.toggle('is-ready',!!draft?.confirmed);
        card.dataset.state=importing?'importing':draft?.confirmed?'ready':result?.status||'pending';
        const edit=card.querySelector('.temp-card-edit');if(edit){edit.disabled=importing;edit.firstChild.textContent=draft?.confirmed?'编辑标签 ':'处理标签 ';}
        if(this.tempSearch||this.tempFilter!=='all')this.applyTempFilter();else card.hidden=false;
    }

    updateTempSelection() {
        const button=document.getElementById('temp-import-selected');
        if(button){button.disabled=!this.tempSelection.size;button.textContent=`入库所选${this.tempSelection.size?`（${this.tempSelection.size}）`:''}`;}
    }

    async showTempDuplicateEditor(result, catalogs) {
        const temp = {
            ...(result.temp || {}),
            image_id: 'temp',
            thumbnail_url: `/api/upload/temp-original?filename=${encodeURIComponent(result.filename)}`,
        };
        const stored = result.stored || {};
        const statusLabel = stored.file_status === 'archived' ? '已归档' : '已入库';
        const filename = String(result.filename || '');
        const filenameStem = String(result.filename_stem || filename.replace(/\.[^.]+$/, ''));

        return new Promise(resolve => {
            ui.showModal('Temp 重复图片', `
                <div class="duplicate-review duplicate-review-large temp-duplicate-editor">
                    <p>dHash 差异 ${stored.distance ?? 0}/64。请选择最终保留的文件，并检查下方信息。</p>
                    <div class="duplicate-compare-grid">
                        <article class="duplicate-compare-card">
                            <header><strong>Temp 图片</strong><span>待处理</span></header>
                            <img src="${this.escapeHtml(temp.thumbnail_url)}" alt="Temp 图片" loading="lazy">
                            ${this.duplicateMetadataRows(temp)}
                            <label class="temp-keep-choice"><input type="radio" name="temp-duplicate-keep" value="temp"> 保留 Temp 图片</label>
                        </article>
                        <article class="duplicate-compare-card">
                            <header><strong>${this.escapeHtml((stored.character_names || []).join('、') || '库内图片')}</strong><span>${statusLabel} · ID ${this.escapeHtml(stored.image_id)}</span></header>
                            <img src="${this.escapeHtml(stored.thumbnail_url)}" alt="库内图片" loading="lazy">
                            ${this.duplicateMetadataRows(stored)}
                            <label class="temp-keep-choice"><input type="radio" name="temp-duplicate-keep" value="existing" checked> 保留库内图片${stored.file_status === 'archived' ? '并恢复显示' : ''}</label>
                        </article>
                    </div>
                    <section class="temp-duplicate-metadata-editor">
                        <h4>合并后信息</h4>
                        <div class="form-group">
                            <label for="temp-duplicate-filename">Temp 文件名</label>
                            <div class="temp-filename-row">
                                <input type="text" id="temp-duplicate-filename" class="form-input" value="${this.escapeHtml(filename)}" readonly>
                                <button type="button" class="btn btn-secondary btn-sm" data-copy-temp-filename>复制</button>
                                <button type="button" class="btn btn-secondary btn-sm" data-use-temp-pid>填入 PID</button>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>标签</label>
                            <div id="temp-duplicate-tag-selector"></div>
                        </div>
                        <div class="duplicate-merge-fields">
                            <label>PID<input type="text" id="temp-duplicate-pid" class="form-input" value="${this.escapeHtml(stored.pid || '')}"></label>
                            <label>年龄分级
                                <select id="temp-duplicate-age-rating" class="form-select">
                                    ${['all', 'r12', 'r16', 'r18'].map(value => `<option value="${value}" ${value === (stored.age_rating || 'all') ? 'selected' : ''}>${value === 'all' ? '全年龄' : value.toUpperCase()}</option>`).join('')}
                                </select>
                            </label>
                        </div>
                        <div class="form-group">
                            <label for="temp-duplicate-description">备注</label>
                            <textarea id="temp-duplicate-description" class="form-textarea">${this.escapeHtml(stored.description || '')}</textarea>
                        </div>
                    </section>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" data-temp-duplicate-cancel>停止扫描</button>
                        <button type="button" class="btn btn-primary" data-temp-duplicate-confirm>确认合并</button>
                    </div>
                </div>
            `);

            const layer = document.getElementById('modal-body')?.lastElementChild;
            const selector = new ImageTagSelector('temp-duplicate-tag-selector', { title: '编辑合并后标签' });
            window.imageTagSelectors['temp-duplicate-tag-selector'] = selector;
            selector.setData(catalogs);
            selector.setSelected({
                group_ids: stored.group_ids || [],
                character_ids: stored.character_ids || [],
                feature_tag_ids: stored.feature_tag_ids || [],
            });

            let settled = false;
            const finish = value => {
                if (settled) return;
                settled = true;
                delete window.imageTagSelectors['temp-duplicate-tag-selector'];
                if (layer) delete layer._onModalClose;
                ui.closeModal();
                resolve(value);
            };
            if (layer) {
                layer._onModalClose = () => {
                    if (settled) return;
                    settled = true;
                    delete window.imageTagSelectors['temp-duplicate-tag-selector'];
                    resolve(null);
                };
            }
            layer?.querySelector('[data-copy-temp-filename]')?.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(filename);
                    ui.showToast('文件名已复制', 'success');
                } catch (_error) {
                    const input = layer.querySelector('#temp-duplicate-filename');
                    input?.select();
                    ui.showToast('请按 Ctrl+C 复制文件名', 'info');
                }
            });
            layer?.querySelector('[data-use-temp-pid]')?.addEventListener('click', () => {
                const input = layer.querySelector('#temp-duplicate-pid');
                if (input) input.value = filenameStem;
            });
            layer?.querySelector('[data-temp-duplicate-cancel]')?.addEventListener('click', () => finish(null));
            layer?.querySelector('[data-temp-duplicate-confirm]')?.addEventListener('click', () => {
                const selected = selector.getValue();
                if (!(selected.character_ids || []).length || !(selected.group_ids || []).length) {
                    ui.showToast('请至少保留一个分组和角色', 'error');
                    return;
                }
                finish({
                    keep: layer.querySelector('input[name="temp-duplicate-keep"]:checked')?.value || 'existing',
                    metadata: {
                        character_ids: selected.character_ids || [],
                        group_ids: selected.group_ids || [],
                        feature_tag_ids: selected.feature_tag_ids || [],
                        pid: layer.querySelector('#temp-duplicate-pid')?.value || null,
                        description: layer.querySelector('#temp-duplicate-description')?.value || null,
                        age_rating: layer.querySelector('#temp-duplicate-age-rating')?.value || 'all',
                    },
                });
            });
        });
    }

    async scanTempDuplicates() {
        const button = document.getElementById('scan-temp-duplicates-button');
        if (button?.disabled) return;
        let handled = 0;
        try {
            if (button) {
                button.disabled = true;
                button.textContent = '扫描中…';
            }
            const [groups, characters, featureTags] = await Promise.all([
                api.getGroups(), api.getCharacters(), api.getFeatureTags(),
            ]);
            const catalogs = { groups, characters, featureTags };
            while (true) {
                const scan = await api.scanTempDuplicates(1);
                const match = (scan.matches || [])[0];
                if (!match) break;
                const decision = await this.showTempDuplicateEditor(match, catalogs);
                if (!decision) {
                    ui.showToast(`已停止扫描；本次合并 ${handled} 张`, 'info');
                    return;
                }
                const result = await api.resolveTempDuplicate(
                    match.duplicate_token,
                    decision.keep,
                    decision.metadata,
                );
                handled += 1;
                ui.showToast(result.message, 'success');
                await this.loadTempImages();
                await ui.updateTempCount();
            }
            ui.showToast(handled ? `Temp 查重完成：合并 ${handled} 张` : 'Temp 中没有重复图片', 'success');
            await this.loadTempImages();
            await ui.updateTempCount();
            ui.loadImages(null);
            ui.loadSystemStatus();
        } catch (error) {
            ui.showToast(`Temp 查重失败: ${error.message}`, 'error');
        } finally {
            if (button) {
                button.disabled = false;
                button.textContent = '扫描重复';
            }
        }
    }

    async uploadTempImage(imageNameEncoded) {
        if(this.tempOpening||this.tempUploading.has(decodeURIComponent(imageNameEncoded)))return;
        const card=this.tempCards?.get(decodeURIComponent(imageNameEncoded));
        const sourceImage=card?.querySelector('.temp-cover img');
        const source={rect:sourceImage?.getBoundingClientRect(),url:sourceImage?.currentSrc||sourceImage?.src,ratio:sourceImage?.naturalWidth&&sourceImage?.naturalHeight?sourceImage.naturalWidth/sourceImage.naturalHeight:1};
        this.tempOpening=true;
        try {
            if(!window.TempUploadWorkbench)await window.auth.loadScript('/static/js/temp-upload.js?v=20261004s');
            this.tempWorkbench ||= new window.TempUploadWorkbench(this);
            await this.tempWorkbench.open(imageNameEncoded,source);
        } catch(error) {ui.showToast(error.message||'加载表单失败','error');}
        finally {this.tempOpening=false;}
    }

    submitTempUpload() { return this.tempWorkbench?.confirm(); }

    async importTempSelected() {
        const names=[...this.tempSelection].filter(name=>this.tempDrafts.get(name)?.confirmed&&!this.tempUploading.has(name));
        if(!names.length)return;
        const pending=names.map(name=>({name,data:JSON.parse(JSON.stringify(this.tempDrafts.get(name))),taskId:window.uploadQueue?.add({name:this.tempLabels.get(name)?.display_name||name,status:'queued',message:'等待入库'})}));
        for(const item of pending){this.tempSelection.delete(item.name);this.tempUploading.add(item.name);this.updateTempCard(item.name);}
        this.updateTempSelection();
        let next=0;
        const worker=async()=>{while(next<pending.length){const item=pending[next++];await this.processTempDraft(item.name,item.data,item.taskId);}};
        await Promise.all(Array.from({length:Math.min(2,pending.length)},worker));
        if(this.tempVisible())await this.loadTempImages();
        await ui.updateTempCount();ui.loadSystemStatus();
    }

    async processTempDraft(name,data,taskId=null) {
        this.tempUploading.add(name);this.tempSelection.delete(name);this.updateTempCard(name);this.updateTempSelection();
        taskId ??= window.uploadQueue?.add({name:this.tempLabels.get(name)?.display_name||name,status:'queued',message:'等待入库'});
        window.uploadQueue?.update(taskId,{status:'processing',message:'正在入库',retry:null});
        try {
            let result=await api.uploadTempImage(data);
            if(result?.status==='duplicate') {
                window.uploadQueue?.update(taskId,{status:'attention',message:'请确认重复图片'});
                const decision=await this.resolveDuplicateChoice(result,'/api/upload/temp-original?filename='+encodeURIComponent(name));
                const choice=this.duplicateDecisionRequest(decision);
                result=await api.resolveDuplicateImage(result.duplicate_token,choice.keep,choice.metadataSources);
            }
            if(result.status==='cancelled') {
                window.uploadQueue?.update(taskId,{status:'cancelled',message:'已取消入库'});
                this.tempSelection.add(name);
            } else {
                window.uploadQueue?.update(taskId,{status:'success',progress:100,message:result.message||'入库完成'});
                this.tempDrafts.delete(name);this.tempResults.delete(name);
                this.tempNames=(this.tempNames||[]).filter(item=>item!==name);
                const count=document.getElementById('temp-image-count');if(count)count.textContent=this.tempNames.length;
                const card=Array.from(document.querySelectorAll('#temp-image-grid [data-image-name]')).find(node=>node.dataset.imageName===encodeURIComponent(name));card?.remove();
            }
        } catch(error) {
            this.tempSelection.add(name);
            window.uploadQueue?.update(taskId,{status:'failed',message:error.message,retry:()=>this.processTempDraft(name,data,taskId)});
            ui.showToast('入库失败：'+(error.message==='temp_precheck_expired'?'预校验已过期，请重新打开图片确认':error.message),'error');
        } finally {this.tempUploading.delete(name);this.updateTempCard(name);this.updateTempSelection();}
    }

    async deleteTempFile(imageNameEncoded) {
        const imageName = decodeURIComponent(imageNameEncoded);
        if (!confirm(`确定要删除 ${imageName} 吗？`)) {
            return;
        }
        
        try {
            await api.deleteTempImage(imageName);
            ui.showToast(`${imageName} 已删除`, 'success');
            
            // 刷新temp图片列表
            await this.loadTempImages();
            await ui.updateTempCount();
            
            // 刷新系统状态
            ui.loadSystemStatus();
        } catch (error) {
            ui.showToast(`删除失败: ${error.message}`, 'error');
        }
    }
    
    async deleteTempImageFromModal(imageNameEncoded) {
        const imageName = decodeURIComponent(imageNameEncoded);
        const button=this.tempWorkbench?.name===imageName?this.tempWorkbench.form?.querySelector('#temp-upload-delete'):null;
        if(button?.disabled)return;
        if (!confirm(`确定要删除 ${imageName} 吗？`)) {
            return;
        }
        if(button)button.disabled=true;
        
        try {
            await api.deleteTempImage(imageName);
            ui.showToast(`${imageName} 已删除`, 'success');
            
            // 关闭模态框
            ui.closeModal();
            
            // 刷新temp图片列表
            await this.loadTempImages();
            await ui.updateTempCount();
            
            // 刷新系统状态
            ui.loadSystemStatus();
        } catch (error) {
            ui.showToast(`删除失败: ${error.message}`, 'error');
        } finally {
            if(button?.isConnected)button.disabled=false;
        }
    }

    async refreshTempImages() {
        await this.loadTempImages();
        await ui.updateTempCount();
        ui.showToast('temp目录已刷新', 'success');
    }
}

// 全局函数
function uploadSingleImage() {
    upload.uploadSingleImage();
}

function clearSingleUpload() {
    upload.clearSingleUpload();
}

function refreshTempImages() {
    upload.refreshTempImages();
}

function scanTempDuplicates() {
    upload.scanTempDuplicates();
}

// 创建全局上传管理实例
window.upload = new UploadManager();
