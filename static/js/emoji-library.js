class EmojiLibrary {
    constructor() {
        this.groups = [];
        this.characters = [];
        this.emotions = [];
        this.initialized = false;
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null };
        this.uploadPickerDraft = null;
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

    async loadOptions() {
        const [groups, characters, emotions] = await Promise.all([
            api.getGroups(),
            api.getCharacters(),
            api.getEmotionTags(),
        ]);
        this.groups = groups || [];
        this.characters = characters || [];
        this.emotions = emotions || [];

        const groupFilter = document.getElementById('emoji-group-filter');
        const characterFilter = document.getElementById('emoji-character-filter');
        const emotionFilter = document.getElementById('emoji-emotion-filter');
        if (groupFilter) groupFilter.innerHTML = this.optionHtml(this.groups, '全部分组');
        if (characterFilter) characterFilter.innerHTML = this.optionHtml(this.characters, '全部角色');
        if (emotionFilter) emotionFilter.innerHTML = this.optionHtml(this.emotions, '全部情绪');

        this.renderUploadTagControls();
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
            limit: 100,
            offset: 0,
        };
        const result = await api.searchEmojis(params);
        this.renderGrid(result.emojis || []);
        this.renderEmotions();
    }

    formatEmojiTags(emoji) {
        const group = (emoji.groups || [])[0];
        const character = (emoji.characters || [])[0];
        return [group?.name, character?.name].filter(Boolean).join('-') || '未添加分组或角色';
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
                <div class="image-card emoji-card" data-emoji-id="${this.escape(emoji.emoji_id)}">
                    <div class="image-card-media">
                        <img class="image-card-img emoji-card-img"
                             src="/${this.escape(emoji.file_path)}"
                             loading="lazy"
                             decoding="async"
                             alt="emoji ${this.escape(emoji.emoji_id)}">
                    </div>
                    <div class="image-card-info">
                        <div class="image-card-id">${this.escape(emoji.emoji_id)}</div>
                        <div class="image-card-characters">${this.escape(this.formatEmojiTags(emoji))}</div>
                        <div class="image-card-pid">${this.escape(emotion)}</div>
                        <div class="emoji-card-actions">
                            <button class="action-btn delete" onclick="event.stopPropagation(); emojiLibrary.deleteEmoji('${this.escape(emoji.emoji_id)}')">删除</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
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
        this.uploadTags = { group_id: null, character_id: null, emotion_id: null };
        ui.showModal('上传GIF表情', `
            <div class="form-group">
                <label>GIF文件</label>
                <input type="file" id="emoji-file-input" class="form-input" accept="image/gif">
            </div>
            <div class="form-group">
                <div id="emoji-upload-tag-selector"></div>
            </div>
            <div class="form-group">
                <label>备注</label>
                <textarea id="emoji-description" class="form-textarea" placeholder="可不填"></textarea>
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                <button class="btn btn-primary" onclick="emojiLibrary.upload()">上传</button>
            </div>
        `);
        this.renderUploadTagControls();
    }

    async upload() {
        const input = document.getElementById('emoji-file-input');
        const file = input?.files?.[0];
        if (!file) {
            ui.showToast('请选择 GIF 文件', 'warning');
            return;
        }
        if (!file.name.toLowerCase().endsWith('.gif')) {
            ui.showToast('表情包库暂只支持 GIF 动图', 'warning');
            return;
        }
        await api.uploadEmoji(file, {
            group_ids: this.uploadTags.group_id ? [this.uploadTags.group_id] : [],
            character_ids: this.uploadTags.character_id ? [this.uploadTags.character_id] : [],
            emotion_ids: this.uploadTags.emotion_id ? [this.uploadTags.emotion_id] : [],
            description: document.getElementById('emoji-description')?.value || '',
        });
        ui.closeModal();
        ui.showToast('表情包已上传', 'success');
        await this.load();
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
        ui.showToast('表情包已删除', 'success');
        await this.load();
    }
}

window.emojiLibrary = new EmojiLibrary();
