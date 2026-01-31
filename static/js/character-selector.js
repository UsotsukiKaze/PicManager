// 角色标签选择器
class CharacterSelector {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.selectedCharacters = [];
        this.availableCharacters = [];
        this.onChangeCallback = options.onChange || null;
        
        this.render();
        this.initEventListeners();
    }
    
    render() {
        this.container.innerHTML = `
            <div class="character-tags-container">
                <div class="character-tags" id="${this.container.id}-tags"></div>
                <div class="character-selector">
                    <input type="text" 
                           class="character-search-input" 
                           id="${this.container.id}-search"
                           placeholder="搜索并选择角色 (支持拼音首字母)">
                    <div class="character-dropdown" id="${this.container.id}-dropdown"></div>
                </div>
            </div>
        `;
    }
    
    initEventListeners() {
        const searchInput = document.getElementById(`${this.container.id}-search`);
        const dropdown = document.getElementById(`${this.container.id}-dropdown`);
        
        // 搜索输入
        searchInput.addEventListener('input', (e) => {
            this.filterCharacters(e.target.value);
        });
        
        // 获得焦点时显示下拉框
        searchInput.addEventListener('focus', () => {
            this.filterCharacters(searchInput.value);
        });
        
        // 点击外部关闭下拉框
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });
    }
    
    setCharacters(characters) {
        this.availableCharacters = characters;
        this.updateDropdown();
    }
    
    filterCharacters(query) {
        const dropdown = document.getElementById(`${this.container.id}-dropdown`);
        
        let filtered = this.availableCharacters;
        if (query) {
            const q = query.toLowerCase();
            let nameMatched = this.availableCharacters;
            if (window.PinyinSearch) {
                nameMatched = window.PinyinSearch.filter(this.availableCharacters, query, 'name');
            }
            const nameIds = new Set(nameMatched.map(item => item.id));
            filtered = this.availableCharacters.filter(char => {
                const nicknames = Array.isArray(char.nicknames) ? char.nicknames : [];
                const nicknameMatched = nicknames.some(item => String(item).toLowerCase().includes(q));
                return nameIds.has(char.id) || nicknameMatched;
            });
        }
        
        // 过滤掉已选择的角色
        const selectedIds = this.selectedCharacters.map(c => c.id);
        filtered = filtered.filter(c => !selectedIds.includes(c.id));
        
        if (filtered.length === 0) {
            dropdown.innerHTML = '<div class="character-option disabled">无匹配角色</div>';
        } else {
            dropdown.innerHTML = filtered.map(char => {
                const nicknameText = Array.isArray(char.nicknames) && char.nicknames.length
                    ? `（${char.nicknames.join(' / ')}）`
                    : '';
                return `
                    <div class="character-option" data-id="${char.id}" data-name="${char.name}">
                        ${char.name}${nicknameText}
                    </div>
                `;
            }).join('');
            
            // 添加点击事件
            dropdown.querySelectorAll('.character-option:not(.disabled)').forEach(option => {
                option.addEventListener('click', () => {
                    this.selectCharacter({
                        id: parseInt(option.dataset.id),
                        name: option.dataset.name
                    });
                });
            });
        }
        
        dropdown.classList.add('show');
    }
    
    updateDropdown() {
        const searchInput = document.getElementById(`${this.container.id}-search`);
        if (searchInput === document.activeElement) {
            this.filterCharacters(searchInput.value);
        }
    }
    
    selectCharacter(character) {
        if (this.selectedCharacters.find(c => c.id === character.id)) {
            return; // 已选择
        }
        
        this.selectedCharacters.push(character);
        this.renderTags();
        
        // 清空搜索框并更新下拉框
        const searchInput = document.getElementById(`${this.container.id}-search`);
        searchInput.value = '';
        this.updateDropdown();
        
        if (this.onChangeCallback) {
            this.onChangeCallback(this.getSelectedIds());
        }
    }
    
    removeCharacter(characterId) {
        this.selectedCharacters = this.selectedCharacters.filter(c => c.id !== characterId);
        this.renderTags();
        this.updateDropdown();
        
        if (this.onChangeCallback) {
            this.onChangeCallback(this.getSelectedIds());
        }
    }
    
    renderTags() {
        const tagsContainer = document.getElementById(`${this.container.id}-tags`);
        
        if (this.selectedCharacters.length === 0) {
            tagsContainer.innerHTML = '<div style="color: var(--text-tertiary); font-size: 14px;">暂无选择角色</div>';
            return;
        }
        
        tagsContainer.innerHTML = this.selectedCharacters.map(char => `
            <div class="character-tag">
                <span>${char.name}${Array.isArray(char.nicknames) && char.nicknames.length ? `（${char.nicknames.join(' / ')}）` : ''}</span>
                <span class="character-tag-remove" onclick="window.characterSelectors['${this.container.id}'].removeCharacter(${char.id})">×</span>
            </div>
        `).join('');
    }
    
    getSelectedIds() {
        return this.selectedCharacters.map(c => c.id);
    }
    
    /**
     * 通过ID选择角色（用于自动选中）
     */
    selectCharacterById(characterId) {
        const character = this.availableCharacters.find(c => c.id === characterId);
        if (character) {
            this.selectCharacter(character);
        }
    }
    
    clear() {
        this.selectedCharacters = [];
        this.renderTags();
        
        if (this.onChangeCallback) {
            this.onChangeCallback(this.getSelectedIds());
        }
    }
}

// 全局存储选择器实例
window.characterSelectors = window.characterSelectors || {};
