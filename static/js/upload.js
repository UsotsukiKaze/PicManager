// 上传管理类
class UploadManager {
    constructor() {
        this.initializeEventListeners();
        this.batchFiles = [];
        this.singleFile = null;
        this.singleCharacterSelector = null;
        this.singleTagSelector = null;
        this.tempLoadTimer = null;
        this.singlePreviewUrl = null;
        this.singleSubmitting = false;
        this.batchSubmitting = false;
        this.batchWorkerCount = 3;
        this.nextBatchItemId = 1;
        this.batchOptions = null;
        this.duplicateChoiceQueue = Promise.resolve();
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
            ageRating: 'all',
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
        item.ageRating = element.querySelector('.batch-age-rating')?.value || 'all';
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
        const title = (merged.character_names || []).join('、') || '合并后图片';
        container.innerHTML = `
            <article class="duplicate-compare-card duplicate-result-card">
                <header><strong>${this.escapeHtml(title)}</strong><span>最终保留 · ${merged.image_id === 'new' ? '新上传' : `ID ${this.escapeHtml(merged.image_id)}`}</span></header>
                <img src="${this.escapeHtml(merged.thumbnail_url)}" alt="合并后保留图片" loading="lazy">
                ${this.duplicateMetadataRows(merged)}
            </article>
        `;
    }

