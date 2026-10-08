class ImageTagSelector {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.title = options.title || '添加标签';
        this.allowedTypes = options.allowedTypes || ['group', 'character', 'feature_tag'];
        this.groups = [];
        this.characters = [];
        this.featureTags = [];
        this.selected = { group_ids: [], character_ids: [], feature_tag_ids: [] };
        this.onChange = options.onChange || null;
        this.addLabel = options.addLabel || '+';
        this.allowCreate = Boolean(options.allowCreate);
        this.searchTimer = null;
        this.render();
    }

    setData({ groups = [], characters = [], featureTags = [] }) {
        this.groups = groups;
        this.characters = characters;
        this.featureTags = featureTags;
        this.render();
    }

    setSelected({ group_ids = [], character_ids = [], feature_tag_ids = [] }) {
        this.selected = {
            group_ids: this.unique(group_ids),
            character_ids: this.unique(character_ids),
            feature_tag_ids: this.unique(feature_tag_ids),
        };
        this.expandFromCharacters();
        this.render();
    }

    unique(values) {
        return Array.from(new Set((values || []).map(Number).filter(Number.isFinite)));
    }

    addUnique(key, ids) {
        this.selected[key] = this.unique([...(this.selected[key] || []), ...(ids || [])]);
    }

    expandFromCharacters() {
        const selectedCharacters = this.characters.filter(c => this.selected.character_ids.includes(c.id));
        selectedCharacters.forEach(character => {
            if (character.group_id) this.addUnique('group_ids', [character.group_id]);
            const tagIds = character.feature_tag_ids || (character.feature_tags || []).map(tag => tag.id);
            this.addUnique('feature_tag_ids', tagIds);
        });
    }

    getValue() {
        this.expandFromCharacters();
        return {
            group_ids: this.selected.group_ids,
            character_ids: this.selected.character_ids,
            feature_tag_ids: this.selected.feature_tag_ids,
        };
    }

    notify() {
        this.expandFromCharacters();
        this.render();
        if (this.onChange) this.onChange(this.getValue());
    }

    remove(type, id) {
        const key = `${type}_ids`;
        if (!(this.selected[key] || []).includes(id)) return;
        if (!confirm(`确认从当前图片移除“${this.getLabel(type, id)}”标签？\n不会删除图库中的标签或 Pixiv 关联。`)) return;
        this.selected[key] = (this.selected[key] || []).filter(item => item !== id);
        this.notify();
    }

    getLabel(type, id) {
        const source = type === 'group' ? this.groups : type === 'character' ? this.characters : this.featureTags;
        return (source.find(item => item.id === id) || {}).name || id;
    }

    escapeHTML(value) {
        return window.PicManagerSecurity.escapeHTML(value);
    }

    renderTag(type, id) {
        const labelMap = { group: '分组', character: '角色', feature_tag: '特征' };
        return `
            <button type="button" class="pm-tag pm-tag-${type}" data-tag-type="${type}" data-tag-id="${id}" onclick="window.imageTagSelectors['${this.container.id}'].remove('${type}', ${id})">
                <span>${this.escapeHTML(this.getLabel(type, id))}</span>
                <small>${labelMap[type]}</small>
                <b aria-hidden="true">×</b>
            </button>
        `;
    }

    render() {
        if (!this.container) return;
        this.container.innerHTML = `
            <div class="pm-tag-box">
                ${this.allowedTypes.includes('group') ? this.selected.group_ids.map(id => this.renderTag('group', id)).join('') : ''}
                ${this.allowedTypes.includes('character') ? this.selected.character_ids.map(id => this.renderTag('character', id)).join('') : ''}
                ${this.allowedTypes.includes('feature_tag') ? this.selected.feature_tag_ids.map(id => this.renderTag('feature_tag', id)).join('') : ''}
                <button type="button" class="pm-tag-add" aria-label="添加标签" onclick="window.imageTagSelectors['${this.container.id}'].openPicker()">${this.escapeHTML(this.addLabel)}</button>
            </div>
        `;
    }

    hasPickerData() {
        const sources = {
            group: this.groups,
            character: this.characters,
            feature_tag: this.featureTags,
        };
        return this.allowedTypes.every(type => Array.isArray(sources[type]) && sources[type].length > 0);
    }

    async refreshData({ forceRefresh = false } = {}) {
        // Upload-page activation already loads these collections. Reusing them
        // avoids refetching every paginated entity list whenever the picker is
        // opened. CRUD actions invalidate UIManager's cache explicitly.
        if (!forceRefresh && this.hasPickerData()) return;

        const loaders = window.ui ? {
            group: () => ui.loadGroupsData(forceRefresh, true),
            character: () => ui.loadCharactersData(forceRefresh, true),
            feature_tag: () => ui.loadFeatureTagsData(forceRefresh, true),
        } : {
            group: () => api.getGroups(),
            character: () => api.getCharacters(),
            feature_tag: () => api.getFeatureTags(),
        };
        const requested = await Promise.all(this.allowedTypes.map(type => loaders[type]()));
        const byType = Object.fromEntries(this.allowedTypes.map((type, index) => [type, requested[index]]));
        const groups = byType.group || this.groups;
        const characters = byType.character || this.characters;
        const featureTags = byType.feature_tag || this.featureTags;
        this.setData({ groups, characters, featureTags });
    }

    option(item, type, selected) {
        return `
            <label class="tag-picker-option ${selected ? 'selected' : ''}">
                <input type="${type === 'group' ? 'radio' : 'checkbox'}" name="picker-${this.container.id}-${type}" value="${item.id}" ${selected ? 'checked' : ''}>
                <span>${this.escapeHTML(item.name)}</span>
                <small>${type === 'group' ? '分组' : type === 'character' ? '角色' : '特征'}</small>
            </label>
        `;
    }

    filterItems(items, query) {
        if (!query) return items;
        return window.PinyinSearch.filter(items, query, 'name');
    }

    async openPicker() {
        await this.refreshData();
        const modalId = `tag-picker-${this.container.id}`;
        this.pickerState = { ...structuredClone(this.getValue()), groupId: this.selected.group_ids[0] || null };
        const createButton = (method, label) => this.allowCreate ? `<button type="button" class="btn-link" onclick="window.imageTagSelectors['${this.container.id}'].createInPicker('${method}')">新建${label}</button>` : '';
        const isNested = Boolean(this.container && this.container.closest('#modal-body') && document.getElementById('modal-overlay')?.style.display !== 'none');
        const sections = [
            this.allowedTypes.includes('group') ? `
                    <section>
                        <h4>分组${createButton('showCreateGroupModal', '分组')}</h4>
                        <div class="tag-picker-list" data-type="group"></div>
                    </section>` : '',
            this.allowedTypes.includes('character') ? `
                    <section>
                        <h4>角色${createButton('showCreateCharacterModal', '角色')}</h4>
                        <div class="tag-picker-list" data-type="character"></div>
                    </section>` : '',
            this.allowedTypes.includes('feature_tag') ? `
                    <section>
                        <h4>特征${createButton('showCreateFeatureTagModal', '特征')}</h4>
                        <div class="tag-picker-list" data-type="feature_tag"></div>
                    </section>` : ''
        ].filter(Boolean).join('');
        const placeholder = this.allowedTypes.length === 1 && this.allowedTypes[0] === 'feature_tag'
            ? '搜索特征标签'
            : '搜索分组、角色或特征';
        const content = `
            <div class="tag-picker" id="${modalId}" data-selector-owner="${this.container.id}">
                <input class="form-input tag-picker-search" placeholder="${placeholder}" autocomplete="off">
                <div class="tag-picker-columns tag-picker-columns-${this.allowedTypes.length}">
                    ${sections}
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="button" class="btn btn-primary" onclick="window.imageTagSelectors['${this.container.id}'].confirmPicker('${modalId}')">添加</button>
                </div>
            </div>
        `;
        ui.showModal(this.title, content, isNested);
        this.renderPicker(modalId);
        const search = document.querySelector(`#${modalId} .tag-picker-search`);
        search.addEventListener('input', () => {
            window.clearTimeout(this.searchTimer);
            this.searchTimer = window.setTimeout(() => this.renderPicker(modalId, search.value), 90);
        });
        document.getElementById(modalId).addEventListener('change', event => {
            const type = event.target.closest('[data-type]')?.dataset.type;
            if (!type || event.target.tagName !== 'INPUT') return;
            const id = Number(event.target.value);
            if (type === 'group') {
                this.pickerState.groupId = id;
                this.renderPicker(modalId, search.value, ['character']);
                document.querySelectorAll(`#${modalId} [data-type="group"] label`).forEach(label => label.classList.toggle('selected', label.querySelector('input').checked));
            } else {
                const key = `${type}_ids`;
                this.pickerState[key] = this.pickerState[key].filter(value => value !== id);
                if (event.target.checked) this.pickerState[key].push(id);
            }
            event.target.closest('label')?.classList.toggle('selected', event.target.checked);
        });
    }

    async createInPicker(method) {
        if (!this.allowCreate || !['showCreateGroupModal', 'showCreateCharacterModal', 'showCreateFeatureTagModal'].includes(method)) return;
        await ui[method](true);
        if (method === 'showCreateCharacterModal' && this.pickerState.groupId) {
            const group = document.getElementById('character-group');
            if (group && Array.from(group.options).some(option => Number(option.value) === this.pickerState.groupId)) group.value = String(this.pickerState.groupId);
        }
    }

    renderPicker(modalId, query = '', sections = null) {
        const root = document.getElementById(modalId);
        if (!root) return;
        const shouldRender = type => !sections || sections.includes(type);
        const selectedGroupId = this.pickerState.groupId;
        const groups = this.filterItems(this.groups, query);
        const charactersSource = selectedGroupId ? this.characters.filter(c => c.group_id === selectedGroupId) : this.characters;
        const characters = this.filterItems(charactersSource, query);
        const featureTags = this.filterItems(this.featureTags, query);
        const groupList = root.querySelector('[data-type="group"]');
        const characterList = root.querySelector('[data-type="character"]');
        const featureList = root.querySelector('[data-type="feature_tag"]');
        if (groupList && shouldRender('group')) groupList.innerHTML = groups.map(item => this.option(item, 'group', item.id === selectedGroupId)).join('');
        if (characterList && shouldRender('character')) characterList.innerHTML = characters.map(item => this.option(item, 'character', this.pickerState.character_ids.includes(item.id))).join('');
        if (featureList && shouldRender('feature_tag')) featureList.innerHTML = featureTags.map(item => this.option(item, 'feature_tag', this.pickerState.feature_tag_ids.includes(item.id))).join('');
    }

    confirmPicker(modalId) {
        if (!document.getElementById(modalId)) return;
        if (this.pickerState.groupId) this.addUnique('group_ids', [this.pickerState.groupId]);
        for (const key of ['group_ids', 'character_ids', 'feature_tag_ids']) this.addUnique(key, this.pickerState[key]);
        this.notify();
        ui.closeModal();
    }
}

window.imageTagSelectors = window.imageTagSelectors || {};
