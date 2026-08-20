class EmojiLibrary {
    constructor() {
        this.groups = [];
        this.characters = [];
        this.emojiCharacters = [];
        this.emotions = [];
        this.initialized = false;
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null };
        this.uploadPickerDraft = null;
        this.uploadFile = null;
        this.uploadPreviewUrl = null;
        this.pagination = { currentPage: 1, totalPages: 1, limit: 20, total: 0 };
    }

    escape(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[char]));
    }

    async init() {
        await this.loadOptions();
        await this.load();
        this.initialized = true;
    }

    optionHtml(items, placeholder) {
        return `<option value="">${placeholder}</option>` + items.map(item => (
            `<option value="${item.id}">${this.escape(item.name)}</option>`
        )).join('');
    }

    async fetchEmojiCharacterFacets() {
        try {
            return await api.getEmojiCharacters() || [];
        } catch (error) {
            console.warn('Emoji character facets are temporarily unavailable:', error);
            return [];
        }
    }

    async loadOptions() {
        const selectedFilters = {
            group: document.getElementById('emoji-group-filter')?.value || '',
            character: document.getElementById('emoji-character-filter')?.value || '',
            emotion: document.getElementById('emoji-emotion-filter')?.value || '',
        };
        const [groups, characters, emotions, emojiCharacters] = await Promise.all([
            api.getGroups(),
            api.getCharacters(),
            api.getEmotionTags(),
            this.fetchEmojiCharacterFacets(),
        ]);
        this.groups = groups || [];
        this.characters = characters || [];
        this.emotions = emotions || [];
        this.emojiCharacters = emojiCharacters || [];

        const groupFilter = document.getElementById('emoji-group-filter');
        const characterFilter = document.getElementById('emoji-character-filter');
        const emotionFilter = document.getElementById('emoji-emotion-filter');
        if (groupFilter) groupFilter.innerHTML = this.optionHtml(this.groups, '全部分组');
        if (characterFilter) characterFilter.innerHTML = this.optionHtml(this.characters, '全部角色');
        if (emotionFilter) emotionFilter.innerHTML = this.optionHtml(this.emotions, '全部情绪');
        if (groupFilter) groupFilter.value = selectedFilters.group;
        if (characterFilter) characterFilter.value = selectedFilters.character;
        if (emotionFilter) emotionFilter.value = selectedFilters.emotion;
        window.queryPanels?.update('emoji-query-panel');
        this.renderCharacterTabs();

        this.renderUploadTagControls();
    }

    renderCharacterTabs() {
        const tabs = document.getElementById('emoji-character-tabs');
        if (!tabs) return;
        const selected = document.getElementById('emoji-character-filter')?.value || '';
        const button = (id, name, count = null) => {
            const value = String(id || '');
            const active = value === String(selected);
            const countTitle = count === null ? '' : `，${count} 个表情包`;
            return `
                <button type="button" class="age-filter-tab ${active ? 'active' : ''}"
                        role="tab" aria-selected="${active}" title="${this.escape(name)}${countTitle}"
                        onclick="emojiLibrary.selectCharacter('${this.escape(value)}')">${this.escape(name)}</button>
            `;
        };
        tabs.innerHTML = button('', '全部') + this.emojiCharacters.map(character => (
            button(character.id, character.name, character.emoji_count)
        )).join('');
    }

    selectCharacter(characterId) {
        const filter = document.getElementById('emoji-character-filter');
        if (filter) filter.value = String(characterId || '');
        this.renderCharacterTabs();
        window.queryPanels?.update('emoji-query-panel');
        this.pagination.currentPage = 1;
        return this.load();
    }

    async refreshCharacterFacets() {
        this.emojiCharacters = await this.fetchEmojiCharacterFacets();
        const filter = document.getElementById('emoji-character-filter');
        if (filter?.value && !this.emojiCharacters.some(item => String(item.id) === String(filter.value))) {
            filter.value = '';
        }
        this.renderCharacterTabs();
    }

    getById(items, id) {
        return items.find(item => Number(item.id) === Number(id)) || null;
    }

    tagButton(type, id) {
        if (!id) return '';
        const typeMap = {
            group: { key: 'group_id', label: '分组', source: this.groups },
            character: { key: 'character_id', label: '角色', source: this.characters },
            emotion: { key: 'emotion_id', label: '情绪', source: this.emotions },
        };
        const config = typeMap[type];
        const item = this.getById(config.source, id);
        if (!item) return '';
        return `
            <button type="button" class="pm-tag pm-tag-${type}" onclick="emojiLibrary.clearUploadTag('${config.key}')">
                <span>${this.escape(item.name)}</span>
                <small>${config.label}</small>
                <b aria-hidden="true">x</b>
            </button>
        `;
    }

    renderUploadTagControls() {
        const uploadBox = document.getElementById('emoji-upload-tag-selector');
        if (!uploadBox) return;
        uploadBox.innerHTML = `
            <label>标签</label>
            <div class="pm-tag-box">
                ${this.tagButton('group', this.uploadTags.group_id)}
                ${this.tagButton('character', this.uploadTags.character_id)}
                ${this.tagButton('emotion', this.uploadTags.emotion_id)}
                <button type="button" class="pm-tag-add" onclick="emojiLibrary.openUploadTagPicker()">+</button>
            </div>
        `;
    }

    clearUploadTag(key) {
        this.uploadTags[key] = null;
        if (key === 'group_id') {
            const character = this.getById(this.characters, this.uploadTags.character_id);
            if (character && character.group_id) {
                this.uploadTags.group_id = character.group_id;
            }
        }
        this.renderUploadTagControls();
    }

    filterItems(items, query) {
        if (!query) return items;
        const q = query.toLowerCase();
        return items.filter(item => {
            const aliases = Array.isArray(item.aliases) ? item.aliases : [];
            const nicknames = Array.isArray(item.nicknames) ? item.nicknames : [];
            return String(item.name).toLowerCase().includes(q)
                || aliases.some(alias => String(alias).toLowerCase().includes(q))
                || nicknames.some(alias => String(alias).toLowerCase().includes(q));
        });
    }

    pickerOption(item, type, selected) {
        const labelMap = { group: '分组', character: '角色', emotion: '情绪' };
        return `
            <label class="tag-picker-option ${selected ? 'selected' : ''}">
                <input type="radio" name="emoji-picker-${type}" value="${item.id}" ${selected ? 'checked' : ''}>
                <span>${this.escape(item.name)}</span>
                <small>${labelMap[type]}</small>
            </label>
        `;
    }

    openUploadTagPicker() {
        const modalId = 'emoji-upload-tag-picker';
        this.uploadPickerDraft = { ...this.uploadTags };
        const content = `
            <div class="tag-picker" id="${modalId}">
                <input class="form-input tag-picker-search" placeholder="搜索分组、角色或情绪" autocomplete="off">
                <div class="tag-picker-columns tag-picker-columns-3">
                    <section>
                        <h4>分组</h4>
                        <div class="tag-picker-list" data-type="group"></div>
                    </section>
                    <section>
                        <h4>角色</h4>
                        <div class="tag-picker-list" data-type="character"></div>
                    </section>
                    <section>
                        <h4>情绪</h4>
                        <div class="tag-picker-list" data-type="emotion"></div>
                    </section>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="button" class="btn btn-primary" onclick="emojiLibrary.confirmUploadTagPicker('${modalId}')">添加</button>
                </div>
            </div>
        `;
        ui.showModal('添加表情包标签', content, true);
        this.renderUploadTagPicker(modalId);
        const search = document.querySelector(`#${modalId} .tag-picker-search`);
        search.addEventListener('input', () => this.renderUploadTagPicker(modalId, search.value));
        const root = document.getElementById(modalId);
        root.addEventListener('change', event => {
            const input = event.target;
            if (!input || input.tagName !== 'INPUT') return;
            const value = Number(input.value) || null;
            if (input.name === 'emoji-picker-group') {
                this.uploadPickerDraft.group_id = value;
                const currentCharacter = this.getById(this.characters, this.uploadPickerDraft.character_id);
                if (currentCharacter && Number(currentCharacter.group_id) !== Number(value)) {
                    this.uploadPickerDraft.character_id = null;
                }
                this.renderUploadTagPicker(modalId, search.value);
            } else if (input.name === 'emoji-picker-character') {
                this.uploadPickerDraft.character_id = value;
                const character = this.getById(this.characters, value);
                if (character?.group_id) this.uploadPickerDraft.group_id = character.group_id;
                this.renderUploadTagPicker(modalId, search.value);
            } else if (input.name === 'emoji-picker-emotion') {
                this.uploadPickerDraft.emotion_id = value;
            }
        });
    }

    renderUploadTagPicker(modalId, query = '') {
        const root = document.getElementById(modalId);
        if (!root) return;
        const draft = this.uploadPickerDraft || this.uploadTags;
        const selectedGroupId = draft.group_id;
        const groups = this.filterItems(this.groups, query);
        const charactersSource = selectedGroupId
            ? this.characters.filter(character => Number(character.group_id) === Number(selectedGroupId))
            : this.characters;
        const characters = this.filterItems(charactersSource, query);
        const emotions = this.filterItems(this.emotions, query);

        root.querySelector('[data-type="group"]').innerHTML = groups.map(group =>
            this.pickerOption(group, 'group', Number(group.id) === Number(draft.group_id))
        ).join('') || '<div class="empty-state">没有分组</div>';
        root.querySelector('[data-type="character"]').innerHTML = characters.map(character =>
            this.pickerOption(character, 'character', Number(character.id) === Number(draft.character_id))
        ).join('') || '<div class="empty-state">没有角色</div>';
        root.querySelector('[data-type="emotion"]').innerHTML = emotions.map(emotion =>
            this.pickerOption(emotion, 'emotion', Number(emotion.id) === Number(draft.emotion_id))
        ).join('') || '<div class="empty-state">没有情绪</div>';
    }

    confirmUploadTagPicker(modalId) {
        const draft = this.uploadPickerDraft || this.uploadTags;
        const character = this.getById(this.characters, draft.character_id);
        this.uploadTags = {
            group_id: character?.group_id || draft.group_id || null,
            character_id: draft.character_id || null,
            emotion_id: draft.emotion_id || null,
        };
        this.uploadPickerDraft = null;

        ui.closeModal();
        this.renderUploadTagControls();
    }

    async load() {
        if (!this.groups.length && !this.initialized) {
            await this.loadOptions();
        }
        const params = {
            group_id: document.getElementById('emoji-group-filter')?.value || '',
            character_id: document.getElementById('emoji-character-filter')?.value || '',
            emotion_id: document.getElementById('emoji-emotion-filter')?.value || '',
            limit: this.pagination.limit,
            offset: (this.pagination.currentPage - 1) * this.pagination.limit,
        };
        const result = await api.searchEmojis(params);
        const total = result.total || 0;
        const totalPages = Math.max(1, Math.ceil(total / this.pagination.limit));
        if (!(result.emojis || []).length && total > 0 && this.pagination.currentPage > totalPages) {
            this.pagination.currentPage = totalPages;
            return this.load();
        }
        this.pagination.total = total;
        this.pagination.totalPages = totalPages;
        this.renderGrid(result.emojis || []);
        this.renderPagination();
        this.renderEmotions();
    }

    applyFilters() {
        this.pagination.currentPage = 1;
        this.renderCharacterTabs();
        return this.load();
    }

    changePage(page) {
        const nextPage = Number(page);
        if (!Number.isInteger(nextPage) || nextPage < 1 || nextPage > this.pagination.totalPages) return;
        this.pagination.currentPage = nextPage;
        this.load();
        document.getElementById('emoji-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    renderPagination() {
        const container = document.getElementById('emoji-pagination');
        if (!container) return;
        const { currentPage, totalPages, total } = this.pagination;
        if (totalPages <= 1) {
            container.innerHTML = total ? `<span class="pagination-summary">共 ${total} 个 · 20/页</span>` : '';
            return;
        }

        const pages = window.ui?.buildPageWindow
            ? ui.buildPageWindow(totalPages, currentPage)
            : Array.from({ length: totalPages }, (_, index) => index + 1);
        let pageButtons = '';
        pages.forEach(item => {
            if (typeof item !== 'number') {
                pageButtons += '<span class="pagination-ellipsis">...</span>';
                return;
            }
            pageButtons += `<button class="pagination-btn ${item === currentPage ? 'active' : ''}" onclick="emojiLibrary.changePage(${item})">${item}</button>`;
        });
        container.innerHTML = `
            <button class="pagination-btn pagination-edge" ${currentPage === 1 ? 'disabled' : ''} onclick="emojiLibrary.changePage(1)">首页</button>
            <button class="pagination-btn" ${currentPage === 1 ? 'disabled' : ''} onclick="emojiLibrary.changePage(${currentPage - 1})">上一页</button>
            ${pageButtons}
            <button class="pagination-btn" ${currentPage === totalPages ? 'disabled' : ''} onclick="emojiLibrary.changePage(${currentPage + 1})">下一页</button>
            <button class="pagination-btn pagination-edge" ${currentPage === totalPages ? 'disabled' : ''} onclick="emojiLibrary.changePage(${totalPages})">末页</button>
            <span class="pagination-summary">${currentPage} / ${totalPages} · 共 ${total} 个 · 20/页</span>
        `;
    }

    formatEmojiTags(emoji) {
        const group = (emoji.groups || [])[0];
        const character = (emoji.characters || [])[0];
        return [group?.name, character?.name].filter(Boolean).join('-') || '未添加分组或角色';
    }

    formatBytes(bytes) {
        const value = Number(bytes);
        if (!Number.isFinite(value) || value < 0) return '未知';
        if (value < 1024) return `${value} B`;
        if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
        return `${(value / 1024 / 1024).toFixed(2)} MB`;
    }

    formatDate(value) {
        if (!value) return '未知';
        const date = new Date(value);
        return Number.isNaN(date.getTime()) ? '未知' : date.toLocaleString('zh-CN');
    }

    renderDetailChips(items, type) {
        if (!Array.isArray(items) || !items.length) {
            return '<span class="detail-chip detail-chip-muted">无</span>';
        }
        return items.map(item => (
            `<span class="detail-chip detail-chip-${type}">${this.escape(item.name || '')}</span>`
        )).join('');
    }

    downloadEmoji(id) {
        const link = document.createElement('a');
        link.href = api.getEmojiDownloadUrl(id);
        link.download = '';
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    renderGrid(emojis) {
        const grid = document.getElementById('emoji-grid');
        if (!grid) return;
        if (!emojis.length) {
            grid.innerHTML = '<div class="empty-state">还没有表情包</div>';
            return;
        }
        grid.innerHTML = emojis.map(emoji => {
            const emotion = (emoji.emotions || [])[0]?.name || '未标情绪';
            return `
                <article class="image-card emoji-card" data-emoji-id="${this.escape(emoji.emoji_id)}">
                    <button type="button" class="image-card-open" aria-label="查看表情包 ${this.escape(emoji.emoji_id)} 的详情">
                        <div class="image-card-media">
                            <img class="image-card-img emoji-card-img"
                                 src="/${this.escape(emoji.file_path)}"
                                 loading="lazy"
                                 decoding="async"
                                 alt="表情包 ${this.escape(emoji.emoji_id)}">
                        </div>
                        <div class="image-card-info">
                            <div class="image-card-id">${this.escape(emoji.emoji_id)}</div>
                            <div class="image-card-characters">${this.escape(this.formatEmojiTags(emoji))}</div>
                            <div class="image-card-pid">${this.escape(emotion)}</div>
                        </div>
                    </button>
                </article>
            `;
        }).join('');
        grid.querySelectorAll('.emoji-card').forEach(card => {
            card.querySelector('.image-card-open')?.addEventListener('click', () => {
                this.showEmojiDetail(card.dataset.emojiId);
            });
        });
    }

    async showEmojiDetail(id) {
        try {
            const emoji = await api.getEmoji(id);
            const isAdmin = Boolean(window.auth?.isAdmin?.());
            const adminActions = isAdmin ? `
                <button class="btn btn-primary" onclick="emojiLibrary.showEditEmojiModal('${this.escape(emoji.emoji_id)}')">修改信息</button>
                <button class="btn btn-danger" onclick="emojiLibrary.deleteEmoji('${this.escape(emoji.emoji_id)}')">删除</button>
            ` : '';
            ui.showModal('表情包详情', `
                <div class="image-detail-card emoji-detail-card">
                    <div class="image-detail-media emoji-detail-media ${String(emoji.file_extension || '').toLowerCase() === 'gif' ? 'is-gif' : ''}">
                        <img src="/${this.escape(emoji.file_path)}" alt="表情包 ${this.escape(emoji.emoji_id)}" loading="eager" decoding="async">
                    </div>
                    <div class="image-detail-panel">
                        <div class="image-detail-head">
                            <span>表情包名片</span>
                            <h3>${this.escape(this.formatEmojiTags(emoji))}</h3>
                        </div>
                        <div class="detail-meta-grid">
                            <div class="detail-meta-item"><span>编号</span><strong>${this.escape(emoji.emoji_id)}</strong></div>
                            <div class="detail-meta-item"><span>原文件名</span><strong>${this.escape(emoji.original_filename || '未记录')}</strong></div>
                            <div class="detail-meta-item"><span>格式与大小</span><strong>${this.escape(String(emoji.file_extension || '').toUpperCase())} · ${this.formatBytes(emoji.file_size)}</strong></div>
                            <div class="detail-meta-item"><span>尺寸</span><strong>${emoji.width && emoji.height ? `${emoji.width} × ${emoji.height}` : '未知'}</strong></div>
                            <div class="detail-meta-item"><span>添加时间</span><strong>${this.escape(this.formatDate(emoji.created_at))}</strong></div>
                        </div>
                        <div class="detail-tag-section"><label>分组</label><div class="detail-chip-row">${this.renderDetailChips(emoji.groups, 'group')}</div></div>
                        <div class="detail-tag-section"><label>角色</label><div class="detail-chip-row">${this.renderDetailChips(emoji.characters, 'character')}</div></div>
                        <div class="detail-tag-section"><label>情绪</label><div class="detail-chip-row">${this.renderDetailChips(emoji.emotions, 'emotion')}</div></div>
                        <div class="detail-note"><span>备注</span><p>${this.escape(emoji.description || '无')}</p></div>
                    </div>
                    <div class="detail-actions">
                        <button class="btn btn-secondary" onclick="emojiLibrary.downloadEmoji('${this.escape(emoji.emoji_id)}')">下载表情包</button>
                        ${adminActions}
                        <button class="btn btn-secondary" onclick="ui.closeModal()">关闭</button>
                    </div>
                </div>
            `);
        } catch (error) {
            ui.showToast(`加载表情包详情失败: ${error.message}`, 'error');
        }
    }

    async showEditEmojiModal(id) {
        const emoji = await api.getEmoji(id);
        const group = (emoji.groups || [])[0];
        const character = (emoji.characters || [])[0];
        const emotion = (emoji.emotions || [])[0];
        this.uploadTags = {
            group_id: group?.id || character?.group_id || null,
            character_id: character?.id || null,
            emotion_id: emotion?.id || null,
        };
        ui.showModal('修改表情包信息', `
            <div class="emoji-edit-dialog">
                <div class="emoji-edit-summary">
                    <img src="/${this.escape(emoji.file_path)}" alt="">
                    <div>
                        <strong>${this.escape(emoji.emoji_id)}</strong>
                        <span>${this.escape(emoji.original_filename || '未记录原文件名')}</span>
                    </div>
                </div>
                <div class="form-group">
                    <div id="emoji-upload-tag-selector"></div>
                </div>
                <div class="form-group">
                    <label for="emoji-edit-description">备注</label>
                    <textarea id="emoji-edit-description" class="form-textarea" placeholder="可不填">${this.escape(emoji.description || '')}</textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="button" class="btn btn-primary" id="emoji-edit-submit" onclick="emojiLibrary.saveEmojiInfo('${this.escape(emoji.emoji_id)}')">保存修改</button>
                </div>
            </div>
        `);
        this.renderUploadTagControls();
    }

    async saveEmojiInfo(id) {
        const submit = document.getElementById('emoji-edit-submit');
        if (submit) submit.disabled = true;
        try {
            await api.updateEmoji(id, {
                group_ids: this.uploadTags.group_id ? [this.uploadTags.group_id] : [],
                character_ids: this.uploadTags.character_id ? [this.uploadTags.character_id] : [],
                emotion_ids: this.uploadTags.emotion_id ? [this.uploadTags.emotion_id] : [],
                description: document.getElementById('emoji-edit-description')?.value || '',
            });
            ui.closeModal();
            ui.showToast('表情包信息已更新', 'success');
            await this.refreshCharacterFacets();
            await this.load();
        } catch (error) {
            ui.showToast(`保存失败: ${error.message}`, 'error');
        } finally {
            if (submit && submit.isConnected) submit.disabled = false;
        }
    }

    renderEmotions() {
        const list = document.getElementById('emotion-list');
        if (!list) return;
        if (!this.emotions.length) {
            list.innerHTML = '<div class="empty-state">暂无情绪标签</div>';
            return;
        }
        list.innerHTML = this.emotions.map(emotion => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">${this.escape(emotion.name)}</div>
                    <div class="list-item-description">
                        ${this.escape(emotion.description || '无描述')}
                        ${(emotion.aliases || []).length ? ` | 别称: ${this.escape(emotion.aliases.join(' / '))}` : ''}
                    </div>
                </div>
                <div class="list-item-actions">
                    <button class="action-btn edit" onclick="emojiLibrary.showEditEmotionModal(${emotion.id})">编辑</button>
                    <button class="action-btn delete" onclick="emojiLibrary.deleteEmotion(${emotion.id})">删除</button>
                </div>
            </div>
        `).join('');
    }

    async showUploadModal() {
        if (!this.groups.length && !this.initialized) {
            await this.loadOptions();
        }
        this.clearUploadFile();
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null };
        ui.showModal('上传表情包', `
            <div class="emoji-upload-dialog">
                <div class="emoji-file-drop" id="emoji-file-drop" role="button" tabindex="0" aria-label="选择表情包文件">
                    <input type="file" id="emoji-file-input" accept="image/gif,image/jpeg,image/png,image/webp,image/bmp" hidden>
                    <div class="emoji-file-placeholder" id="emoji-file-placeholder">
                        <span class="upload-drop-icon"></span>
                        <strong>拖入文件，或点这里选择</strong>
                        <span>支持 GIF 动图和 JPG、PNG、WEBP、BMP 静态图</span>
                    </div>
                    <div class="emoji-file-preview" id="emoji-file-preview" hidden>
                        <img id="emoji-preview-image" alt="待上传表情包预览">
                        <div class="emoji-file-preview-info">
                            <strong id="emoji-preview-name"></strong>
                            <span id="emoji-preview-meta"></span>
                            <button type="button" class="btn-link emoji-file-remove" onclick="event.stopPropagation(); emojiLibrary.clearUploadFile()">重新选择</button>
                        </div>
                    </div>
                </div>
                <div class="form-group">
                    <div id="emoji-upload-tag-selector"></div>
                </div>
                <div class="form-group">
                    <label>备注</label>
                    <textarea id="emoji-description" class="form-textarea" placeholder="可不填"></textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="emojiLibrary.cancelUpload()">取消</button>
                    <button type="button" class="btn btn-primary" id="emoji-upload-submit" onclick="emojiLibrary.upload()">上传到表情包库</button>
                </div>
            </div>
        `);
        this.renderUploadTagControls();
        this.bindUploadFilePicker();
    }

    bindUploadFilePicker() {
        const dropZone = document.getElementById('emoji-file-drop');
        const input = document.getElementById('emoji-file-input');
        if (!dropZone || !input) return;
        dropZone.addEventListener('click', event => {
            if (!event.target.closest('.emoji-file-remove')) input.click();
        });
        dropZone.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                input.click();
            }
        });
        input.addEventListener('change', () => this.handleUploadFile(input.files?.[0]));
        dropZone.addEventListener('dragover', event => {
            event.preventDefault();
            dropZone.classList.add('dragover');
        });
        dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
        dropZone.addEventListener('drop', event => {
            event.preventDefault();
            dropZone.classList.remove('dragover');
            this.handleUploadFile(event.dataTransfer?.files?.[0]);
        });
    }

    isSupportedUploadFile(file) {
        if (!file) return false;
        const extension = file.name.split('.').pop()?.toLowerCase();
        return ['gif', 'jpg', 'jpeg', 'png', 'webp', 'bmp'].includes(extension);
    }

    handleUploadFile(file) {
        if (!this.isSupportedUploadFile(file)) {
            ui.showToast('请选择 GIF、JPG、PNG、WEBP 或 BMP 图片', 'warning');
            return;
        }
        this.clearUploadFile(false);
        this.uploadFile = file;
        this.uploadPreviewUrl = URL.createObjectURL(file);
        const placeholder = document.getElementById('emoji-file-placeholder');
        const preview = document.getElementById('emoji-file-preview');
        const image = document.getElementById('emoji-preview-image');
        if (placeholder) placeholder.hidden = true;
        if (preview) preview.hidden = false;
        if (image) image.src = this.uploadPreviewUrl;
        const name = document.getElementById('emoji-preview-name');
        const meta = document.getElementById('emoji-preview-meta');
        if (name) name.textContent = file.name;
        if (meta) meta.textContent = `${file.name.toLowerCase().endsWith('.gif') ? 'GIF 动图' : '静态图片'} · ${(file.size / 1024 / 1024).toFixed(2)} MB`;
    }

    clearUploadFile(resetInput = true) {
        if (this.uploadPreviewUrl) URL.revokeObjectURL(this.uploadPreviewUrl);
        this.uploadPreviewUrl = null;
        this.uploadFile = null;
        const input = document.getElementById('emoji-file-input');
        if (resetInput && input) input.value = '';
        const placeholder = document.getElementById('emoji-file-placeholder');
        const preview = document.getElementById('emoji-file-preview');
        const image = document.getElementById('emoji-preview-image');
        if (placeholder) placeholder.hidden = false;
        if (preview) preview.hidden = true;
        if (image) image.removeAttribute('src');
    }

    cancelUpload() {
        this.clearUploadFile();
        ui.closeModal();
    }

    async upload() {
        const file = this.uploadFile || document.getElementById('emoji-file-input')?.files?.[0];
        if (!file) {
            ui.showToast('请选择表情包文件', 'warning');
            return;
        }
        if (!this.isSupportedUploadFile(file)) {
            ui.showToast('不支持这个图片格式', 'warning');
            return;
        }
        const submit = document.getElementById('emoji-upload-submit');
        if (submit) submit.disabled = true;
        try {
            await api.uploadEmoji(file, {
                group_ids: this.uploadTags.group_id ? [this.uploadTags.group_id] : [],
                character_ids: this.uploadTags.character_id ? [this.uploadTags.character_id] : [],
                emotion_ids: this.uploadTags.emotion_id ? [this.uploadTags.emotion_id] : [],
                description: document.getElementById('emoji-description')?.value || '',
            });
            this.clearUploadFile();
            ui.closeModal();
            ui.showToast('表情包已上传', 'success');
            this.pagination.currentPage = 1;
            await this.refreshCharacterFacets();
            await this.load();
        } catch (error) {
            ui.showToast(`上传失败: ${error.message}`, 'error');
        } finally {
            if (submit && submit.isConnected) submit.disabled = false;
        }
    }

    showCreateEmotionModal() {
        this.showEmotionModal();
    }

    showEditEmotionModal(id) {
        const emotion = this.emotions.find(item => item.id === id);
        if (emotion) this.showEmotionModal(emotion);
    }

    showEmotionModal(emotion = null) {
        const aliases = (emotion?.aliases || []).join(', ');
        ui.showModal(emotion ? '编辑情绪' : '添加情绪', `
            <div class="form-group">
                <label>名称</label>
                <input id="emotion-name" class="form-input" value="${this.escape(emotion?.name || '')}">
            </div>
            <div class="form-group">
                <label>别称</label>
                <input id="emotion-aliases" class="form-input" value="${this.escape(aliases)}" placeholder="多个别称用逗号分隔">
            </div>
            <div class="form-group">
                <label>说明</label>
                <textarea id="emotion-description" class="form-textarea">${this.escape(emotion?.description || '')}</textarea>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                <button class="btn btn-primary" onclick="emojiLibrary.saveEmotion(${emotion?.id || 'null'})">保存</button>
            </div>
        `);
    }

    async saveEmotion(id = null) {
        const payload = {
            name: document.getElementById('emotion-name')?.value?.trim() || '',
            aliases: (document.getElementById('emotion-aliases')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
            description: document.getElementById('emotion-description')?.value || '',
        };
        if (!payload.name) {
            ui.showToast('请填写情绪名称', 'warning');
            return;
        }
        if (id) {
            await api.updateEmotionTag(id, payload);
        } else {
            await api.createEmotionTag(payload);
        }
        ui.closeModal();
        await this.loadOptions();
        await this.load();
    }

    async deleteEmotion(id) {
        if (!confirm('确定删除这个情绪吗？')) return;
        await api.deleteEmotionTag(id);
        await this.loadOptions();
        await this.load();
    }

    async deleteEmoji(id) {
        if (!confirm('确定删除这个表情包吗？')) return;
        await api.deleteEmoji(id);
        ui.closeModal();
        ui.showToast('表情包已删除', 'success');
        await this.refreshCharacterFacets();
        await this.load();
    }
}

window.emojiLibrary = new EmojiLibrary();