    resolveDuplicateChoice(result, newPreviewUrl = '') {
        const choose = () => new Promise(resolve => {
            const existing = (result.duplicates || [])[0];
            const incoming = result.incoming || null;
            const items = incoming ? [existing, { ...incoming, image_id: 'new', thumbnail_url: newPreviewUrl }] : (result.duplicates || []).slice(0, 2);
            if (items.length !== 2 || items.some(item => !item)) {
                resolve(null);
                return;
            }
            const cards = items.map((item, index) => {
                const title = (item.character_names || []).join('、') || (index === 0 ? '图片 A' : '图片 B');
                const preview = item.thumbnail_url || newPreviewUrl;
                return `
                    <article class="duplicate-compare-card" data-image-id="${this.escapeHtml(item.image_id)}">
                        <header><strong>${this.escapeHtml(title)}</strong><span>${item.image_id === 'new' ? '新上传' : `ID ${this.escapeHtml(item.image_id)}`}</span></header>
                        <img src="${this.escapeHtml(preview)}" alt="${this.escapeHtml(title)}" loading="lazy">
                        ${this.duplicateMetadataRows(item)}
                    </article>
                `;
            }).join('');
            const mergeFields = [
                ['pid', 'PID'], ['description', '描述'], ['age_rating', '年龄分级'],
                ['groups', '分组标签'], ['characters', '角色标签'], ['feature_tags', '特征标签'],
            ].map(([field, label]) => `
                <label>${label}
                    <select data-merge-field="${field}">
                        <option value="merge">合并两侧</option>
                        <option value="keep">采用保留图</option>
                        <option value="other">采用另一张</option>
                    </select>
                </label>
            `).join('');
            const overlay = document.getElementById('modal-overlay');
            const nested = overlay?.style.display === 'flex' && overlay.getAttribute('aria-hidden') !== 'true';
            ui.showModal('相似图片比对', `
                <div class="duplicate-review duplicate-review-large" role="group" aria-label="相似图片比对">
                    <p>dHash 差异 ${items[1].distance ?? items[0].distance}/64。请判断它们是不同图片、同一图片，或稍后再处理。</p>
                    <div class="duplicate-compare-grid">${cards}</div>
                    <section class="duplicate-merge-panel" hidden>
                        <h4>选择保留文件与信息来源</h4>
                        <div class="duplicate-file-choice">
                            ${items.map((item, index) => `<label><input type="radio" name="duplicate-file-keep" value="${this.escapeHtml(item.image_id)}" ${index === 0 ? 'checked' : ''}> 保留${index === 0 ? '左侧' : '右侧'}文件</label>`).join('')}
                        </div>
                        <div class="duplicate-merge-fields">${mergeFields}</div>
                        <h4 class="duplicate-result-title">修改后保留图片</h4>
                        <div class="duplicate-merge-preview" data-duplicate-merge-preview></div>
                        <p class="duplicate-merge-note duplicate-delete-warning">确认后会永久删除另一份原图及缩略图，无法从系统恢复。</p>
                    </section>
                    <div class="duplicate-decision-actions">
                        <button type="button" class="btn btn-secondary" data-duplicate-action="later">暂不处理</button>
                        <button type="button" class="btn btn-secondary" data-duplicate-action="distinct">保存全部</button>
                        <button type="button" class="btn btn-primary" data-duplicate-action="show-merge">合并检查</button>
                        <button type="button" class="btn btn-primary" data-duplicate-action="confirm-merge" hidden>确认合并</button>
                    </div>
                </div>
            `, nested);
            const layer = document.getElementById('modal-body')?.lastElementChild;
            let settled = false;
            const finish = value => {
                if (settled) return;
                settled = true;
                if (layer) delete layer._onModalClose;
                ui.closeModal();
                resolve(value);
            };
            if (layer) {
                layer._onModalClose = () => {
                    if (settled) return;
                    settled = true;
                    resolve(null);
                };
            }
            layer?.querySelector('[data-duplicate-action="later"]')?.addEventListener('click', () => finish({ action: 'later' }));
            layer?.querySelector('[data-duplicate-action="distinct"]')?.addEventListener('click', () => finish({ action: 'distinct' }));
            layer?.querySelector('[data-duplicate-action="show-merge"]')?.addEventListener('click', event => {
                layer.querySelector('.duplicate-merge-panel').hidden = false;
                event.currentTarget.hidden = true;
                layer.querySelector('[data-duplicate-action="confirm-merge"]').hidden = false;
                this.renderMergedDuplicatePreview(items, layer);
            });
            layer?.querySelectorAll('input[name="duplicate-file-keep"], [data-merge-field]').forEach(control => {
                control.addEventListener('change', () => this.renderMergedDuplicatePreview(items, layer));
            });
            layer?.querySelector('[data-duplicate-action="confirm-merge"]')?.addEventListener('click', () => {
                const keep = layer.querySelector('input[name="duplicate-file-keep"]:checked')?.value;
                const metadataSources = {};
                layer.querySelectorAll('[data-merge-field]').forEach(select => {
                    metadataSources[select.dataset.mergeField] = select.value;
                });
                finish({ action: 'merge', keep, metadataSources });
            });
        });
        const queued = this.duplicateChoiceQueue.then(choose, choose);
        this.duplicateChoiceQueue = queued.catch(() => null);
        return queued;
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
                        age_rating: document.getElementById('single-age-rating')?.value || 'all',
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
                    age_rating: item.ageRating || 'all',
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
        if (ageRatingInput) ageRatingInput.value = 'all';
        
        const descInput = document.getElementById('single-description');
        if (descInput) descInput.value = '';
        
        // 重置文件引用
        this.singleFile = null;
    }

    async loadTempImages() {
        if (this.tempLoadTimer) {
            clearTimeout(this.tempLoadTimer);
        }

        this.tempLoadTimer = setTimeout(async () => {
            try {
                const result = await api.getTempImages();
                if (result && result.images) {
                    this.renderTempImages(result.images);
                    
                    // 更新计数
                    const countEl = document.getElementById('temp-image-count');
                    if (countEl) {
                        countEl.textContent = result.images.length;
                    }
                } else {
                    this.renderTempImages([]);
                }
            } catch (error) {
                console.error('加载temp图片失败:', error);
                ui.showToast('加载temp图片失败: ' + (error.message || '未知错误'), 'error');
            }
        }, 200);
    }

