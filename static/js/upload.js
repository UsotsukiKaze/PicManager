// 上传管理类
class UploadManager {
    constructor() {
        this.initializeEventListeners();
        this.batchFiles = [];
        this.singleFile = null;
        this.singleCharacterSelector = null;
        this.tempLoadTimer = null;
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
        if (!this.singleCharacterSelector) {
            this.singleCharacterSelector = new CharacterSelector('single-character-selector');
            window.characterSelectors['single-character-selector'] = this.singleCharacterSelector;
        }
    }

    showSinglePreview(file) {
        const preview = document.getElementById('single-preview');
        const img = document.getElementById('single-preview-img');
        const filename = document.getElementById('single-filename');
        const placeholder = document.querySelector('#single-upload-area .upload-placeholder');

        const reader = new FileReader();
        reader.onload = (e) => {
            img.src = e.target.result;
            filename.textContent = `文件名: ${file.name}`;
            placeholder.style.display = 'none';
            preview.style.display = 'flex';
        };
        reader.readAsDataURL(file);
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

        this.batchFiles = validFiles;
        this.renderBatchList();
    }

    renderBatchList() {
        const container = document.getElementById('batch-upload-list');
        
        container.innerHTML = `
            <div class="batch-header">
                <p>已选择 ${this.batchFiles.length} 张图片</p>
                <button type="button" class="btn btn-primary btn-sm" onclick="upload.processBatchUpload()">开始批量上传</button>
            </div>
            <div class="batch-items">
                ${this.batchFiles.map((file, index) => `
                    <div class="batch-item" data-index="${index}">
                        <div class="batch-preview">
                            <img id="batch-preview-${index}" style="width: 120px; height: 120px; object-fit: cover; border-radius: 8px;">
                        </div>
                        <div class="batch-info">
                            <div class="batch-filename">(${(file.size / 1024 / 1024).toFixed(2)} MB) ${file.name}</div>
                            <div class="batch-form">
                                <div class="batch-form-group">
                                    <label class="batch-label">分组</label>
                                    <select class="batch-group form-select" required>
                                        <option value="">选择分组</option>
                                    </select>
                                </div>
                                <div class="batch-form-group">
                                    <label class="batch-label">角色</label>
                                    <div class="batch-character-selector" id="batch-character-selector-${index}"></div>
                                </div>
                                <div class="batch-form-group">
                                    <label class="batch-label">PID</label>
                                    <input type="text" class="batch-pid form-input" placeholder="可选">
                                </div>
                                <div class="batch-form-group">
                                    <label class="batch-label">描述</label>
                                    <input type="text" class="batch-description form-input" placeholder="可选">
                                </div>
                            </div>
                        </div>
                        <div class="batch-actions">
                            <button class="btn btn-danger btn-sm" onclick="upload.removeBatchItem(${index})">删除</button>
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        // 加载预览图
        this.batchFiles.forEach((file, index) => {
            const reader = new FileReader();
            reader.onload = (e) => {
                document.getElementById(`batch-preview-${index}`).src = e.target.result;
            };
            reader.readAsDataURL(file);
        });

        // 初始化批量表单
        this.initializeBatchForms();
    }

    async initializeBatchForms() {
        try {
            const groups = await api.getGroups();
            
            document.querySelectorAll('.batch-group').forEach((select, itemIndex) => {
                select.innerHTML = '<option value="">选择分组</option>';
                groups.forEach(group => {
                    select.innerHTML += `<option value="${group.id}">${group.name}</option>`;
                });

                // 初始化角色选择器
                const characterSelectorId = `batch-character-selector-${itemIndex}`;
                let characterSelector = window.characterSelectors ? window.characterSelectors[characterSelectorId] : null;
                
                if (!characterSelector) {
                    characterSelector = new CharacterSelector(characterSelectorId);
                    if (!window.characterSelectors) {
                        window.characterSelectors = {};
                    }
                    window.characterSelectors[characterSelectorId] = characterSelector;
                }

                // 监听分组变化
                select.addEventListener('change', async () => {
                    const groupId = select.value;
                    
                    if (groupId) {
                        const characters = await api.getCharacters(parseInt(groupId));
                        characterSelector.setCharacters(characters);
                    } else {
                        characterSelector.setCharacters([]);
                    }
                });
            });
        } catch (error) {
            ui.showToast('加载分组信息失败', 'error');
        }
    }

