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

    resolveDuplicateChoice(result, newPreviewUrl = '') {
        const choose = () => new Promise(resolve => {
            const matches = result.duplicates || [];
            const cards = matches.map(match => `
                <label class="duplicate-choice-card">
                    <input type="radio" name="duplicate-keep" value="existing:${this.escapeHtml(match.image_id)}">
                    <img src="${this.escapeHtml(match.thumbnail_url)}" alt="现有图片 ${this.escapeHtml(match.image_id)}" loading="lazy">
                    <span>
                        <strong>保留现有图片</strong>
                        <small>ID ${this.escapeHtml(match.image_id)} · 差异 ${match.distance}/64</small>
                        <small>${this.escapeHtml((match.character_names || []).join('、') || '未标注角色')}</small>
                    </span>
                </label>
            `).join('');
            const newPreview = newPreviewUrl ? `
                <label class="duplicate-choice-card duplicate-choice-new">
                    <input type="radio" name="duplicate-keep" value="new">
                    <img src="${this.escapeHtml(newPreviewUrl)}" alt="本次上传的新图片">
                    <span><strong>保留新图片</strong><small>重复的现有图片将归档，但不会物理删除原文件</small></span>
                </label>
            ` : '';
            const overlay = document.getElementById('modal-overlay');
            const nested = overlay?.style.display === 'flex' && overlay.getAttribute('aria-hidden') !== 'true';
            ui.showModal('发现可能重复的图片', `
                <div class="duplicate-review" role="group" aria-label="选择要保留的图片">
                    <p>dHash 检测到 ${matches.length} 张相似图片。请选择保留哪一张。</p>
                    <div class="duplicate-choice-list">${cards}${newPreview}</div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" id="duplicate-cancel">取消</button>
                        <button type="button" class="btn btn-primary" id="duplicate-confirm" disabled>确认选择</button>
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
            layer?.querySelectorAll('input[name="duplicate-keep"]').forEach(input => {
                input.addEventListener('change', () => {
                    const confirmButton = layer.querySelector('#duplicate-confirm');
                    if (confirmButton) confirmButton.disabled = false;
                });
            });
            layer?.querySelector('#duplicate-cancel')?.addEventListener('click', () => finish(null));
            layer?.querySelector('#duplicate-confirm')?.addEventListener('click', () => {
                finish(layer.querySelector('input[name="duplicate-keep"]:checked')?.value || null);
            });
        });
        const queued = this.duplicateChoiceQueue.then(choose, choose);
        this.duplicateChoiceQueue = queued.catch(() => null);
        return queued;
    }

    async uploadWithDuplicateChoice(file, metadata, onProgress, previewUrl = '') {
        const firstResult = await api.uploadSingleImage(file, metadata, onProgress);
        if (firstResult?.status !== 'duplicate') return firstResult;
        const duplicateKeep = await this.resolveDuplicateChoice(firstResult, previewUrl);
        if (!duplicateKeep) {
            await api.resolveDuplicateImage(firstResult.duplicate_token, 'cancel');
            return { status: 'cancelled', message: '已取消提交' };
        }
        return api.resolveDuplicateImage(firstResult.duplicate_token, duplicateKeep);
    }

    async uploadSingleImage() {
        if (this.singleSubmitting) return;
        try {
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

            const metadata = {
                character_ids: selectedCharacters,
                group_ids: selectedTags.group_ids || [],
                feature_tag_ids: selectedTags.feature_tag_ids || [],
                age_rating: document.getElementById('single-age-rating')?.value || 'all',
                pid: document.getElementById('single-pid').value || null,
                description: document.getElementById('single-description').value || null
            };

            this.singleSubmitting = true;
            const submitButton = document.getElementById('single-upload-submit');
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.textContent = '正在提交…';
            }
            ui.showToast('正在上传图片...', 'info');
            
            const result = await this.uploadWithDuplicateChoice(file, metadata, (progress) => {
                ui.showToast(`正在上传图片... ${progress}%`, 'info');
            }, this.singlePreviewUrl || '');
            if (result.status === 'cancelled') {
                ui.showToast(result.message, 'info');
                return;
            }
            ui.showToast(result.message, result.status === 'kept_existing' ? 'info' : 'success');
            
            this.clearSingleUpload();
            
            // 切换到图片管理页面并刷新
            ui.switchPage('management');
            ui.loadImages(null);
            ui.loadSystemStatus();
            
        } catch (error) {
            ui.showToast(`上传失败: ${error.message}`, 'error');
        } finally {
            this.singleSubmitting = false;
            const submitButton = document.getElementById('single-upload-submit');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = '提交图片';
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
            try {
                const selectedTags = item.tags || { group_ids: [], character_ids: [], feature_tag_ids: [] };
                const selectedCharacters = selectedTags.character_ids || [];

                if (selectedCharacters.length === 0) {
                    item.status = 'failed';
                    item.message = '请至少选择一个角色';
                    failedCount++;
                    this.updateBatchItemStatus(item);
                    return;
                }
                if ((selectedTags.group_ids || []).length === 0) {
                    item.status = 'failed';
                    item.message = '请至少添加一个分组标签';
                    failedCount++;
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
                this.updateBatchItemStatus(item);
                const result = await this.uploadWithDuplicateChoice(item.file, metadata, (progress) => {
                    item.progress = progress;
                    this.updateBatchItemStatus(item);
                }, item.previewUrl || '');
                if (result.status === 'cancelled') {
                    item.status = 'ready';
                    item.message = result.message;
                    this.updateBatchItemStatus(item);
                    return;
                }
                const message = result && result.message ? result.message : '上传成功';
                const isPending = message.includes('审核');
                item.status = isPending ? 'pending-review' : 'success';
                item.progress = 100;
                item.message = message;
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
            const escapedName = imageName.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            return `
                <div class="temp-image-item">
                    <img src="/resource/temp/${encodedName}" alt="${escapedName}" loading="lazy" decoding="async"
                         style="width: 150px; height: 150px; object-fit: cover; border-radius: 8px;">
                    <div class="temp-image-name">${imageName}</div>
                    <div class="temp-image-actions">
                        <button class="btn btn-primary btn-sm" onclick="upload.uploadTempImage('${encodedName}')">提交</button>
                        <button class="btn btn-danger btn-sm" onclick="upload.deleteTempFile('${encodedName}')">删除</button>
                    </div>
                </div>
            `;
        }).join('');
        
        grid.innerHTML = html;
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
            
            const content = `
                <form id="temp-upload-form" data-image-name="${imageNameEncoded}" onsubmit="event.preventDefault(); upload.submitTempUpload('${imageNameEncoded}')">
                    <div class="temp-image-preview">
                        <img src="/resource/temp/${imageNameEncoded}" alt="${imageName}" 
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
                        <button type="button" class="btn btn-danger" onclick="upload.deleteTempImageFromModal('${imageNameEncoded}')">删除</button>
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
                const choice = await this.resolveDuplicateChoice(
                    result,
                    `/resource/temp/${encodeURIComponent(imageName)}`
                );
                if (!choice) {
                    await api.resolveDuplicateImage(result.duplicate_token, 'cancel');
                    ui.showToast('已取消提交', 'info');
                    return;
                }
                result = await api.resolveDuplicateImage(result.duplicate_token, choice);
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

// 创建全局上传管理实例
window.upload = new UploadManager();