    renderTempImages(images) {
        const grid = document.getElementById('temp-image-grid');
        
        if (!grid) {
            return;
        }
        
        if (images.length === 0) {
            grid.innerHTML = '<div class="empty-state">待处理文件夹里没有图片</div>';
            return;
        }

        // 使用encodeURIComponent处理特殊字符
        const html = images.map(imageName => {
            const encodedName = encodeURIComponent(imageName);
            const escapedName = this.escapeHtml(imageName);
            const escapedEncodedName = this.escapeHtml(encodedName);
            return `
                <div class="temp-image-item" data-image-name="${escapedEncodedName}">
                    <img src="/resource/temp/${escapedEncodedName}" alt="${escapedName}" loading="lazy" decoding="async"
                         style="width: 150px; height: 150px; object-fit: cover; border-radius: 8px;">
                    <div class="temp-image-name">${escapedName}</div>
                    <div class="temp-image-actions">
                        <button type="button" class="btn btn-primary btn-sm temp-image-submit">提交</button>
                        <button type="button" class="btn btn-danger btn-sm temp-image-delete">删除</button>
                    </div>
                </div>
            `;
        }).join('');
        
        grid.innerHTML = html;
        grid.querySelectorAll('.temp-image-item').forEach(item => {
            const encodedName = item.dataset.imageName;
            item.querySelector('.temp-image-submit')?.addEventListener('click', () => this.uploadTempImage(encodedName));
            item.querySelector('.temp-image-delete')?.addEventListener('click', () => this.deleteTempFile(encodedName));
        });
    }

