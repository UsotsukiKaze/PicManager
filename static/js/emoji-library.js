class EmojiLibrary {
    constructor() {
        this.groups = [];
        this.characters = [];
        this.emojiCharacters = [];
        this.emotions = [];
        this.initialized = false;
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null, function_id: null };
        this.uploadPickerDraft = null;
        this.uploadFile = null;
        this.uploadPreviewUrl = null;
        this.pagination = { currentPage: 1, totalPages: 1, limit: 20, total: 0 };
        this.requestSerial = 0;
        this.descriptionTimer = null;
        this.tagType = 'all';
        this.tagQuery = '';
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
        this.restoreFromUrl();
        this.bindLibraryControls();
        await this.loadOptions();
        await this.load();
        this.initialized = true;
    }

    async resume() {
        this.restoreFromUrl();
        await this.loadOptions();
        await this.load();
    }

    restoreFromUrl() {
        const query = new URLSearchParams((window.location.hash.split('?')[1] || '').split('#')[0]);
        const ids = { group_id: 'emoji-group-filter', character_id: 'emoji-character-filter', emotion_id: 'emoji-emotion-filter', function_id: 'emoji-function-filter', description: 'emoji-description-filter' };
        this.restoredFilters = Object.fromEntries(Object.entries(ids).map(([key]) => [key, query.get(key) || '']));
        const page = Number(query.get('page'));
        this.pagination.currentPage = Number.isSafeInteger(page) && page > 0 ? page : 1;
        this.restoredTab = query.get('tab') === 'tags' ? 'emotion-management' : 'emoji-list';
    }

    syncUrl() {
        if (document.querySelector('.modern-emoji')) return;
        if (!window.location.hash.startsWith('#/emoji')) return;
        const query = new URLSearchParams();
        for (const [key, id] of Object.entries({ group_id: 'emoji-group-filter', character_id: 'emoji-character-filter', emotion_id: 'emoji-emotion-filter', function_id: 'emoji-function-filter', description: 'emoji-description-filter' })) {
            const value = document.getElementById(id)?.value?.trim();
            if (value) query.set(key, value);
        }
        if (this.pagination.currentPage > 1) query.set('page', String(this.pagination.currentPage));
        if (document.querySelector('#page-emoji-library .tab-btn[data-tab="emotion-management"]')?.classList.contains('active')) query.set('tab', 'tags');
        const next = `#/emoji${query.size ? `?${query}` : ''}`;
        if (window.location.hash !== next) window.history.replaceState(window.history.state, '', next);
    }

    bindLibraryControls() {
        const page = document.getElementById('page-emoji-library');
        if (!page || page.dataset.emojiBound) return;
        page.dataset.emojiBound = 'true';
        for (const id of ['emoji-group-filter', 'emoji-character-filter', 'emoji-emotion-filter', 'emoji-function-filter']) {
            document.getElementById(id)?.addEventListener('change', event => {
                if (event.target.id === 'emoji-group-filter') {
                    const character = this.getById(this.characters, document.getElementById('emoji-character-filter')?.value);
                    if (character && event.target.value && String(character.group_id) !== event.target.value) {
                        document.getElementById('emoji-character-filter').value = '';
                    }
                    this.renderCharacterOptions();
                }
                this.applyFilters();
            });
        }
        document.getElementById('emoji-character-query')?.addEventListener('input', () => this.renderCharacterOptions());
        document.getElementById('emoji-description-filter')?.addEventListener('input', () => {
            window.clearTimeout(this.descriptionTimer);
            this.descriptionTimer = window.setTimeout(() => this.applyFilters(), 300);
        });
        document.getElementById('emoji-description-filter')?.addEventListener('keydown', event => {
            if (event.key === 'Enter') { event.preventDefault(); window.clearTimeout(this.descriptionTimer); this.applyFilters(); }
        });
        document.getElementById('emoji-tag-search')?.addEventListener('input', event => { this.tagQuery = event.target.value.trim().toLocaleLowerCase(); this.renderEmotions(); });
        page.querySelector('.emoji-tag-tabs')?.addEventListener('click', event => {
            const button = event.target.closest('[data-emoji-tag-type]');
            if (!button) return;
            this.tagType = button.dataset.emojiTagType;
            page.querySelectorAll('[data-emoji-tag-type]').forEach(item => item.classList.toggle('is-active', item === button));
            this.renderEmotions();
        });
        page.querySelector('.emoji-tab-header')?.addEventListener('click', () => window.setTimeout(() => this.syncUrl(), 0));
        document.getElementById('emoji-grid')?.addEventListener('click', event => {
            const download = event.target.closest('[data-emoji-download]');
            if (download) { this.downloadEmoji(download.dataset.emojiDownload); return; }
            const open = event.target.closest('.image-card-open');
            if (open) this.showEmojiDetail(open.closest('.emoji-card').dataset.emojiId);
        });
    }

    optionHtml(items, placeholder) {
        return `<option value="">${placeholder}</option>` + items.map(item => (
            `<option value="${item.id}">${this.escape(item.name)}</option>`
        )).join('');
    }

    isFunctionTag(tag) {
        return String(tag?.name || '').trim().startsWith('#');
    }

    getEmotionTags(functional, tags = this.emotions) {
        return (tags || []).filter(tag => this.isFunctionTag(tag) === functional);
    }

    selectedEmotionIds() {
        return [this.uploadTags.emotion_id, this.uploadTags.function_id].filter(Boolean);
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
        const selectedFilters = this.restoredFilters || {
            group_id: document.getElementById('emoji-group-filter')?.value || '',
            character_id: document.getElementById('emoji-character-filter')?.value || '',
            emotion_id: document.getElementById('emoji-emotion-filter')?.value || '',
            function_id: document.getElementById('emoji-function-filter')?.value || '',
            description: document.getElementById('emoji-description-filter')?.value || '',
        };
        this.restoredFilters = null;
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
        const functionFilter = document.getElementById('emoji-function-filter');
        if (groupFilter) groupFilter.innerHTML = this.optionHtml(this.groups, '全部分组');
        if (characterFilter) characterFilter.innerHTML = this.optionHtml(this.characters, '全部角色');
        if (emotionFilter) emotionFilter.innerHTML = this.optionHtml(this.getEmotionTags(false), '全部基础情绪');
        if (functionFilter) functionFilter.innerHTML = this.optionHtml(this.getEmotionTags(true), '全部功能');
        if (groupFilter) groupFilter.value = selectedFilters.group_id;
        if (characterFilter) characterFilter.value = selectedFilters.character_id;
        if (emotionFilter) emotionFilter.value = selectedFilters.emotion_id;
        if (functionFilter) functionFilter.value = selectedFilters.function_id;
        const descriptionFilter = document.getElementById('emoji-description-filter');
        if (descriptionFilter) descriptionFilter.value = selectedFilters.description || '';
        this.renderCharacterOptions();
        window.queryPanels?.update('emoji-query-panel');
        this.renderCharacterTabs();

        if (this.restoredTab === 'emotion-management') window.ui?.switchTab('emotion-management');
        this.restoredTab = null;

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
        tabs.innerHTML = button('', '不限') + this.emojiCharacters.map(character => (
            button(character.id, character.name, character.emoji_count)
        )).join('');
        const activeTab = tabs.querySelector('.active');
        if (this.initialized && activeTab) {
            const tabRect = tabs.getBoundingClientRect();
            const activeRect = activeTab.getBoundingClientRect();
            if (activeRect.left < tabRect.left || activeRect.right > tabRect.right) {
                tabs.scrollTo({ left: tabs.scrollLeft + activeRect.left - tabRect.left - 12, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
            }
        }
    }

    renderCharacterOptions() {
        const select = document.getElementById('emoji-character-filter');
        if (!select) return;
        const current = select.value;
        const group = document.getElementById('emoji-group-filter')?.value || '';
        const query = document.getElementById('emoji-character-query')?.value.trim().toLocaleLowerCase() || '';
        const available = this.characters.filter(character => (!group || String(character.group_id) === group)
            && (!query || this.filterItems([character], query).length || String(character.id) === current));
        select.innerHTML = this.optionHtml(available, '全部角色');
        select.value = current;
        if (select.selectedIndex < 0) select.value = '';
    }

    selectCharacter(characterId) {
        const filter = document.getElementById('emoji-character-filter');
        const character = this.getById(this.characters, characterId);
        const group = document.getElementById('emoji-group-filter');
        if (character?.group_id && group?.value && String(character.group_id) !== group.value) group.value = String(character.group_id);
        if (filter) filter.value = String(characterId || '');
        this.renderCharacterOptions();
        this.renderCharacterTabs();
        window.queryPanels?.update('emoji-query-panel');
        return this.applyFilters();
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
            emotion: { key: 'emotion_id', label: '基础情绪', source: this.emotions },
            function: { key: 'function_id', label: '功能', source: this.emotions },
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
                ${this.tagButton('function', this.uploadTags.function_id)}
                <button type="button" class="pm-tag-add" onclick="emojiLibrary.openUploadTagPicker()">+</button>
            </div>
            <small class="emoji-tag-hint">基础情绪和功能标签各选一个，也可只选其中一类。功能标签以 # 开头。</small>
        `;
    }

    clearUploadTag(key) {
        const source = key === 'group_id' ? this.groups : key === 'character_id' ? this.characters : this.emotions;
        const tag = this.getById(source, this.uploadTags[key]);
        if (!this.uploadTags[key] || !confirm(`确认从当前表情包移除“${tag?.name || '所选标签'}”？\n不会删除标签资料。`)) return;
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
        const labelMap = { group: '分组', character: '角色', emotion: '基础情绪', function: '功能' };
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
                <input class="form-input tag-picker-search" placeholder="搜索分组、角色、基础情绪或 #功能" autocomplete="off">
                <div class="tag-picker-columns tag-picker-columns-4">
                    <section>
                        <h4>分组</h4>
                        <div class="tag-picker-list" data-type="group"></div>
                    </section>
                    <section>
                        <h4>角色</h4>
                        <div class="tag-picker-list" data-type="character"></div>
                    </section>
                    <section>
                        <h4>基础情绪（最多一个）</h4>
                        <div class="tag-picker-list" data-type="emotion"></div>
                    </section>
                    <section>
                        <h4>#功能（最多一个）</h4>
                        <div class="tag-picker-list" data-type="function"></div>
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
            } else if (input.name === 'emoji-picker-function') {
                this.uploadPickerDraft.function_id = value;
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
        const emotions = this.filterItems(this.getEmotionTags(false), query);
        const functions = this.filterItems(this.getEmotionTags(true), query);

        root.querySelector('[data-type="group"]').innerHTML = groups.map(group =>
            this.pickerOption(group, 'group', Number(group.id) === Number(draft.group_id))
        ).join('') || '<div class="empty-state">没有分组</div>';
        root.querySelector('[data-type="character"]').innerHTML = characters.map(character =>
            this.pickerOption(character, 'character', Number(character.id) === Number(draft.character_id))
        ).join('') || '<div class="empty-state">没有角色</div>';
        root.querySelector('[data-type="emotion"]').innerHTML = this.pickerOption(
            { id: 0, name: '不设置基础情绪' }, 'emotion', !draft.emotion_id
        ) + emotions.map(emotion =>
            this.pickerOption(emotion, 'emotion', Number(emotion.id) === Number(draft.emotion_id))
        ).join('');
        root.querySelector('[data-type="function"]').innerHTML = this.pickerOption(
            { id: 0, name: '不设置功能标签' }, 'function', !draft.function_id
        ) + functions.map(tag =>
            this.pickerOption(tag, 'function', Number(tag.id) === Number(draft.function_id))
        ).join('');
    }

    confirmUploadTagPicker(modalId) {
        const draft = this.uploadPickerDraft || this.uploadTags;
        const character = this.getById(this.characters, draft.character_id);
        const selected = {
            group_id: character?.group_id || draft.group_id || null,
            character_id: draft.character_id || null,
            emotion_id: draft.emotion_id || null,
            function_id: draft.function_id || null,
        };
        const removed = Object.keys(selected).filter(key => this.uploadTags[key] && !selected[key]);
        if (removed.length && !confirm(`确认从当前表情包移除 ${removed.length} 个标签？\n不会删除标签资料。`)) return;
        this.uploadTags = selected;
        this.uploadPickerDraft = null;

        ui.closeModal();
        this.renderUploadTagControls();
    }

    async load() {
        if (!this.groups.length && !this.initialized) {
            await this.loadOptions();
        }
        const serial = ++this.requestSerial;
        const params = {
            group_id: document.getElementById('emoji-group-filter')?.value || '',
            character_id: document.getElementById('emoji-character-filter')?.value || '',
            emotion_id: document.getElementById('emoji-emotion-filter')?.value || '',
            function_id: document.getElementById('emoji-function-filter')?.value || '',
            description: document.getElementById('emoji-description-filter')?.value?.trim() || '',
            limit: this.pagination.limit,
            offset: (this.pagination.currentPage - 1) * this.pagination.limit,
        };
        document.getElementById('emoji-results')?.classList.add('is-loading');
        let result;
        try { result = await api.searchEmojis(params); }
        catch (error) {
            if (serial === this.requestSerial) {
                document.getElementById('emoji-results')?.classList.remove('is-loading');
                ui.showToast(`加载表情包失败: ${error.message}`, 'error');
            }
            return;
        }
        if (serial !== this.requestSerial) return;
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
        this.renderResults();
        document.getElementById('emoji-results')?.classList.remove('is-loading');
        this.syncUrl();
    }

    applyFilters() {
        window.clearTimeout(this.descriptionTimer);
        this.pagination.currentPage = 1;
        this.renderCharacterTabs();
        window.queryPanels?.update('emoji-query-panel');
        this.renderResults();
        return this.load();
    }

    clearFilter(key) {
        const id = { group_id: 'emoji-group-filter', character_id: 'emoji-character-filter', emotion_id: 'emoji-emotion-filter', function_id: 'emoji-function-filter', description: 'emoji-description-filter' }[key];
        if (!id) return;
        document.getElementById(id).value = '';
        if (key === 'group_id') this.renderCharacterOptions();
        this.applyFilters();
    }

    clearFilters() {
        for (const id of ['emoji-group-filter', 'emoji-character-filter', 'emoji-emotion-filter', 'emoji-function-filter', 'emoji-description-filter', 'emoji-character-query']) {
            document.getElementById(id).value = '';
        }
        this.renderCharacterOptions();
        this.applyFilters();
    }

    renderResults() {
        const target = document.getElementById('emoji-results');
        if (!target) return;
        const sources = [
            ['group_id', 'emoji-group-filter', '分组'],
            ['character_id', 'emoji-character-filter', '角色'],
            ['emotion_id', 'emoji-emotion-filter', '情绪'],
            ['function_id', 'emoji-function-filter', '功能'],
            ['description', 'emoji-description-filter', '备注'],
        ];
        const chips = sources.map(([key, id, label]) => {
            const field = document.getElementById(id);
            if (!field?.value) return '';
            const value = field.tagName === 'SELECT' ? field.selectedOptions[0]?.textContent : field.value;
            return `<button type="button" class="emoji-result-chip" onclick="emojiLibrary.clearFilter('${key}')" aria-label="移除${label}筛选：${this.escape(value)}"><span>${label}：${this.escape(value)}</span><b aria-hidden="true">×</b></button>`;
        }).filter(Boolean);
        target.innerHTML = `<span class="emoji-result-count">${chips.length ? '找到' : '共'} ${this.pagination.total} 个表情包</span><div class="emoji-result-chips">${chips.join('')}</div>${chips.length ? '<button type="button" class="emoji-result-clear" onclick="emojiLibrary.clearFilters()">清除条件</button>' : ''}`;
    }

    changePage(page) {
        const nextPage = Number(page);
        if (!Number.isInteger(nextPage) || nextPage < 1 || nextPage > this.pagination.totalPages) return;
        this.pagination.currentPage = nextPage;
        this.load();
        this.syncUrl();
        document.getElementById('emoji-results')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
    }

    renderPagination() {
        const container = document.getElementById('emoji-pagination');
        if (!container) return;
        const { currentPage, totalPages, total } = this.pagination;
        if (totalPages <= 1) {
            container.innerHTML = '';
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
            const filtered = ['emoji-group-filter', 'emoji-character-filter', 'emoji-emotion-filter', 'emoji-function-filter', 'emoji-description-filter'].some(id => document.getElementById(id)?.value);
            grid.innerHTML = `<div class="emoji-empty"><span aria-hidden="true">✦</span><p>${filtered ? '没有匹配的表情包' : '还没有表情包'}</p>${filtered ? '<button type="button" onclick="emojiLibrary.clearFilters()">清除搜索条件</button>' : ''}</div>`;
            return;
        }
        grid.innerHTML = emojis.map((emoji, index) => {
            const tags = [
                ...this.getEmotionTags(false, emoji.emotions),
                ...this.getEmotionTags(true, emoji.emotions),
            ].slice(0, 2);
            const character = (emoji.characters || [])[0]?.name || '';
            const group = (emoji.groups || [])[0]?.name || '';
            const title = character || group || '未分类';
            const gif = String(emoji.file_extension || '').toLowerCase() === 'gif';
            return `
                <article class="image-card emoji-card" data-emoji-id="${this.escape(emoji.emoji_id)}" style="--emoji-order:${Math.min(index % 5, 4)}">
                    <button type="button" class="image-card-open" aria-label="查看表情包 ${this.escape(emoji.emoji_id)} 的详情">
                        <div class="image-card-media">
                            <img class="image-card-img emoji-card-img"
                                 src="/${this.escape(emoji.file_path)}"
                                 loading="lazy"
                                 decoding="async"
                                 alt="表情包 ${this.escape(emoji.emoji_id)}">
                            ${gif ? '<span class="emoji-format-badge">GIF</span>' : ''}
                        </div>
                        <div class="image-card-info">
                            <strong class="emoji-card-title">${this.escape(title)}</strong>
                            <div class="emoji-card-meta">${group && character ? `<span class="emoji-card-group">${this.escape(group)}</span>` : ''}${tags.map(tag => `<span class="emoji-card-tag ${this.isFunctionTag(tag) ? 'is-function' : ''}">${this.escape(tag.name)}</span>`).join('')}</div>
                        </div>
                    </button>
                    <button type="button" class="emoji-card-download" data-emoji-download="${this.escape(emoji.emoji_id)}" aria-label="下载表情包 ${this.escape(emoji.emoji_id)}" title="下载表情包">↓</button>
                </article>
            `;
        }).join('');
    }

    async showEmojiDetail(id) {
        try {
            const emoji = await api.getEmoji(id);
            const isAdmin = Boolean(window.auth?.isAdmin?.());
            const adminActions = isAdmin ? `<button class="btn btn-secondary" onclick="emojiLibrary.showEditEmojiModal('${this.escape(emoji.emoji_id)}')">编辑信息</button><details class="emoji-detail-more"><summary aria-label="更多操作">···</summary><button class="btn btn-danger" onclick="emojiLibrary.deleteEmoji('${this.escape(emoji.emoji_id)}')">删除表情包</button></details>` : '';
            ui.showModal('表情包详情', `
                <div class="image-detail-card emoji-detail-card">
                    <div class="image-detail-media emoji-detail-media ${String(emoji.file_extension || '').toLowerCase() === 'gif' ? 'is-gif' : ''}">
                        <img src="/${this.escape(emoji.file_path)}" alt="表情包 ${this.escape(emoji.emoji_id)}" loading="eager" decoding="async">
                    </div>
                    <div class="image-detail-panel">
                        <div class="image-detail-head">
                            <span>EMOTE ARCHIVE</span>
                            <h3>${this.escape(this.formatEmojiTags(emoji))}</h3>
                        </div>
                        <p class="emoji-detail-spec">${this.escape(String(emoji.file_extension || '').toUpperCase())} · ${this.formatBytes(emoji.file_size)} · ${emoji.width && emoji.height ? `${emoji.width} × ${emoji.height}` : '尺寸未知'}</p>
                        <div class="detail-tag-section"><label>分组</label><div class="detail-chip-row">${this.renderDetailChips(emoji.groups, 'group')}</div></div>
                        <div class="detail-tag-section"><label>角色</label><div class="detail-chip-row">${this.renderDetailChips(emoji.characters, 'character')}</div></div>
                        <div class="detail-tag-section"><label>基础情绪</label><div class="detail-chip-row">${this.renderDetailChips(this.getEmotionTags(false, emoji.emotions), 'emotion')}</div></div>
                        <div class="detail-tag-section"><label>功能标签</label><div class="detail-chip-row">${this.renderDetailChips(this.getEmotionTags(true, emoji.emotions), 'function')}</div></div>
                        ${emoji.description ? `<div class="detail-note"><span>备注</span><p>${this.escape(emoji.description)}</p></div>` : ''}
                        <details class="emoji-file-details"><summary>文件信息</summary><dl><dt>编号</dt><dd>${this.escape(emoji.emoji_id)}</dd><dt>原文件名</dt><dd>${this.escape(emoji.original_filename || '未记录')}</dd><dt>添加时间</dt><dd>${this.escape(this.formatDate(emoji.created_at))}</dd></dl></details>
                    </div>
                    <div class="detail-actions">
                        <button class="btn btn-primary" onclick="emojiLibrary.downloadEmoji('${this.escape(emoji.emoji_id)}')">下载表情包</button>
                        ${adminActions}
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
        const emotion = this.getEmotionTags(false, emoji.emotions)[0];
        const functionTag = this.getEmotionTags(true, emoji.emotions)[0];
        this.uploadTags = {
            group_id: group?.id || character?.group_id || null,
            character_id: character?.id || null,
            emotion_id: emotion?.id || null,
            function_id: functionTag?.id || null,
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
                emotion_ids: this.selectedEmotionIds(),
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
        const items = this.emotions.filter(tag => (this.tagType === 'all' || this.isFunctionTag(tag) === (this.tagType === 'function'))
            && (!this.tagQuery || this.filterItems([tag], this.tagQuery).length));
        if (!items.length) {
            list.innerHTML = `<div class="emoji-empty"><span aria-hidden="true">✦</span><p>${this.emotions.length ? '没有匹配的标签' : '暂无情绪或功能标签'}</p></div>`;
            return;
        }
        list.innerHTML = items.map(emotion => `
            <div class="list-item emoji-tag-card">
                <div class="list-item-info">
                    <div class="list-item-name">${this.escape(emotion.name)} <small class="emoji-tag-kind ${this.isFunctionTag(emotion) ? 'is-function' : ''}">${this.isFunctionTag(emotion) ? '功能标签' : '基础情绪'}</small></div>
                    ${emotion.description || (emotion.aliases || []).length ? `<div class="list-item-description">${emotion.description ? this.escape(emotion.description) : ''}${(emotion.aliases || []).length ? `<span>别称：${this.escape(emotion.aliases.join(' / '))}</span>` : ''}</div>` : ''}
                </div>
                <div class="list-item-actions">
                    <button class="action-btn edit" onclick="emojiLibrary.showEditEmotionModal(${emotion.id})">编辑</button>
                    <details class="emoji-tag-more"><summary aria-label="${this.escape(emotion.name)}更多操作">···</summary><button class="action-btn delete" onclick="emojiLibrary.deleteEmotion(${emotion.id})">删除</button></details>
                </div>
            </div>
        `).join('');
    }

    async showUploadModal() {
        if (!this.groups.length && !this.initialized) {
            await this.loadOptions();
        }
        this.clearUploadFile();
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null, function_id: null };
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
                            <button type="button" class="btn-link emoji-file-remove" onclick="event.stopPropagation(); emojiLibrary.removeUploadFile()">重新选择</button>
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

    removeUploadFile() {
        if (!this.uploadFile || !confirm(`确认移除当前选择的“${this.uploadFile.name}”？\n原文件不会被删除。`)) return;
        this.clearUploadFile();
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
                emotion_ids: this.selectedEmotionIds(),
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
        ui.showModal(emotion ? '编辑情绪 / 功能标签' : '添加情绪 / 功能标签', `
            <div class="emoji-tag-kind-picker" role="group" aria-label="标签类型"><label><input type="radio" name="emotion-kind" value="emotion" ${!this.isFunctionTag(emotion) ? 'checked' : ''}>基础情绪</label><label><input type="radio" name="emotion-kind" value="function" ${this.isFunctionTag(emotion) ? 'checked' : ''}>功能标签</label></div>
            <div class="form-group">
                <label>名称</label>
                <input id="emotion-name" class="form-input" maxlength="255" value="${this.escape(String(emotion?.name || '').replace(/^#/, ''))}" placeholder="例如 开心、摸头">
                <small class="emoji-tag-hint">功能标签会自动添加 # 前缀。</small>
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
        const kind = document.querySelector('input[name="emotion-kind"]:checked')?.value || 'emotion';
        const name = document.getElementById('emotion-name')?.value?.trim().replace(/^#+/, '').trim() || '';
        const payload = {
            name: kind === 'function' && name ? `#${name}` : name,
            aliases: (document.getElementById('emotion-aliases')?.value || '').split(',').map(item => item.trim()).filter(Boolean),
            description: document.getElementById('emotion-description')?.value || '',
        };
        if (!name) {
            ui.showToast('请填写标签名称', 'warning');
            return;
        }
        try {
            if (id) {
                await api.updateEmotionTag(id, payload);
            } else {
                await api.createEmotionTag(payload);
            }
            ui.closeModal();
            await this.loadOptions();
            await this.load();
        } catch (error) {
            ui.showToast(`保存标签失败: ${error.message}`, 'error');
        }
    }

    async deleteEmotion(id) {
        if (!confirm('确定删除这个情绪或功能标签吗？')) return;
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
