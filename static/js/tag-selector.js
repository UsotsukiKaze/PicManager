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
        this.selected[key] = (this.selected[key] || []).filter(item => item !== id);
        this.notify();
    }

    getLabel(type, id) {
        const source = type === 'group' ? this.groups : type === 'character' ? this.characters : this.featureTags;
        return (source.find(item => item.id === id) || {}).name || id;
    }

    renderTag(type, id) {
        const labelMap = { group: '分组', character: '角色', feature_tag: '特征' };
        return `
            <button type="button" class="pm-tag pm-tag-${type}" onclick="window.imageTagSelectors['${this.container.id}'].remove('${type}', ${id})">
                <span>${this.getLabel(type, id)}</span>
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
                <button type="button" class="pm-tag-add" onclick="window.imageTagSelectors['${this.container.id}'].openPicker()">+</button>
            </div>
        `;
    }

    async refreshData() {
        const [groups, characters, featureTags] = await Promise.all([
            api.getGroups(),
            api.getCharacters(),
            api.getFeatureTags()
        ]);
        this.setData({ groups, characters, featureTags });
    }

    option(item, type, selected) {
        return `
            <label class="tag-picker-option ${selected ? 'selected' : ''}">
                <input type="${type === 'group' ? 'radio' : 'checkbox'}" name="picker-${this.container.id}-${type}" value="${item.id}" ${selected ? 'checked' : ''}>
                <span>${item.name}</span>
                <small>${type === 'group' ? '分组' : type === 'character' ? '角色' : '特征'}</small>
            </label>
        `;
    }

    filterItems(items, query) {
        if (!query) return items;
        const q = query.toLowerCase();
        const directMatches = items.filter(item => {
            const aliases = Array.isArray(item.aliases) ? item.aliases : [];
            return String(item.name).toLowerCase().includes(q)
                || aliases.some(alias => String(alias).toLowerCase().includes(q));
        });
        if (!window.PinyinSearch) return directMatches;
        const pinyinMatches = window.PinyinSearch.filter(items, query, 'name');
        return Array.from(new Map([...directMatches, ...pinyinMatches].map(item => [item.id, item])).values());
    }

    async openPicker() {
        await this.refreshData();
        const modalId = `tag-picker-${this.container.id}`;
        const isNested = Boolean(this.container && this.container.closest('#modal-body') && document.getElementById('modal-overlay')?.style.display !== 'none');
        const sections = [
            this.allowedTypes.includes('group') ? `
                    <section>
                        <h4>分组</h4>
                        <div class="tag-picker-list" data-type="group"></div>
                    </section>` : '',
            this.allowedTypes.includes('character') ? `
                    <section>
                        <h4>角色</h4>
                        <div class="tag-picker-list" data-type="character"></div>
                    </section>` : '',
            this.allowedTypes.includes('feature_tag') ? `
                    <section>
                        <h4>特征</h4>
                        <div class="tag-picker-list" data-type="feature_tag"></div>
                    </section>` : ''
        ].filter(Boolean).join('');
        const placeholder = this.allowedTypes.length === 1 && this.allowedTypes[0] === 'feature_tag'
            ? '搜索特征标签'
            : '搜索分组、角色或特征';
        const content = `
            <div class="tag-picker" id="${modalId}">
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
        search.addEventListener('input', () => this.renderPicker(modalId, search.value));
        const groupList = document.querySelector(`#${modalId} [data-type="group"]`);
        if (groupList) groupList.addEventListener('change', () => this.renderPicker(modalId, search.value));
    }

    renderPicker(modalId, query = '') {
        const root = document.getElementById(modalId);
        if (!root) return;
        const selectedGroupInput = root.querySelector('[data-type="group"] input:checked');
        const selectedGroupId = selectedGroupInput ? Number(selectedGroupInput.value) : null;
        const groups = this.filterItems(this.groups, query);
        const charactersSource = selectedGroupId ? this.characters.filter(c => c.group_id === selectedGroupId) : this.characters;
        const characters = this.filterItems(charactersSource, query);
        const featureTags = this.filterItems(this.featureTags, query);
        const groupList = root.querySelector('[data-type="group"]');
        const characterList = root.querySelector('[data-type="character"]');
        const featureList = root.querySelector('[data-type="feature_tag"]');
        if (groupList) groupList.innerHTML = groups.map(item => this.option(item, 'group', selectedGroupId ? item.id === selectedGroupId : this.selected.group_ids.includes(item.id))).join('');
        if (characterList) characterList.innerHTML = characters.map(item => this.option(item, 'character', this.selected.character_ids.includes(item.id))).join('');
        if (featureList) featureList.innerHTML = featureTags.map(item => this.option(item, 'feature_tag', this.selected.feature_tag_ids.includes(item.id))).join('');
    }

    confirmPicker(modalId) {
        const root = document.getElementById(modalId);
        const group = root.querySelector('[data-type="group"] input:checked');
        const characters = Array.from(root.querySelectorAll('[data-type="character"] input:checked')).map(input => Number(input.value));
        const featureTags = Array.from(root.querySelectorAll('[data-type="feature_tag"] input:checked')).map(input => Number(input.value));
        if (group) this.addUnique('group_ids', [Number(group.value)]);
        this.addUnique('character_ids', characters);
        this.addUnique('feature_tag_ids', featureTags);
        this.notify();
        ui.closeModal();
    }
}

window.imageTagSelectors = window.imageTagSelectors || {};