    async showTempDuplicateEditor(result, catalogs) {
        const temp = {
            ...(result.temp || {}),
            image_id: 'temp',
            thumbnail_url: `/resource/temp/${encodeURIComponent(result.filename)}`,
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
        try {
            const imageName = decodeURIComponent(imageNameEncoded);
            const [groups, characters, featureTags] = await Promise.all([
                api.getGroups(),
                api.getCharacters(),
                api.getFeatureTags()
            ]);
            
            if (groups.length === 0 || characters.length === 0) {
                ui.showToast('请先创建分组和角色', 'warning');
                return;
            }
            
            const groupOptions = '';
            const safeImageName = this.escapeHtml(imageName);
            const safeEncodedName = this.escapeHtml(imageNameEncoded);
            
            const content = `
                <form id="temp-upload-form" data-image-name="${safeEncodedName}">
                    <div class="temp-image-preview">
                        <img src="/resource/temp/${safeEncodedName}" alt="${safeImageName}"
                             style="max-width: 100%; max-height: 400px; border-radius: 8px; margin-bottom: 16px;">
                    </div>
                    <div class="form-group">
                        <label for="temp-group-select">分组</label>
                        <select id="temp-group-select" class="form-select" required>
                            <option value="">先选分组</option>
                            ${groupOptions}
                        </select>
                        <button type="button" class="btn-link" onclick="showCreateGroupModal(true)">添加分组</button>
                    </div>
                    <div class="form-group">
                        <label>角色</label>
                        <div id="temp-character-selector"></div>
                        <button type="button" class="btn-link" onclick="showCreateCharacterModal(true)">添加角色</button>
                    </div>
                    <div class="form-group">
                        <label for="temp-pid">PID（可不填）</label>
                        <input type="text" id="temp-pid" class="form-input" placeholder="输入 PID">
                    </div>
                    <div class="form-group">
                        <label for="temp-age-rating">年龄分级</label>
                        <select id="temp-age-rating" class="form-select">
                            <option value="all" selected>全年龄</option>
                            <option value="r12">R12</option>
                            <option value="r16">R16</option>
                            <option value="r18">R18</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="temp-description">备注（可不填）</label>
                        <textarea id="temp-description" class="form-textarea" placeholder="写点备注"></textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="button" class="btn btn-danger" id="temp-upload-delete">删除</button>
                        <button type="submit" class="btn btn-primary">提交</button>
                    </div>
                </form>
            `;
            
            ui.showModal(`提交图片: ${imageName}`, content);

            const tempForm = document.getElementById('temp-upload-form');
            if (tempForm) {
                tempForm.onsubmit = (e) => {
                    e.preventDefault();
                    const encoded = tempForm.dataset.imageName || imageNameEncoded;
                    this.submitTempUpload(encoded);
                };
            }
            document.getElementById('temp-upload-delete')?.addEventListener('click', () => {
                const encoded = tempForm?.dataset.imageName || imageNameEncoded;
                this.deleteTempImageFromModal(encoded);
            });
            
            // 初始化temp角色选择器
            const tempCharacterSelector = null;
            
            // 监听分组变化
            const groupSelect = document.getElementById('temp-group-select');
            
            if (groupSelect) {
                groupSelect.required = false;
                groupSelect.closest('.form-group').style.display = 'none';
            }
            const oldCharacterContainer = document.getElementById('temp-character-selector');
            if (oldCharacterContainer) {
                oldCharacterContainer.closest('.form-group').style.display = 'none';
            }
            const previewBlock = document.querySelector('#temp-upload-form .temp-image-preview');
            if (previewBlock) {
                previewBlock.insertAdjacentHTML('afterend', `
                    <div class="form-group">
                        <label>标签</label>
                        <div id="temp-tag-selector"></div>
                        <button type="button" class="btn-link" onclick="showCreateGroupModal(true)">添加分组</button>
                        <button type="button" class="btn-link" onclick="showCreateCharacterModal(true)">添加角色</button>
                        <button type="button" class="btn-link" onclick="ui.showCreateFeatureTagModal(true)">添加特征</button>
                    </div>
                `);
            }
            const tempTagSelector = new ImageTagSelector('temp-tag-selector', { title: '添加temp图片标签' });
            window.imageTagSelectors['temp-tag-selector'] = tempTagSelector;
            tempTagSelector.setData({ groups, characters, featureTags });
            
        } catch (error) {
            ui.showToast(`加载表单失败: ${error.message}`, 'error');
        }
    }
    
    async submitTempUpload(imageNameEncoded) {
        try {
            const encodedName = imageNameEncoded || document.getElementById('temp-upload-form')?.dataset?.imageName;
            const imageName = decodeURIComponent(encodedName || '');
            const selectedTags = window.imageTagSelectors['temp-tag-selector']
                ? window.imageTagSelectors['temp-tag-selector'].getValue()
                : { group_ids: [], character_ids: [], feature_tag_ids: [] };
            const selectedCharacters = selectedTags.character_ids || [];
            
            if (selectedCharacters.length === 0) {
                ui.showToast('请选择至少一个角色', 'error');
                return;
            }
            if ((selectedTags.group_ids || []).length === 0) {
                ui.showToast('请至少添加一个分组标签', 'error');
                return;
            }
            
            const data = {
                filename: imageName,
                character_ids: selectedCharacters,
                group_ids: selectedTags.group_ids || [],
                feature_tag_ids: selectedTags.feature_tag_ids || [],
                age_rating: document.getElementById('temp-age-rating')?.value || 'all',
                pid: document.getElementById('temp-pid').value || null,
                description: document.getElementById('temp-description').value || null
            };
            
            ui.showToast('正在提交图片...', 'info');
            
            let result = await api.uploadTempImage(data);
            if (result?.status === 'duplicate') {
                const decision = await this.resolveDuplicateChoice(
                    result,
                    `/resource/temp/${encodeURIComponent(imageName)}`
                );
                if (!decision) {
                    await api.resolveDuplicateImage(result.duplicate_token, 'cancel');
                    ui.showToast('已取消提交', 'info');
                    return;
                }
                const request = this.duplicateDecisionRequest(decision);
                result = await api.resolveDuplicateImage(
                    result.duplicate_token,
                    request.keep,
                    request.metadataSources,
                );
            }
            ui.showToast(result.message, 'success');
            
            ui.closeModal();
            
            // 刷新temp图片列表
            await this.loadTempImages();
            await ui.updateTempCount();
            
            // 刷新系统状态
            ui.loadSystemStatus();
            
        } catch (error) {
            ui.showToast(`上传失败: ${error.message}`, 'error');
        }
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
        if (!confirm(`确定要删除 ${imageName} 吗？`)) {
            return;
        }
        
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
