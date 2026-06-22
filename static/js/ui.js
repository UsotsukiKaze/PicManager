// UI 管理类
class UIManager {
    constructor() {
        this.currentPage = 'home';
        this.currentTab = null;
        this.pagination = {
            currentPage: 1,
            totalPages: 1,
            limit: 20,
            maxButtons: 11
        };
        this.activeImageSearchParams = {};
        
        // 存储所有分组和角色数据用于搜索
        this.allGroups = [];
        this.allCharacters = [];
        
        // 模态框状态管理
        this.modalStack = [];
        this.isNestedModal = false;
        
        // 数据缓存和加载状态
        this.dataCache = {
            groups: { data: null, timestamp: 0 },
            characters: { data: null, timestamp: 0 },
            images: { data: null, timestamp: 0, params: null }
        };
        this.cacheTimeout = 30000; // 缓存有效期30秒
        this.loadingStates = {}; // 防止重复加载
        this.thumbnailMaintenanceQueued = false;
        this.lastThumbnailMaintenanceAt = 0;
        
        this.initializeEventListeners();
    }
    
    /**
     * 检查缓存是否有效
     */
    isCacheValid(key, params = null) {
        const cache = this.dataCache[key];
        if (!cache || !cache.data) return false;
        if (Date.now() - cache.timestamp > this.cacheTimeout) return false;
        if (params && JSON.stringify(cache.params) !== JSON.stringify(params)) return false;
        return true;
    }
    
    /**
     * 更新缓存
     */
    updateCache(key, data, params = null) {
        this.dataCache[key] = { data, timestamp: Date.now(), params };
    }
    
    /**
     * 使缓存失效
     */
    invalidateCache(key = null) {
        if (key) {
            this.dataCache[key] = { data: null, timestamp: 0, params: null };
        } else {
            Object.keys(this.dataCache).forEach(k => {
                this.dataCache[k] = { data: null, timestamp: 0, params: null };
            });
        }
    }