    removeBatchItem(index) {
        this.batchFiles.splice(index, 1);
        if (this.batchFiles.length > 0) {
            this.renderBatchList();
        } else {
            document.getElementById('batch-upload-list').innerHTML = '';
        }
    }

    isValidImageFile(file) {
        const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif', 'image/bmp'];
        return validTypes.includes(file.type);
    }

    async uploadSingleImage() {
        try {
            const fileInput = document.getElementById('single-file-input');
            const file = fileInput.files[0];
            
            if (!file) {
                ui.showToast('请选择图片文件', 'error');
                return;
            }

            const selectedCharacters = this.singleCharacterSelector ? this.singleCharacterSelector.getSelectedIds() : [];
            
            if (selectedCharacters.length === 0) {
                ui.showToast('请选择至少一个角色', 'error');
                return;
            }

            const groupId = document.getElementById('single-group-select').value;
            if (!groupId) {
                ui.showToast('请选择分组', 'error');
                return;
            }

            const metadata = {
                character_ids: selectedCharacters,
                group_id: parseInt(groupId),
                pid: document.getElementById('single-pid').value || null,
                description: document.getElementById('single-description').value || null
            };

            ui.showToast('正在上传图片...', 'info');
            
            const result = await api.uploadSingleImage(file, metadata);
            ui.showToast(result.message, 'success');
            
            this.clearSingleUpload();
            
            // 切换到图片管理页面并刷新
            ui.switchPage('management');
            ui.loadImages();
            ui.loadSystemStatus();
            
        } catch (error) {
            ui.showToast(`上传失败: ${error.message}`, 'error');
        }
    }

    async processBatchUpload() {
        const batchItems = document.querySelectorAll('.batch-item');
        let successCount = 0;
        let failedCount = 0;

        for (let i = 0; i < batchItems.length; i++) {
            const item = batchItems[i];
            const file = this.batchFiles[i];
            
            try {
                const groupSelect = item.querySelector('.batch-group');
                const characterSelectorId = `batch-character-selector-${i}`;
                const characterSelector = window.characterSelectors[characterSelectorId];
                const selectedCharacters = characterSelector ? characterSelector.getSelectedIds() : [];
                
                if (selectedCharacters.length === 0) {
                    ui.showToast(`第 ${i + 1} 张图片未选择角色，跳过`, 'warning');
                    failedCount++;
                    continue;
                }
                if (!groupSelect.value) {
                    ui.showToast(`第 ${i + 1} 张图片未选择分组，跳过`, 'warning');
                    failedCount++;
                    continue;
                }

                const metadata = {
                    character_ids: selectedCharacters,
                    group_id: parseInt(groupSelect.value),
                    pid: item.querySelector('.batch-pid').value || null,
                    description: item.querySelector('.batch-description').value || null
                };

                await api.uploadSingleImage(file, metadata);
                successCount++;
                
                ui.showToast(`已上传 ${successCount} / ${this.batchFiles.length} 张图片`, 'info');
                
            } catch (error) {
                console.error(`上传第 ${i + 1} 张图片失败:`, error);
                failedCount++;
            }
        }

        ui.showToast(`批量上传完成! 成功: ${successCount}, 失败: ${failedCount}`, 'success');
        
        // 清空批量上传列表
        this.batchFiles = [];
        document.getElementById('batch-upload-list').innerHTML = '';
        document.getElementById('batch-file-input').value = '';
        
        // 刷新数据
        ui.loadImages();
        ui.loadSystemStatus();
    }

