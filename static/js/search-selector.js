(function () {
    'use strict';

    class SearchSelectorModule {
    async updateSearchOptions() {
        // 强制刷新并更新搜索选项
        this.invalidateCache('groups');
        this.invalidateCache('characters');
        
        await Promise.all([
            this.loadGroupsData(true),
            this.loadCharactersData(true),
            this.loadFeatureTagsData(true)
        ]);
        
        // 重新渲染下拉选项
        this.renderGroupDropdown();
        this.renderCharacterDropdown();
        this.renderCharacterGroupFilterDropdown();
    }

    async loadImageSearchOptions() {
        // Keep the image list and its filters independent: images can render
        // immediately while the reusable group/character collections load in
        // parallel. This also makes the first visit to the image tab complete,
        // without relying on a prior visit to either management tab.
        this.initializeSearchSelectors();
        const [groups, characters] = await Promise.all([
            this.loadGroupsData(),
            this.loadCharactersData()
        ]);

        this.allGroups = groups;
        this.allCharacters = characters;
        this.filteredCharacters = characters;
        this.renderGroupDropdown();
        this.renderCharacterDropdown();
    }
    
    /**
     * 初始化可搜索的选择器
     */
    initializeSearchSelectors() {
        // 分组搜索选择器
        this.initSearchableSelect({
            containerId: 'search-group-container',
            inputId: 'search-group-input',
            hiddenId: 'search-group',
            dropdownId: 'search-group-dropdown',
            getData: () => this.allGroups || [],
            renderOption: (item) => `<div class="option-main">${this.escapeHomeRankingText(item.name)}</div>`,
            onSelect: (item) => {
                // 选择分组后更新角色列表
                this.filterCharactersByGroup(item ? item.id : null);
            },
            allOptionText: '全部分组'
        });
        
        // 角色搜索选择器
        this.initSearchableSelect({
            containerId: 'search-character-container',
            inputId: 'search-character-input',
            hiddenId: 'search-character',
            dropdownId: 'search-character-dropdown',
            getData: () => this.filteredCharacters || this.allCharacters || [],
            renderOption: (item) => `
                <div class="option-main">${this.escapeHomeRankingText(item.name)}</div>
                <div class="option-sub">${this.escapeHomeRankingText(item.group_name || '')}</div>
            `,
            onSelect: null,
            allOptionText: '全部角色'
        });
        
        // 初始渲染
        this.renderGroupDropdown();
        this.renderCharacterDropdown();
    }
    
    /**
     * 初始化单个可搜索选择器
     */
    initSearchableSelect(config) {
        const input = document.getElementById(config.inputId);
        const hidden = document.getElementById(config.hiddenId);
        const dropdown = document.getElementById(config.dropdownId);
        
        if (!input || !dropdown) return;
        
        // 存储配置
        input._config = config;

        // Page/tab switches may initialize the same control repeatedly. Keep
        // one set of listeners and let them read the latest configuration.
        if (input._searchableSelectInitialized) return;
        input._searchableSelectInitialized = true;
        
        // 输入事件：过滤选项
        input.addEventListener('input', () => {
            this.filterSearchableOptions(input._config);
            dropdown.classList.add('show');
        });
        
        // 聚焦事件：显示下拉
        input.addEventListener('focus', () => {
            this.filterSearchableOptions(input._config);
            dropdown.classList.add('show');
        });
        
        // 失焦事件：延迟隐藏（允许点击选项）
        input.addEventListener('blur', () => {
            setTimeout(() => dropdown.classList.remove('show'), 200);
        });
        
        // 点击选项
        dropdown.addEventListener('click', (e) => {
            const option = e.target.closest('.searchable-option');
            if (option) {
                const value = option.dataset.value;
                const text = option.dataset.text;
                
                input.value = text;
                hidden.value = value;
                dropdown.classList.remove('show');
                window.queryPanels?.updateForField(hidden);
                
                const currentConfig = input._config;
                if (currentConfig.onSelect) {
                    const item = value ? currentConfig.getData().find(i => String(i.id) === value) : null;
                    currentConfig.onSelect(item);
                }
            }
        });
    }
    
    /**
     * 过滤可搜索选项
     */
    filterSearchableOptions(config) {
        const input = document.getElementById(config.inputId);
        const dropdown = document.getElementById(config.dropdownId);
        const query = input.value.trim();
        const data = config.getData();
        
        let filtered = data;
        if (query && window.PinyinSearch) {
            filtered = window.PinyinSearch.filter(data, query, 'name');
        }
        
        // 渲染选项
        let html = `<div class="searchable-option" data-value="" data-text="${this.escapeHomeRankingText(config.allOptionText)}">
            <div class="option-main">${this.escapeHomeRankingText(config.allOptionText)}</div>
        </div>`;
        
        filtered.forEach(item => {
            html += `<div class="searchable-option" data-value="${Number(item.id)}" data-text="${this.escapeHomeRankingText(item.name)}">
                ${config.renderOption(item)}
            </div>`;
        });
        
        dropdown.innerHTML = html;
    }
    
    /**
     * 渲染分组下拉选项
     */
    renderGroupDropdown() {
        const config = document.getElementById('search-group-input')?._config;
        if (config) {
            this.filterSearchableOptions(config);
        }
    }
    
    /**
     * 渲染角色下拉选项
     */
    renderCharacterDropdown() {
        const config = document.getElementById('search-character-input')?._config;
        if (config) {
            this.filterSearchableOptions(config);
        }
    }
    
    /**
     * 根据分组过滤角色
     */
    async filterCharactersByGroup(groupId) {
        if (groupId) {
            this.filteredCharacters = await api.getCharacters(groupId);
        } else {
            this.filteredCharacters = this.allCharacters;
        }
        
        // 清空角色选择
        document.getElementById('search-character-input').value = '';
        document.getElementById('search-character').value = '';
        
        this.renderCharacterDropdown();
    }
    }

    window.PicManagerUIModules = window.PicManagerUIModules || [];
    window.PicManagerUIModules.push(SearchSelectorModule);
})();