    initializeEventListeners() {
        // 页面导航 - 使用closest确保点击响应
        document.addEventListener('click', (e) => {
            const menuItem = e.target.closest('.menu-item');
            if (menuItem) {
                e.preventDefault();
                e.stopPropagation();
                const page = menuItem.getAttribute('data-page');
                if (page) {
                    this.switchPage(page);
                }
            }
        });

        window.addEventListener('resize', () => this.updateSidebarIndicator());

        // 标签页切换 - 使用事件委托和closest来确保点击响应
        document.addEventListener('click', (e) => {
            const tabBtn = e.target.closest('.tab-btn');
            if (tabBtn) {
                e.preventDefault();
                const tab = tabBtn.getAttribute('data-tab');
                if (tab) {
                    this.switchTab(tab);
                }
            }
        });

        // 模态框关闭
        document.addEventListener('click', (e) => {
            if (e.target.id === 'modal-overlay' && !this.isNestedModal) {
                this.closeModal();
            }
        });

        // ESC 键关闭模态框
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.isNestedModal) {
                this.closeModal();
            }
        });
        
        // 分组搜索监听
        document.addEventListener('input', (e) => {
            if (e.target.id === 'group-search-input') {
                this.filterGroups(e.target.value);
            }
        });
        
        // 角色搜索监听
        document.addEventListener('input', (e) => {
            if (e.target.id === 'character-search-input') {
                this.filterCharacters(e.target.value);
            }
        });

        // 榜单标签切换
        document.addEventListener('click', (e) => {
            const tab = e.target.closest('.leaderboard-tab');
            if (!tab) return;
            const board = tab.getAttribute('data-board');
            if (!board) return;
            this.switchLeaderboard(board);
        });
    }

    switchLeaderboard(board) {
        document.querySelectorAll('.leaderboard-tab').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.leaderboard-panel').forEach(panel => panel.classList.remove('active'));

        const activeTab = document.querySelector(`.leaderboard-tab[data-board="${board}"]`);
        if (activeTab) activeTab.classList.add('active');

        const panel = document.getElementById(`leaderboard-${board}`);
        if (panel) panel.classList.add('active');
    }

    switchPage(page) {
        // 如果切换的是当前页面则不操作
        if (this.currentPage === page && !this._forceSwitch) return;
        
        // 更新导航菜单
        document.querySelectorAll('.menu-item').forEach(item => {
            item.classList.remove('active');
        });
        const activeMenuItem = document.querySelector(`.menu-item[data-page="${page}"]`);
        if (activeMenuItem) activeMenuItem.classList.add('active');
        this.updateSidebarIndicator();

        // 切换页面内容
        document.querySelectorAll('.page-content').forEach(content => {
            content.style.display = 'none';
        });
        const targetPage = document.getElementById(`page-${page}`);
        if (!targetPage) return;
        targetPage.style.display = 'block';
        targetPage.classList.remove('page-enter');
        void targetPage.offsetWidth;
        targetPage.classList.add('page-enter');

        this.currentPage = page;
        
        // 重置到第一个标签页
        this.resetToFirstTab(page);

        // 页面切换后的处理
        this.handlePageSwitch(page);
    }

    updateSidebarIndicator() {
        const indicator = document.getElementById('menu-indicator');
        const menu = document.querySelector('.sidebar-menu');
        const active = document.querySelector('.sidebar-menu .menu-item.active');
        if (!indicator || !menu || !active) {
            if (indicator) indicator.style.opacity = '0';
            return;
        }

        const menuRect = menu.getBoundingClientRect();
        const activeRect = active.getBoundingClientRect();
        indicator.style.opacity = '1';
        indicator.style.width = `${activeRect.width}px`;
        indicator.style.height = `${activeRect.height}px`;
        indicator.style.transform = `translate(${activeRect.left - menuRect.left}px, ${activeRect.top - menuRect.top}px)`;
    }

    isAdminView() {
        return Boolean(window.auth && typeof window.auth.isAdmin === 'function' && window.auth.isAdmin());
    }

    applyRolePreferences() {
        if (!this.isAdminView()) {
            this.pagination.limit = 20;
        } else if (![20, 50, 100].includes(this.pagination.limit)) {
            this.pagination.limit = 50;
        }
    }
    
    /**
     * 重置到该页面的第一个标签页
     */
    resetToFirstTab(page) {
        const pageElement = document.getElementById(`page-${page}`);
        if (!pageElement) return;
        
        const tabButtons = pageElement.querySelectorAll('.tab-btn');
        const tabContents = pageElement.querySelectorAll('.tab-content');
        
        if (tabButtons.length === 0) return;
        
        // 重置所有标签页按钮
        tabButtons.forEach(btn => btn.classList.remove('active'));
        tabContents.forEach(content => content.style.display = 'none');
        
        // 激活第一个标签页
        const firstTab = tabButtons[0];
        firstTab.classList.add('active');
        const firstTabName = firstTab.getAttribute('data-tab');
        const firstTabContent = document.getElementById(`tab-${firstTabName}`);
        if (firstTabContent) {
            firstTabContent.style.display = 'block';
        }
        // 先重置currentTab为null，确保handleTabSwitch能被触发
        this.currentTab = null;
        this.currentTab = firstTabName;
        
        // 触发标签页内容加载
        this.handleTabSwitch(firstTabName);
    }
    
    /**
     * 页面切换后的数据加载处理
     */
    handlePageSwitch(page) {
        switch (page) {
            case 'home':
                this.loadSystemStatus();
                this.loadHomeGroupChips();
                break;
            case 'management':
                this.applyRolePreferences();
                break;
            case 'upload':
                this.loadUploadData();
                break;
            case 'settings':
                this.loadSystemStatus();
                break;
            case 'rankings':
                this.loadRankings();
                break;
        }
    }

    switchTab(tab) {
        // 防止重复切换
        if (this.currentTab === tab) return;
        
        // 获取当前页面的标签页按钮
        const pageElement = document.getElementById(`page-${this.currentPage}`);
        if (!pageElement) {
            return;
        }
        
        const tabButtons = pageElement.querySelectorAll('.tab-btn');
        const tabContents = pageElement.querySelectorAll('.tab-content');
        
        // 更新标签页按钮
        tabButtons.forEach(btn => {
            btn.classList.remove('active');
            if (btn.getAttribute('data-tab') === tab) {
                btn.classList.add('active');
            }
        });

        // 切换标签页内容
        tabContents.forEach(content => {
            content.style.display = 'none';
        });
        
        const targetContent = document.getElementById(`tab-${tab}`);
        if (targetContent) {
            targetContent.style.display = 'block';
            targetContent.classList.remove('tab-enter');
            void targetContent.offsetWidth;
            targetContent.classList.add('tab-enter');
        }

        this.currentTab = tab;

        // 标签页切换后的处理
        this.handleTabSwitch(tab);
    }

    handleTabSwitch(tab) {
        switch (tab) {
            case 'image-list':
                this.loadImages();
                this.initializeSearchSelectors();
                break;
            case 'group-management':
                this.loadGroups();
                break;
            case 'character-management':
                this.loadCharacters();
                break;
            case 'temp-upload':
                // 调用upload对象的loadTempImages方法
                if (window.upload) {
                    upload.loadTempImages();
                }
                break;
        }
    }

    async loadManagementData() {
        // 并行加载数据，提高速度
        const [groups, characters] = await Promise.all([
            this.loadGroupsData(),
            this.loadCharactersData()
        ]);
        
        // 渲染UI
        this.renderGroupList(groups);
        this.renderCharacterList(characters);
        
        // 加载图片列表
        await this.loadImages();
        
        // 更新搜索选项
        this.renderGroupDropdown();
        this.renderCharacterDropdown();
    }

    async loadUploadData() {
        // 并行加载数据
        await Promise.all([
            this.loadGroupsData(),
            this.loadCharactersData()
        ]);
        
        await this.updateUploadOptions();
        await this.updateTempCount();
    }
    
    /**
     * 加载分组数据（带缓存）
     */
    async loadGroupsData(forceRefresh = false) {
        if (!forceRefresh && this.isCacheValid('groups')) {
            this.allGroups = this.dataCache.groups.data;
            return this.allGroups;
        }
        
        try {
            const groups = await api.getGroups();
            this.allGroups = groups;
            this.updateCache('groups', groups);
            
            // 学习拼音
            if (window.PinyinSearch) {
                window.PinyinSearch.learnWords(groups.map(g => g.name));
            }
            
            return groups;
        } catch (error) {
            this.showToast('加载分组失败', 'error');
            return this.allGroups || [];
        }
    }
    
    /**
     * 加载角色数据（带缓存）
     */
    async loadCharactersData(forceRefresh = false) {
        if (!forceRefresh && this.isCacheValid('characters')) {
            this.allCharacters = this.dataCache.characters.data;
            return this.allCharacters;
        }
        
        try {
            const characters = await api.getCharacters();
            this.allCharacters = characters;
            this.updateCache('characters', characters);
            
            // 学习拼音
            if (window.PinyinSearch) {
                window.PinyinSearch.learnWords(characters.map(c => c.name));
            }
            
            return characters;
        } catch (error) {
            this.showToast('加载角色失败', 'error');
            return this.allCharacters || [];
        }
    }

    async updateSearchOptions() {
        // 强制刷新并更新搜索选项
        this.invalidateCache('groups');
        this.invalidateCache('characters');
        
        await Promise.all([
            this.loadGroupsData(true),
            this.loadCharactersData(true)
        ]);
        
        // 重新渲染下拉选项
        this.renderGroupDropdown();
        this.renderCharacterDropdown();
        this.renderCharacterGroupFilterDropdown();
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
            renderOption: (item) => `<div class="option-main">${item.name}</div>`,
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
                <div class="option-main">${item.name}</div>
                <div class="option-sub">${item.group_name || ''}</div>
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
        
        // 输入事件：过滤选项
        input.addEventListener('input', () => {
            this.filterSearchableOptions(config);
            dropdown.classList.add('show');
        });
        
        // 聚焦事件：显示下拉
        input.addEventListener('focus', () => {
            this.filterSearchableOptions(config);
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
                
                if (config.onSelect) {
                    const item = value ? config.getData().find(i => String(i.id) === value) : null;
                    config.onSelect(item);
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
        let html = `<div class="searchable-option" data-value="" data-text="${config.allOptionText}">
            <div class="option-main">${config.allOptionText}</div>
        </div>`;
        
        filtered.forEach(item => {
            html += `<div class="searchable-option" data-value="${item.id}" data-text="${item.name}">
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

    async updateUploadOptions() {
        try {
            const groups = await api.getGroups();
            const characters = await api.getCharacters();

            // 更新单张上传的分组选择器
            const singleGroupSelect = document.getElementById('single-group-select');
            singleGroupSelect.innerHTML = '<option value="">先选分组</option>';
            groups.forEach(group => {
                singleGroupSelect.innerHTML += `<option value="${group.id}">${group.name}</option>`;
            });

            // 监听分组变化，更新角色选项（覆盖式，避免重复绑定）
            singleGroupSelect.onchange = async () => {
                const groupId = singleGroupSelect.value;
                
                if (groupId) {
                    const filteredCharacters = await api.getCharacters(parseInt(groupId));
                    // 更新角色标签选择器
                    if (upload.singleCharacterSelector) {
                        upload.singleCharacterSelector.setCharacters(filteredCharacters);
                    }
                } else {
                    if (upload.singleCharacterSelector) {
                        upload.singleCharacterSelector.setCharacters([]);
                    }
                }
            };
        } catch (error) {
            this.showToast('加载上传选项失败', 'error');
        }
    }

    async loadImages(params = undefined) {
        try {
            this.applyRolePreferences();
            if (params !== undefined && params !== null) {
                this.activeImageSearchParams = { ...params };
            }

            const searchParams = {
                ...(this.activeImageSearchParams || {}),
                limit: this.pagination.limit,
                offset: (this.pagination.currentPage - 1) * this.pagination.limit
            };

            const result = await api.searchImages(searchParams);
            const totalPages = Math.max(1, Math.ceil((result.total || 0) / this.pagination.limit));
            if ((result.images || []).length === 0 && (result.total || 0) > 0 && this.pagination.currentPage > totalPages) {
                this.pagination.currentPage = totalPages;
                return this.loadImages(null);
            }

            this.renderImageGrid(result.images || []);
            this.updatePagination(result);
        } catch (error) {
            this.showToast('加载图片失败', 'error');
        }
    }

    getImageFilename(image) {
        return `${image.image_id}.${image.file_extension}`;
    }

    getImagePath(image) {
        return (image.file_path || `resource/store/${this.getImageFilename(image)}`).replace(/^\/+/, '');
    }

    getImageUrl(image) {
        return `/${this.getImagePath(image)}`;
    }

    getThumbnailUrl(image) {
        return `/resource/thumbs/${image.image_id}.webp`;
    }

    handleImageFallback(img) {
        const fallback = img.dataset.fullSrc;
        if (fallback && img.src !== new URL(fallback, window.location.origin).href) {
            img.src = fallback;
            img.dataset.fullSrc = '';
            return;
        }
        img.onerror = null;
        img.src = '/static/images/placeholder.png';
    }

    renderImageGrid(images) {
        const grid = document.getElementById('image-grid');
        if (!grid) return;
        
        if (images.length === 0) {
            grid.innerHTML = '<div class="empty-state">未找到图片</div>';
            return;
        }

        grid.innerHTML = images.map(image => `
            <div class="image-card" data-image-id="${image.image_id}">
                <div class="image-card-media">
                    <img class="image-card-img" src="${this.getThumbnailUrl(image)}"
                         data-full-src="${this.getImageUrl(image)}"
                         alt="Image ${image.image_id}" loading="lazy" decoding="async"
                         onerror="ui.handleImageFallback(this)">
                </div>
                <div class="image-card-info">
                    <div class="image-card-id">${image.image_id}</div>
                    <div class="image-card-characters">
                        ${image.characters.map(char => {
                            const groupName = char.group_name || (char.group && char.group.name) || '未知分组';
                            return `${groupName} - ${char.name}`;
                        }).join(', ')}
                    </div>
                    ${image.pid ? `<div class="image-card-pid">PID: ${image.pid}</div>` : ''}
                </div>
            </div>
        `).join('');

        grid.querySelectorAll('.image-card').forEach(card => {
            card.addEventListener('click', () => {
                const imageId = card.getAttribute('data-image-id');
                this.showImageDetail(imageId);
            });
        });
    }

    buildPageWindow(totalPages, currentPage) {
        const maxButtons = Math.max(7, this.pagination.maxButtons || 11);
        if (totalPages <= maxButtons) {
            return Array.from({ length: totalPages }, (_, index) => index + 1);
        }

        const dynamicRadius = Math.min(4, Math.max(2, Math.floor(totalPages * 0.04)));
        let start = Math.max(2, currentPage - dynamicRadius);
        let end = Math.min(totalPages - 1, currentPage + dynamicRadius);
        const innerLimit = maxButtons - 2;

        while ((end - start + 1) < innerLimit && start > 2) start--;
        while ((end - start + 1) < innerLimit && end < totalPages - 1) end++;

        const pages = [1];
        if (start > 2) pages.push('gap-start');
        for (let page = start; page <= end; page++) pages.push(page);
        if (end < totalPages - 1) pages.push('gap-end');
        pages.push(totalPages);
        return pages;
    }

    updatePagination(result) {
        const total = result.total || 0;
        this.pagination.totalPages = Math.max(1, Math.ceil(total / this.pagination.limit));
        
        const paginationContainer = document.getElementById('pagination');
        if (!paginationContainer) return;
        if (this.pagination.totalPages <= 1 && total <= this.pagination.limit) {
            paginationContainer.innerHTML = '';
            return;
        }

        const pageItems = this.buildPageWindow(this.pagination.totalPages, this.pagination.currentPage);
        const isAdmin = this.isAdminView();
        let html = `
            <button class="pagination-btn pagination-edge" ${this.pagination.currentPage === 1 ? 'disabled' : ''} 
                    onclick="ui.changePage(1)">首页</button>
            <button class="pagination-btn" ${this.pagination.currentPage === 1 ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.currentPage - 1})">上一页</button>
        `;

        pageItems.forEach((item) => {
            if (typeof item === 'string') {
                html += '<span class="pagination-ellipsis">...</span>';
                return;
            }
            html += `
                <button class="pagination-btn ${item === this.pagination.currentPage ? 'active' : ''}" 
                        onclick="ui.changePage(${item})">${item}</button>
            `;
        });

        html += `
            <button class="pagination-btn" ${this.pagination.currentPage === this.pagination.totalPages ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.currentPage + 1})">下一页</button>
            <button class="pagination-btn pagination-edge" ${this.pagination.currentPage === this.pagination.totalPages ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.totalPages})">末页</button>
            <span class="pagination-summary">${this.pagination.currentPage} / ${this.pagination.totalPages} · ${total}</span>
            ${isAdmin ? `
                <select class="pagination-size" onchange="ui.changePageSize(this.value)" aria-label="每页数量">
                    ${[20, 50, 100].map(size => `<option value="${size}" ${size === this.pagination.limit ? 'selected' : ''}>${size}/页</option>`).join('')}
                </select>
            ` : '<span class="pagination-size locked">20/页</span>'}
            <span class="pagination-jump">
                <input class="pagination-input" id="pagination-jump-input" type="number" min="1" max="${this.pagination.totalPages}" value="${this.pagination.currentPage}" aria-label="跳转页码">
                <button class="pagination-btn" onclick="ui.jumpToPage()">跳转</button>
            </span>
        `;

        paginationContainer.innerHTML = html;
    }

    changePage(page) {
        if (page < 1 || page > this.pagination.totalPages) return;
        this.pagination.currentPage = page;
        this.loadImages(null);
    }

    changePageSize(value) {
        if (!this.isAdminView()) return;
        const nextLimit = parseInt(value, 10);
        if (!Number.isFinite(nextLimit) || ![20, 50, 100].includes(nextLimit) || nextLimit === this.pagination.limit) return;
        this.pagination.limit = nextLimit;
        this.pagination.currentPage = 1;
        this.loadImages(null);
    }

    jumpToPage() {
        const input = document.getElementById('pagination-jump-input');
        const page = parseInt(input?.value, 10);
        if (!Number.isFinite(page)) return;
        this.changePage(Math.min(Math.max(page, 1), this.pagination.totalPages));
    }
    getSearchParams() {
        return {
            group_id: document.getElementById('search-group').value || null,
            character_id: document.getElementById('search-character').value || null,
            pid: document.getElementById('search-pid').value || null
        };
    }

    async loadGroups() {
        const groups = await this.loadGroupsData();
        this.renderGroupList(groups);
    }
    
    filterGroups(query) {
        if (!window.PinyinSearch) {
            console.error('PinyinSearch not loaded');
            return;
        }
        const filtered = window.PinyinSearch.filter(this.allGroups, query, 'name');
        this.renderGroupList(filtered);
    }

    renderGroupList(groups) {
        const container = document.getElementById('group-list');
        
        if (groups.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无分组</div>';
            return;
        }

        container.innerHTML = groups.map(group => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">${group.name}</div>
                    <div class="list-item-description">${group.description || '无描述'}</div>
                </div>
                <div class="list-item-actions">
                    <button class="action-btn edit" onclick="ui.editGroup(${group.id})">编辑</button>
                    <button class="action-btn delete" onclick="ui.deleteGroup(${group.id})">删除</button>
                </div>
            </div>
        `).join('');
    }

    async loadCharacters() {
        const characters = await this.loadCharactersData();
        this.renderCharacterList(characters);
        
        // 初始化分组筛选器
        this.initializeCharacterGroupFilter();
    }

    async loadRankings() {
        try {
            console.log('开始加载榜单数据...');
            const data = await api.getRankings(10);
            console.log('榜单数据:', data);
            
            // 渲染各榜单
            this.renderContributionRankings(data.contribution || []);
            this.renderCharacterRankings(data.characters || []);
            this.renderImageRankings(data.images || []);
            console.log('榜单渲染完成');
        } catch (error) {
            console.error('加载榜单失败:', error);
            // 显示更详细的错误信息
            const errorMsg = error.message || '未知错误';
            this.showToast(`加载榜单失败: ${errorMsg}`, 'error');
        }
    }

    renderContributionRankings(items) {
        const container = document.getElementById('leaderboard-contribution-list');
        if (!container) return;

        if (!items.length) {
            container.innerHTML = '<div class="empty-state">暂无贡献数据</div>';
            return;
        }

        container.innerHTML = items.map((item, index) => {
            const avatar = item.avatar_url || `https://q1.qlogo.cn/g?b=qq&nk=${item.qq_number}&s=100`;
            return `
                <div class="leaderboard-item">
                    <div class="leaderboard-rank">${index + 1}</div>
                    <img class="leaderboard-avatar" src="${avatar}" alt="头像" onerror="this.style.display='none'">
                    <div class="leaderboard-info">
                        <div class="leaderboard-name">${item.nickname}</div>
                        <div class="leaderboard-sub">QQ: ${item.qq_number}</div>
                    </div>
                    <div class="leaderboard-score">${item.score}</div>
                </div>
            `;
        }).join('');
    }

    renderCharacterRankings(items) {
        const container = document.getElementById('leaderboard-characters-list');
        if (!container) return;

        if (!items.length) {
            container.innerHTML = '<div class="empty-state">暂无角色数据</div>';
            return;
        }

        container.innerHTML = items.map((item, index) => `
            <div class="leaderboard-item">
                <div class="leaderboard-rank">${index + 1}</div>
                <div class="leaderboard-info">
                    <div class="leaderboard-name">${item.name}</div>
                    <div class="leaderboard-sub">${item.group_name || '未分组'}</div>
                </div>
                <div class="leaderboard-score">${item.count}</div>
            </div>
        `).join('');
    }

    renderImageRankings(items) {
        const container = document.getElementById('leaderboard-images-list');
        if (!container) return;

        if (!items.length) {
            container.innerHTML = '<div class="empty-state">暂无图片数据</div>';
            return;
        }

        container.innerHTML = items.map((item, index) => `
            <div class="leaderboard-item">
                <div class="leaderboard-rank">${index + 1}</div>
                <img class="leaderboard-thumb" src="${this.getThumbnailUrl(item)}" data-full-src="${this.getImageUrl(item)}" alt="图片" onerror="ui.handleImageFallback(this)">
                <div class="leaderboard-info">
                    <div class="leaderboard-name">图片 ${item.image_id}</div>
                    <div class="leaderboard-sub">浏览次数</div>
                </div>
                <div class="leaderboard-score">${item.count}</div>
            </div>
        `).join('');
    }
    
    filterCharacters(query) {
        if (!window.PinyinSearch) {
            console.error('PinyinSearch not loaded');
            return;
        }
        
        // 获取当前分组筛选
        const selectedGroupId = document.getElementById('character-group-filter').value;
        
        // 先按分组筛选
        let filtered = this.allCharacters;
        if (selectedGroupId) {
            filtered = this.allCharacters.filter(c => c.group_id == selectedGroupId);
        }
        
        // 再按名称/昵称筛选
        if (query) {
            const nameMatched = window.PinyinSearch.filter(filtered, query, 'name');
            const nameIds = new Set(nameMatched.map(item => item.id));
            const q = query.toLowerCase();
            filtered = filtered.filter(item => {
                const nicknames = Array.isArray(item.nicknames) ? item.nicknames : [];
                const nicknameMatched = nicknames.some(nick => String(nick).toLowerCase().includes(q));
                return nameIds.has(item.id) || nicknameMatched;
            });
        }
        
        this.renderCharacterList(filtered);
    }
    
    /**
     * 初始化角色管理页面的分组筛选器
     */
    initializeCharacterGroupFilter() {
        this.initSearchableSelect({
            containerId: 'character-group-filter-container',
            inputId: 'character-group-filter-input',
            hiddenId: 'character-group-filter',
            dropdownId: 'character-group-filter-dropdown',
            getData: () => this.allGroups || [],
            renderOption: (item) => `<div class="option-main">${item.name}</div>`,
            onSelect: () => {
                // 分组选择变化时立即更新角色列表
                this.filterCharacters(document.getElementById('character-search-input').value);
            },
            allOptionText: '全部分组'
        });
        
        this.renderCharacterGroupFilterDropdown();
    }
    
    /**
     * 渲染角色管理页面的分组筛选下拉选项
     */
    renderCharacterGroupFilterDropdown() {
        const config = document.getElementById('character-group-filter-input')?._config;
        if (config) {
            this.filterSearchableOptions(config);
        }
    }

    renderCharacterList(characters) {
        const container = document.getElementById('character-list');
        
        if (characters.length === 0) {
            container.innerHTML = '<div class="empty-state">暂无角色</div>';
            return;
        }

        container.innerHTML = characters.map(character => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">${character.name}</div>
                    <div class="list-item-description">
                        分组: ${character.group_name}
                        ${character.nicknames && character.nicknames.length ? ` | 昵称: ${character.nicknames.join(' / ')}` : ''}
                    </div>
                </div>
                <div class="list-item-actions">
                    <button class="action-btn edit" onclick="ui.editCharacter(${character.id})">编辑</button>
                    <button class="action-btn delete" onclick="ui.deleteCharacter(${character.id})">删除</button>
                </div>
            </div>
        `).join('');
    }

    async updateTempCount() {
        try {
            const result = await api.getTempCount();
            const badge = document.getElementById('temp-count-badge');
            const countSpan = document.getElementById('temp-image-count');
            
            if (result.count > 0) {
                badge.textContent = result.count;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
            
            if (countSpan) {
                countSpan.textContent = result.count;
            }
        } catch (error) {
            console.error('更新temp计数失败:', error);
        }
    }

    async loadHomeGroupChips() {
        const orbit = document.getElementById('home-group-orbit');
        if (!orbit) return;

        const fallback = [
            { name: '先传几张图', image_count: 0 },
            { name: '再分好组', image_count: 0 },
            { name: '找图更轻松', image_count: 0 },
        ];

        if (!api.getPopularGroups) {
            this.renderHomeGroupChips(orbit, fallback);
            return;
        }

        try {
            const groups = await api.getPopularGroups(5);
            const chips = groups && groups.length ? groups : fallback;
            this.renderHomeGroupChips(orbit, chips);
        } catch (error) {
            console.error('加载首页分组失败:', error);
            this.renderHomeGroupChips(orbit, fallback);
        }
    }

    renderHomeGroupChips(orbit, groups) {
        orbit.querySelectorAll('.orbit-chip').forEach(chip => chip.remove());
        const chipClasses = ['chip-one', 'chip-two', 'chip-three', 'chip-four', 'chip-five'];

        groups.slice(0, chipClasses.length).forEach((group, index) => {
            const chip = document.createElement('span');
            chip.className = `orbit-chip ${chipClasses[index]}`;
            chip.textContent = group.image_count > 0
                ? `${group.name} · ${group.image_count}张`
                : group.name;
            orbit.appendChild(chip);
        });
    }

    async loadSystemStatus() {
        try {
            const status = await api.getSystemStatus();
            
            // 更新侧边栏状态
            document.getElementById('total-images').textContent = status.total_images;
            document.getElementById('total-groups').textContent = status.total_groups;
            const homeImages = document.getElementById('home-total-images');
            const homeAvailable = document.getElementById('home-available-images');
            const homeGroups = document.getElementById('home-total-groups');
            const homeCharacters = document.getElementById('home-total-characters');
            const homeThumbMissing = document.getElementById('home-thumb-missing');
            if (homeImages) homeImages.textContent = status.total_images;
            if (homeAvailable) homeAvailable.textContent = status.available_images || 0;
            if (homeGroups) homeGroups.textContent = status.total_groups;
            if (homeCharacters) homeCharacters.textContent = status.total_characters;
            if (homeThumbMissing) homeThumbMissing.textContent = status.thumb_missing || 0;
            
            // 更新设置页面
            document.getElementById('store-path').textContent = status.store_path;
            document.getElementById('temp-path').textContent = status.temp_path;
            document.getElementById('stat-images').textContent = status.total_images;
            const availableEl = document.getElementById('stat-available-images');
            const missingEl = document.getElementById('stat-missing-images');
            const thumbMissingEl = document.getElementById('stat-thumb-missing');
            if (availableEl) availableEl.textContent = status.available_images || 0;
            if (missingEl) missingEl.textContent = (status.missing_images || 0) + (status.archived_images || 0);
            if (thumbMissingEl) thumbMissingEl.textContent = status.thumb_missing || 0;
            document.getElementById('stat-groups').textContent = status.total_groups;
            document.getElementById('stat-characters').textContent = status.total_characters;
            document.getElementById('stat-temp').textContent = status.temp_images_count;
            this.scheduleThumbnailMaintenance(status);
        } catch (error) {
            this.showToast('加载页面数据失败', 'error');
        }
    }

    scheduleThumbnailMaintenance(status) {
        if (!this.isAdminView()) return;
        if (!status || (status.thumb_missing || 0) <= 0) return;
        if (this.thumbnailMaintenanceQueued) return;
        if (Date.now() - this.lastThumbnailMaintenanceAt < 10 * 60 * 1000) return;

        this.thumbnailMaintenanceQueued = true;
        const run = async () => {
            try {
                this.lastThumbnailMaintenanceAt = Date.now();
                await api.rebuildThumbnails(80, false);
                await this.loadSystemStatus();
            } catch (error) {
                console.error('后台生成小图失败:', error);
            } finally {
                this.thumbnailMaintenanceQueued = false;
            }
        };

        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(run, { timeout: 12000 });
        } else {
            window.setTimeout(run, 3000);
        }
    }

    showModal(title, content, isNested = false) {
        const modalOverlay = document.getElementById('modal-overlay');
        
        if (isNested) {
            // 保存当前模态框内容
            this.modalStack.push({
                title: document.getElementById('modal-title').textContent,
                content: document.getElementById('modal-body').innerHTML
            });
            this.isNestedModal = true;
        }
        
        document.getElementById('modal-title').textContent = title;
        document.getElementById('modal-body').innerHTML = content;
        modalOverlay.style.display = 'flex';
    }

    closeModal() {
        if (this.modalStack.length > 0) {
            // 恢复上一个模态框
            const previous = this.modalStack.pop();
            document.getElementById('modal-title').textContent = previous.title;
            document.getElementById('modal-body').innerHTML = previous.content;
            this.isNestedModal = this.modalStack.length > 0;
            
            // 恢复后重新绑定表单和选择器事件
            this.rebindModalEvents();
        } else {
            document.getElementById('modal-overlay').style.display = 'none';
            this.isNestedModal = false;
        }
    }
    
    /**
     * 重新绑定恢复的模态框内的事件
     */
    rebindModalEvents() {
        // 重新绑定temp上传表单
        const tempForm = document.getElementById('temp-upload-form');
        if (tempForm) {
            tempForm.onsubmit = (e) => {
                e.preventDefault();
                const encoded = tempForm.dataset.imageName;
                if (window.upload && encoded) {
                    window.upload.submitTempUpload(encoded);
                }
            };
            // 恢复角色选择器状态
            this.restoreTempCharacterSelector();
        }
        
        // 重新绑定批量上传表单
        const batchItem = document.querySelector('.batch-item');
        if (batchItem) {
            this.restoreBatchSelectors();
        }
    }
    
    /**
     * 恢复temp上传的角色选择器
     */
    async restoreTempCharacterSelector() {
        const groupSelect = document.getElementById('temp-group-select');
        const selectorContainer = document.getElementById('temp-character-selector');
        
        if (!groupSelect || !selectorContainer) return;
        
        // 刷新分组选项
        const groups = await api.getGroups();
        const currentValue = groupSelect.value;
        
        groupSelect.innerHTML = '<option value="">先选分组</option>';
        groups.forEach(group => {
            groupSelect.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${group.name}</option>`;
        });
        
        // 重新初始化角色选择器
        if (currentValue) {
            const characters = await api.getCharacters(parseInt(currentValue));
            
            // 获取或创建选择器
            let tempCharacterSelector = window.characterSelectors['temp-character-selector'];
            if (!tempCharacterSelector) {
                tempCharacterSelector = new CharacterSelector('temp-character-selector');
                window.characterSelectors['temp-character-selector'] = tempCharacterSelector;
            }
            tempCharacterSelector.setCharacters(characters);
        }
        
        // 重新绑定分组change事件
        groupSelect.addEventListener('change', async () => {
            const groupId = groupSelect.value;
            const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
            if (groupId) {
                const characters = await api.getCharacters(parseInt(groupId));
                if (tempCharacterSelector) {
                    tempCharacterSelector.setCharacters(characters);
                }
            } else {
                if (tempCharacterSelector) {
                    tempCharacterSelector.setCharacters([]);
                }
            }
        });
    }
    
    /**
     * 恢复批量上传的选择器
     */
    async restoreBatchSelectors() {
        const groups = await api.getGroups();
        
        document.querySelectorAll('.batch-group').forEach(select => {
            const currentValue = select.value;
            
            select.innerHTML = '<option value="">先选分组</option>';
            groups.forEach(group => {
                select.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${group.name}</option>`;
            });
            
            // 如果已选择分组，刷新角色列表
            if (currentValue) {
                const characterSelect = select.parentElement.querySelector('.batch-character');
                api.getCharacters(parseInt(currentValue)).then(characters => {
                    const currentCharacters = Array.from(characterSelect.selectedOptions).map(opt => opt.value);
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        const selected = currentCharacters.includes(String(character.id));
                        characterSelect.innerHTML += `<option value="${character.id}" ${selected ? 'selected' : ''}>${character.name}</option>`;
                    });
                    characterSelect.disabled = false;
                });
            }
            
            // 重新绑定change事件
            const newSelect = select.cloneNode(true);
            select.parentNode.replaceChild(newSelect, select);
            
            newSelect.addEventListener('change', async () => {
                const groupId = newSelect.value;
                const characterSelect = newSelect.parentElement.querySelector('.batch-character');
                
                if (groupId) {
                    const characters = await api.getCharacters(parseInt(groupId));
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        characterSelect.innerHTML += `<option value="${character.id}">${character.name}</option>`;
                    });
                    characterSelect.disabled = false;
                } else {
                    characterSelect.innerHTML = '<option value="">先选分组</option>';
                    characterSelect.disabled = true;
                }
            });
        });
    }
    
    /**
     * 在嵌套模态框关闭后刷新父模态框内的选择器
     */
    async refreshModalSelectors(newItemId, itemType, groupId = null) {
        // 等待模态框DOM更新
        await new Promise(resolve => setTimeout(resolve, 100));
        
        // 处理temp上传模态框
        const tempGroupSelect = document.getElementById('temp-group-select');
        if (tempGroupSelect) {
            if (itemType === 'group') {
                // 刷新分组选项
                const groups = await api.getGroups();
                tempGroupSelect.innerHTML = '<option value="">先选分组</option>';
                groups.forEach(group => {
                    tempGroupSelect.innerHTML += `<option value="${group.id}" ${group.id == newItemId ? 'selected' : ''}>${group.name}</option>`;
                });
                
                // 自动选中并加载角色
                if (newItemId) {
                    tempGroupSelect.value = newItemId;
                    tempGroupSelect.dispatchEvent(new Event('change'));
                }
            } else if (itemType === 'character' && groupId) {
                // 如果当前分组匹配，刷新角色选择器
                if (tempGroupSelect.value == groupId) {
                    const characters = await api.getCharacters(groupId);
                    const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
                    if (tempCharacterSelector) {
                        tempCharacterSelector.setCharacters(characters);
                        // 自动选中新角色
                        tempCharacterSelector.selectCharacterById(newItemId);
                    }
                } else {
                    // 自动切换到新角色所在的分组
                    tempGroupSelect.value = groupId;
                    const characters = await api.getCharacters(groupId);
                    const tempCharacterSelector = window.characterSelectors['temp-character-selector'];
                    if (tempCharacterSelector) {
                        tempCharacterSelector.setCharacters(characters);
                        tempCharacterSelector.selectCharacterById(newItemId);
                    }
                }
            }
        }
        
        // 处理批量上传模态框中的选择器
        const batchGroups = document.querySelectorAll('.batch-group');
        if (batchGroups.length > 0) {
            const groups = await api.getGroups();
            
            batchGroups.forEach(async select => {
                const currentValue = select.value;
                
                if (itemType === 'group') {
                    // 刷新分组选项
                    select.innerHTML = '<option value="">先选分组</option>';
                    groups.forEach(group => {
                        select.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${group.name}</option>`;
                    });
                } else if (itemType === 'character' && currentValue == groupId) {
                    // 刷新角色选项
                    const characterSelect = select.parentElement.querySelector('.batch-character');
                    const characters = await api.getCharacters(parseInt(currentValue));
                    const currentChars = Array.from(characterSelect.selectedOptions).map(opt => opt.value);
                    
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        const selected = currentChars.includes(String(character.id)) || character.id == newItemId;
                        characterSelect.innerHTML += `<option value="${character.id}" ${selected ? 'selected' : ''}>${character.name}</option>`;
                    });
                }
            });
        }
        
        // 处理单张上传的选择器
        const singleGroupSelect = document.getElementById('single-group-select');
        if (singleGroupSelect && document.getElementById('single-upload-form').style.display !== 'none') {
            if (itemType === 'group') {
                const groups = await api.getGroups();
                const currentValue = singleGroupSelect.value;
                
                singleGroupSelect.innerHTML = '<option value="">先选分组</option>';
                groups.forEach(group => {
                    singleGroupSelect.innerHTML += `<option value="${group.id}" ${group.id == currentValue ? 'selected' : ''}>${group.name}</option>`;
                });
                
                // 选中新分组
                singleGroupSelect.value = newItemId;
                singleGroupSelect.dispatchEvent(new Event('change'));
            } else if (itemType === 'character' && groupId) {
                // 确保分组正确
                if (singleGroupSelect.value != groupId) {
                    singleGroupSelect.value = groupId;
                }
                
                const characters = await api.getCharacters(groupId);
                if (upload.singleCharacterSelector) {
                    upload.singleCharacterSelector.setCharacters(characters);
                    upload.singleCharacterSelector.selectCharacterById(newItemId);
                }
            }
        }
    }

    showToast(message, type = 'info', duration = 3000) {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, duration);
    }

    // 模态框相关方法
    async showCreateGroupModal(isNested = false) {
        const content = `
            <form id="create-group-form">
                <div class="form-group">
                    <label for="group-name">分组名称</label>
                    <input type="text" id="group-name" class="form-input" required>
                </div>
                <div class="form-group">
                    <label for="group-description">备注</label>
                    <textarea id="group-description" class="form-textarea"></textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="submit" class="btn btn-primary">添加</button>
                </div>
            </form>
        `;
        
        this.showModal('添加分组', content, isNested);
        
        document.getElementById('create-group-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.createGroup(isNested);
        });
    }

    async createGroup(isNested = false) {
        try {
            const data = {
                name: document.getElementById('group-name').value,
                description: document.getElementById('group-description').value || null
            };
            
            const newGroup = await api.createGroup(data);

            if (newGroup && newGroup.message && !newGroup.id) {
                this.showToast(newGroup.message, 'success');
                this.closeModal();
                return;
            }
            
            // 学习新的分组名
            if (window.PinyinSearch && data.name) {
                window.PinyinSearch.learn(data.name);
            }
            
            // 使缓存失效
            this.invalidateCache('groups');
            
            this.showToast('分组创建成功', 'success');
            this.closeModal();
            this.loadGroups();
            this.updateSearchOptions();
            await this.updateUploadOptions();
            
            // 如果是嵌套模态框，需要刷新模态框内的选择器
            if (isNested) {
                await this.refreshModalSelectors(newGroup.id, 'group');
            }
            
            // 如果在上传页面，自动选中新建的分组
            if (this.currentPage === 'upload' && !isNested) {
                const singleGroupSelect = document.getElementById('single-group-select');
                if (singleGroupSelect && newGroup.id) {
                    singleGroupSelect.value = newGroup.id;
                    // 触发change事件以加载角色
                    singleGroupSelect.dispatchEvent(new Event('change'));
                }
            }
        } catch (error) {
            this.showToast(`创建分组失败: ${error.message}`, 'error');
        }
    }

    async showCreateCharacterModal(isNested = false) {
        try {
            const groups = await api.getGroups();
            const groupOptions = groups.map(group => 
                `<option value="${group.id}">${group.name}</option>`
            ).join('');
            
            const content = `
                <form id="create-character-form">
                    <div class="form-group">
                        <label for="character-name">角色名称</label>
                        <input type="text" id="character-name" class="form-input" required>
                    </div>
                    <div class="form-group">
                        <label for="character-group">所属分组</label>
                        <select id="character-group" class="form-select" required>
                            <option value="">先选分组</option>
                            ${groupOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="character-nicknames">角色昵称</label>
                        <input type="text" id="character-nicknames" class="form-input" placeholder="多个昵称用英文逗号分隔">
                    </div>
                    <div class="form-group">
                        <label for="character-description">备注</label>
                        <textarea id="character-description" class="form-textarea"></textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="submit" class="btn btn-primary">添加</button>
                    </div>
                </form>
            `;
            
            this.showModal('添加角色', content, isNested);
            
            document.getElementById('create-character-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.createCharacter(isNested);
            });
        } catch (error) {
            this.showToast('加载分组失败', 'error');
        }
    }

    async createCharacter(isNested = false) {
        try {
            const data = {
                name: document.getElementById('character-name').value,
                group_id: parseInt(document.getElementById('character-group').value),
                nicknames: document.getElementById('character-nicknames').value
                    .split(',')
                    .map(item => item.trim())
                    .filter(Boolean),
                description: document.getElementById('character-description').value || null
            };
            
            const newCharacter = await api.createCharacter(data);

            if (newCharacter && newCharacter.message && !newCharacter.id) {
                this.showToast(newCharacter.message, 'success');
                this.closeModal();
                return;
            }
            
            // 学习新的角色名
            if (window.PinyinSearch && data.name) {
                window.PinyinSearch.learn(data.name);
            }
            
            // 使缓存失效
            this.invalidateCache('characters');
            
            this.showToast('角色创建成功', 'success');
            this.closeModal();
            this.loadCharacters();
            this.updateSearchOptions();
            await this.updateUploadOptions();
            
            // 如果是嵌套模态框，需要刷新模态框内的选择器
            if (isNested) {
                await this.refreshModalSelectors(newCharacter.id, 'character', data.group_id);
            }
            
            // 如果在上传页面（非嵌套模态框情况），自动选中新建的角色
            if (this.currentPage === 'upload' && !isNested) {
                const singleGroupSelect = document.getElementById('single-group-select');
                const singleCharacterSelect = document.getElementById('single-character-select');
                
                if (singleGroupSelect && singleCharacterSelect && newCharacter.id) {
                    // 先选中对应的分组
                    singleGroupSelect.value = data.group_id;
                    // 触发change事件以加载角色列表
                    await singleGroupSelect.dispatchEvent(new Event('change'));
                    // 等待一下让角色列表更新
                    setTimeout(() => {
                        // 选中新建的角色
                        const option = Array.from(singleCharacterSelect.options).find(opt => opt.value == newCharacter.id);
                        if (option) {
                            option.selected = true;
                        }
                    }, 100);
                }
            }
        } catch (error) {
            this.showToast(`创建角色失败: ${error.message}`, 'error');
        }
    }

    // 分组编辑和删除
    async editGroup(groupId) {
        try {
            const group = await api.getGroups();
            const currentGroup = group.find(g => g.id === groupId);
            
            if (!currentGroup) {
                this.showToast('分组不存在', 'error');
                return;
            }
            
            const content = `
                <form id="edit-group-form">
                    <div class="form-group">
                        <label for="edit-group-name">分组名称</label>
                        <input type="text" id="edit-group-name" class="form-input" value="${currentGroup.name}" required>
                    </div>
                    <div class="form-group">
                        <label for="edit-group-description">备注</label>
                        <textarea id="edit-group-description" class="form-textarea">${currentGroup.description || ''}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑分组', content);
            
            document.getElementById('edit-group-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.updateGroup(groupId);
            });
        } catch (error) {
            this.showToast(`加载分组信息失败: ${error.message}`, 'error');
        }
    }
    
    async updateGroup(groupId) {
        try {
            const data = {
                name: document.getElementById('edit-group-name').value,
                description: document.getElementById('edit-group-description').value || null
            };
            
            const result = await api.updateGroup(groupId, data);
            if (result && result.message) {
                this.showToast(result.message, 'success');
                this.closeModal();
                return;
            }
            this.invalidateCache('groups');
            this.showToast('分组更新成功', 'success');
            this.closeModal();
            this.loadGroups();
            this.updateSearchOptions();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`更新分组失败: ${error.message}`, 'error');
        }
    }
    
    async deleteGroup(groupId) {
        if (!confirm('确定要删除此分组吗？删除后该分组下的所有角色也将被删除！')) {
            return;
        }
        
        try {
            const result = await api.deleteGroup(groupId);
            if (result && result.message) {
                this.showToast(result.message, 'success');
                return;
            }
            this.invalidateCache('groups');
            this.invalidateCache('characters');
            this.showToast('分组删除成功', 'success');
            this.loadGroups();
            this.updateSearchOptions();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`删除分组失败: ${error.message}`, 'error');
        }
    }
    
    // 角色编辑和删除
    async editCharacter(characterId) {
        try {
            const characters = await api.getCharacters();
            const groups = await api.getGroups();
            const currentCharacter = characters.find(c => c.id === characterId);
            
            if (!currentCharacter) {
                this.showToast('角色不存在', 'error');
                return;
            }
            
            const groupOptions = groups.map(group => 
                `<option value="${group.id}" ${group.id === currentCharacter.group_id ? 'selected' : ''}>${group.name}</option>`
            ).join('');
            
            const content = `
                <form id="edit-character-form">
                    <div class="form-group">
                        <label for="edit-character-name">角色名称</label>
                        <input type="text" id="edit-character-name" class="form-input" value="${currentCharacter.name}" required>
                    </div>
                    <div class="form-group">
                        <label for="edit-character-group">所属分组</label>
                        <select id="edit-character-group" class="form-select" required>
                            ${groupOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="edit-character-nicknames">角色昵称</label>
                        <input type="text" id="edit-character-nicknames" class="form-input" value="${(currentCharacter.nicknames || []).join(', ')}" placeholder="多个昵称用英文逗号分隔">
                    </div>
                    <div class="form-group">
                        <label for="edit-character-description">备注</label>
                        <textarea id="edit-character-description" class="form-textarea">${currentCharacter.description || ''}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑角色', content);
            
            document.getElementById('edit-character-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.updateCharacter(characterId);
            });
        } catch (error) {
            this.showToast(`加载角色信息失败: ${error.message}`, 'error');
        }
    }
    
    async updateCharacter(characterId) {
        try {
            const data = {
                name: document.getElementById('edit-character-name').value,
                group_id: parseInt(document.getElementById('edit-character-group').value),
                nicknames: document.getElementById('edit-character-nicknames').value
                    .split(',')
                    .map(item => item.trim())
                    .filter(Boolean),
                description: document.getElementById('edit-character-description').value || null
            };
            
            const result = await api.updateCharacter(characterId, data);
            if (result && result.message) {
                this.showToast(result.message, 'success');
                this.closeModal();
                return;
            }
            this.invalidateCache('characters');
            this.showToast('角色更新成功', 'success');
            this.closeModal();
            this.loadCharacters();
            this.updateSearchOptions();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`更新角色失败: ${error.message}`, 'error');
        }
    }
    
    async deleteCharacter(characterId) {
        if (!confirm('确定要删除此角色吗？')) {
            return;
        }
        
        try {
            const result = await api.deleteCharacter(characterId);
            if (result && result.message) {
                this.showToast(result.message, 'success');
                return;
            }
            this.invalidateCache('characters');
            this.showToast('角色删除成功', 'success');
            this.loadCharacters();
            this.updateSearchOptions();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`删除角色失败: ${error.message}`, 'error');
        }
    }
    
    // 图片编辑和删除
    async editImage(imageId) {
        try {
            const image = await api.getImage(imageId);
            const groups = await api.getGroups();
            
            const groupOptions = groups.map(group => 
                `<option value="${group.id}">${group.name}</option>`
            ).join('');
            
            const content = `
                <form id="edit-image-form">
                    <div class="form-group">
                        <label for="edit-image-group">分组</label>
                        <select id="edit-image-group" class="form-select" required>
                            <option value="">先选分组</option>
                            ${groupOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="edit-image-characters">角色</label>
                        <select id="edit-image-characters" class="form-select" multiple required>
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="edit-image-pid">PID</label>
                        <input type="text" id="edit-image-pid" class="form-input" value="${image.pid || ''}">
                    </div>
                    <div class="form-group">
                        <label for="edit-image-description">备注</label>
                        <textarea id="edit-image-description" class="form-textarea">${image.description || ''}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑图片', content);
            
            // 监听分组变化
            const groupSelect = document.getElementById('edit-image-group');
            const characterSelect = document.getElementById('edit-image-characters');
            
            groupSelect.addEventListener('change', async () => {
                const groupId = groupSelect.value;
                if (groupId) {
                    const characters = await api.getCharacters(parseInt(groupId));
                    characterSelect.innerHTML = '';
                    characters.forEach(character => {
                        const selected = image.characters.some(c => c.id === character.id);
                        characterSelect.innerHTML += `<option value="${character.id}" ${selected ? 'selected' : ''}>${character.name}</option>`;
                    });
                }
            });
            
            // 如果图片已有角色，加载第一个角色的分组
            if (image.characters.length > 0) {
                groupSelect.value = image.characters[0].group_id;
                groupSelect.dispatchEvent(new Event('change'));
            }
            
            document.getElementById('edit-image-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.updateImage(imageId);
            });
        } catch (error) {
            this.showToast(`加载图片信息失败: ${error.message}`, 'error');
        }
    }
    
    async updateImage(imageId) {
        try {
            const characterSelect = document.getElementById('edit-image-characters');
            const selectedCharacters = Array.from(characterSelect.selectedOptions).map(option => parseInt(option.value));
            
            if (selectedCharacters.length === 0) {
                this.showToast('请选择至少一个角色', 'error');
                return;
            }
            
            const data = {
                character_ids: selectedCharacters,
                pid: document.getElementById('edit-image-pid').value || null,
                description: document.getElementById('edit-image-description').value || null
            };
            
            const result = await api.updateImage(imageId, data);
            const message = result && result.message ? result.message : '图片更新成功';
            const status = result && result.status ? result.status : null;
            const toastType = status === 'pending' || message.includes('审核') ? 'info' : 'success';
            this.showToast(message, toastType);
            this.closeModal();
            this.loadImages(null);
        } catch (error) {
            this.showToast(`更新图片失败: ${error.message}`, 'error');
        }
    }
    
    async deleteImage(imageId) {
        if (!confirm('确定要删除此图片吗？此操作不可恢复！')) {
            return;
        }
        
        try {
            const result = await api.deleteImage(imageId);
            const message = result && result.message ? result.message : '图片删除成功';
            const status = result && result.status ? result.status : null;
            const toastType = status === 'pending' || message.includes('审核') ? 'info' : 'success';
            this.showToast(message, toastType);
            this.closeModal();
            this.loadImages(null);
            this.loadSystemStatus();
        } catch (error) {
            this.showToast(`删除图片失败: ${error.message}`, 'error');
        }
    }

    async showImageDetail(imageId) {
        try {
            const image = await api.getImage(imageId);
            const content = `
                <div class="image-detail">
                    <img src="${this.getImageUrl(image)}" loading="eager" decoding="async" 
                         alt="Image ${image.image_id}" style="max-width: 100%; height: auto; border-radius: 8px; margin-bottom: 16px;">
                    
                    <div class="detail-info">
                        <p><strong>图片编号:</strong> ${image.image_id}</p>
                        <p><strong>原始文件名:</strong> ${image.original_filename || '未知'}</p>
                        <p><strong>文件大小:</strong> ${image.file_size ? (image.file_size / 1024 / 1024).toFixed(2) + ' MB' : '未知'}</p>
                        <p><strong>分辨率:</strong> ${image.width && image.height ? `${image.width}x${image.height}` : '未知'}</p>
                        <p><strong>PID:</strong> ${image.pid || '无'}</p>
                        <p><strong>备注:</strong> ${image.description || '无'}</p>
                        <p><strong>角色:</strong> ${image.characters.map(char => {
                            const groupName = char.group_name || (char.group && char.group.name) || '未知分组';
                            return `${groupName} - ${char.name}`;
                        }).join(', ')}</p>
                        <p><strong>创建时间:</strong> ${new Date(image.created_at).toLocaleString()}</p>
                    </div>
                    
                    <div class="detail-actions" style="margin-top: 20px; display: flex; gap: 12px;">
                        <button class="btn btn-primary" onclick="ui.editImage('${image.image_id}')">编辑</button>
                        <button class="btn btn-danger" onclick="ui.deleteImage('${image.image_id}')">删除</button>
                        <button class="btn btn-secondary" onclick="ui.closeModal()">关闭</button>
                    </div>
                </div>
            `;
            
            this.showModal('图片详情', content);
        } catch (error) {
            if (String(error.message || '').includes('404') || String(error.message || '').includes('Image not found')) {
                const resyncAction = this.isAdminView()
                    ? '<button class="btn btn-primary" onclick="syncImageStatus()">重新检查</button>'
                    : '';
                this.showModal('这张图现在打不开', `
                    <div class="empty-state">
                        <p>这张图的原文件找不到了，可以重新检查一下。</p>
                        <div class="form-actions" style="margin-top: 16px;">
                            <button class="btn btn-secondary" onclick="ui.closeModal()">关闭</button>
                            ${resyncAction}
                        </div>
                    </div>
                `);
                return;
            }
            this.showToast(`加载图片详情失败: ${error.message}`, 'error');
        }
    }
}

// 全局函数
function searchImages() {
    ui.pagination.currentPage = 1;
    ui.loadImages(ui.getSearchParams());
}

function clearSearch() {
    // 清空所有搜索条件
    document.getElementById('search-group-input').value = '';
    document.getElementById('search-group').value = '';
    document.getElementById('search-character-input').value = '';
    document.getElementById('search-character').value = '';
    document.getElementById('search-pid').value = '';
    
    const imageIdInput = document.getElementById('search-image-id');
    if (imageIdInput) imageIdInput.value = '';
    
    // 重置角色过滤
    ui.filteredCharacters = ui.allCharacters;
    ui.renderCharacterDropdown();
    
    // 重新加载图片
    ui.pagination.currentPage = 1;
    ui.activeImageSearchParams = {};
    ui.loadImages({});
    ui.showToast('已重置查找条件', 'info');
}

function toggleAdvancedSearch() {
    const panel = document.getElementById('advanced-search-panel');
    const icon = document.getElementById('advanced-toggle-icon');
    
    if (panel.style.display === 'none') {
        panel.style.display = 'block';
        icon.classList.add('expanded');
    } else {
        panel.style.display = 'none';
        icon.classList.remove('expanded');
    }
}

async function searchByImageId() {
    const imageId = document.getElementById('search-image-id').value.trim().toUpperCase();
    
    if (!imageId) {
        ui.showToast('请输入图片编号', 'warning');
        return;
    }
    
    if (!/^[A-F0-9]{10}$/.test(imageId)) {
        ui.showToast('图片编号需要是 10 位十六进制字符', 'error');
        return;
    }
    
    try {
        const image = await api.getImage(imageId);
        if (image) {
            ui.showImageDetail(imageId);
        }
    } catch (error) {
        ui.showToast(`没有找到编号为 ${imageId} 的图片`, 'error');
    }
}

function refreshData() {
    ui.invalidateCache();
    if (ui.currentPage === 'management') {
        if (ui.currentTab === 'group-management') {
            ui.loadGroups();
        } else if (ui.currentTab === 'character-management') {
            ui.loadCharacters();
        } else {
            ui.loadImages(null);
            ui.initializeSearchSelectors();
        }
    } else if (ui.currentPage === 'upload') {
        ui.loadUploadData();
    } else if (ui.currentPage === 'settings' || ui.currentPage === 'home') {
        ui.loadSystemStatus();
        if (ui.currentPage === 'home') ui.loadHomeGroupChips();
    }
    if (ui.currentPage !== 'settings' && ui.currentPage !== 'home') {
        ui.loadSystemStatus();
    }
    ui.showToast('数据已刷新', 'success');
}

function showCreateGroupModal(isNested = false) {
    ui.showCreateGroupModal(isNested);
}

function showCreateCharacterModal(isNested = false) {
    ui.showCreateCharacterModal(isNested);
}

function closeModal() {
    ui.closeModal();
}

async function cleanupOrphaned() {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }
    try {
        const preview = await api.cleanupPreview();
        const message = [
            `打不开的记录: ${preview.missing_records}`,
            `多出来的文件: ${preview.orphan_files}`,
            `待生成小图: ${preview.thumb_missing}`,
            '',
            '这些打不开的图片会先从列表里收起来，确认继续吗？'
        ].join('\n');
        if (!confirm(message)) return;

        const result = await api.cleanupOrphaned('archive');
        ui.showToast(result.message, 'success');
        ui.loadImages(null);
        ui.loadSystemStatus();
    } catch (error) {
        ui.showToast(`清理失败: ${error.message}`, 'error');
    }
}

async function syncImageStatus() {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }
    try {
        const result = await api.syncImageStatus();
        ui.showToast(`检查完成：能打开 ${result.available_records}，打不开 ${result.missing_records}`, 'success');
        ui.loadImages(null);
        ui.loadSystemStatus();
    } catch (error) {
        ui.showToast(`检查失败: ${error.message}`, 'error');
    }
}

async function rebuildThumbnails() {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }
    try {
        const result = await api.rebuildThumbnails(500, true);
        ui.showToast(result.message, 'success');
        ui.loadImages(null);
        ui.loadSystemStatus();
    } catch (error) {
        ui.showToast(`生成小图失败: ${error.message}`, 'error');
    }
}

async function scanStoreOrphans() {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }
    try {
        const result = await api.scanStoreOrphans();
        ui.showToast(result.message, 'success');
        ui.updateTempCount();
        ui.loadSystemStatus();
    } catch (error) {
        ui.showToast(`扫描失败: ${error.message}`, 'error');
    }
}

// 创建全局UI实例
window.ui = new UIManager();