    clearSingleUpload() {
        // 清空文件输入
        const fileInput = document.getElementById('single-file-input');
        if (fileInput) fileInput.value = '';
        
        // 隐藏预览
        const preview = document.getElementById('single-preview');
        if (preview) preview.style.display = 'none';
        
        const placeholder = document.querySelector('#single-upload-area .upload-placeholder');
        if (placeholder) placeholder.style.display = 'flex';
        
        // 隐藏表单
        const form = document.getElementById('single-upload-form');
        if (form) form.style.display = 'none';
        
        // 清空表单内容
        const groupSelect = document.getElementById('single-group-select');
        if (groupSelect) groupSelect.value = '';
        
        // 清空角色选择器（使用正确的容器 ID）
        if (this.singleCharacterSelector) {
            this.singleCharacterSelector.clear();
        }
        
        const pidInput = document.getElementById('single-pid');
        if (pidInput) pidInput.value = '';
        
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
            grid.innerHTML = '<div class="empty-state">temp目录中没有图片</div>';
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
                        <button class="btn btn-primary btn-sm" onclick="upload.uploadTempImage('${encodedName}')">上传</button>
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
            // 加载分组和角色数据
            const groups = await api.getGroups();
            
            if (groups.length === 0) {
                ui.showToast('请先创建分组和角色', 'warning');
                return;
            }
            
            const groupOptions = groups.map(group => 
                `<option value="${group.id}">${group.name}</option>`
            ).join('');
            
            const content = `
                <form id="temp-upload-form" data-image-name="${imageNameEncoded}" onsubmit="event.preventDefault(); upload.submitTempUpload('${imageNameEncoded}')">
                    <div class="temp-image-preview">
                        <img src="/resource/temp/${imageNameEncoded}" alt="${imageName}" 
                             style="max-width: 100%; max-height: 400px; border-radius: 8px; margin-bottom: 16px;">
                    </div>
                    <div class="form-group">
                        <label for="temp-group-select">选择分组</label>
                        <select id="temp-group-select" class="form-select" required>
                            <option value="">请选择分组</option>
                            ${groupOptions}
                        </select>
                        <button type="button" class="btn-link" onclick="showCreateGroupModal(true)">新建分组</button>
                    </div>
                    <div class="form-group">
                        <label>选择角色</label>
                        <div id="temp-character-selector"></div>
                        <button type="button" class="btn-link" onclick="showCreateCharacterModal(true)">新建角色</button>
                    </div>
                    <div class="form-group">
                        <label for="temp-pid">PID (可选)</label>
                        <input type="text" id="temp-pid" class="form-input" placeholder="输入PID">
                    </div>
                    <div class="form-group">
                        <label for="temp-description">描述 (可选)</label>
                        <textarea id="temp-description" class="form-textarea" placeholder="输入图片描述"></textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="button" class="btn btn-danger" onclick="upload.deleteTempImageFromModal('${imageNameEncoded}')">删除</button>
                        <button type="submit" class="btn btn-primary">上传图片</button>
                    </div>
                </form>
            `;
            
            ui.showModal(`上传图片: ${imageName}`, content);

            const tempForm = document.getElementById('temp-upload-form');
            if (tempForm) {
                tempForm.onsubmit = (e) => {
                    e.preventDefault();
                    const encoded = tempForm.dataset.imageName || imageNameEncoded;
                    this.submitTempUpload(encoded);
                };
            }
            
            // 初始化temp角色选择器
            const tempCharacterSelector = new CharacterSelector('temp-character-selector');
            window.characterSelectors['temp-character-selector'] = tempCharacterSelector;
            
            // 监听分组变化
            const groupSelect = document.getElementById('temp-group-select');
            
            groupSelect.addEventListener('change', async () => {
                const groupId = groupSelect.value;
                if (groupId) {
                    const characters = await api.getCharacters(parseInt(groupId));
                    tempCharacterSelector.setCharacters(characters);
                } else {
                    tempCharacterSelector.setCharacters([]);
                }
            });
            
        } catch (error) {
            ui.showToast(`加载表单失败: ${error.message}`, 'error');
        }
    }
    
    async submitTempUpload(imageNameEncoded) {
        try {
            const encodedName = imageNameEncoded || document.getElementById('temp-upload-form')?.dataset?.imageName;
            const imageName = decodeURIComponent(encodedName || '');
            const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
            const selectedCharacters = tempCharacterSelector ? tempCharacterSelector.getSelectedIds() : [];
            
            if (selectedCharacters.length === 0) {
                ui.showToast('请选择至少一个角色', 'error');
                return;
            }
            
            const data = {
                filename: imageName,
                character_ids: selectedCharacters,
                pid: document.getElementById('temp-pid').value || null,
                description: document.getElementById('temp-description').value || null
            };
            
            ui.showToast('正在上传图片...', 'info');
            
            const result = await api.uploadTempImage(data);
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