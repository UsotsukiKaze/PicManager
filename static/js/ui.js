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
        this.allFeatureTags = [];
        
        // 模态框状态管理
        this.modalStack = [];
        this.isNestedModal = false;
        this.modalPreviousFocus = null;
        
        // 数据缓存和加载状态
        this.dataCache = {
            groups: { data: null, timestamp: 0 },
            characters: { data: null, timestamp: 0 },
            featureTags: { data: null, timestamp: 0 },
            images: { data: null, timestamp: 0, params: null }
        };
        this.cacheTimeout = 30000; // 缓存有效期30秒
        this.loadingStates = {}; // 防止重复加载
        this.cacheGenerations = {}; // 失效后忽略仍在途的旧响应
        this.thumbnailMaintenanceQueued = false;
        this.lastThumbnailMaintenanceAt = 0;
        this.thumbnailObserver = null;
        this.imageLoadRequestId = 0;
        this.avatarCropState = null;
        this.featureActivationPromises = {};
        
        this.initializeEventListeners();
    }
    
    /**
     * 检查缓存是否有效
     */
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
            const modalOverlay = document.getElementById('modal-overlay');
            const modalVisible = modalOverlay?.style.display !== 'none';
            const nativeTop = Array.from(document.querySelectorAll('dialog[open]')).at(-1);
            if (nativeTop && nativeTop !== this.modalBridge) return;
            if (e.key === 'Escape' && modalVisible) {
                e.preventDefault();
                this.closeModal();
            }
            if (e.key === 'Tab' && modalVisible) this.trapModalFocus(e);
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
            if (e.target.id === 'feature-tag-search-input') {
                this.filterFeatureTags(e.target.value);
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
        const currentPageElement = document.getElementById(`page-${page}`);
        const retryFailedFeature = Boolean(currentPageElement?.dataset.featureLoadError);
        if (this.currentPage === page && !this._forceSwitch && !retryFailedFeature) return;
        
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
        const userButton = document.querySelector('.sidebar-user');
        if (page === 'profile') userButton?.setAttribute('aria-current', 'page');
        else userButton?.removeAttribute('aria-current');
        targetPage.style.display = 'block';
        targetPage.classList.remove('page-enter');
        void targetPage.offsetWidth;
        targetPage.classList.add('page-enter');

        if (this.currentPage === 'pixiv-ol' && page !== 'pixiv-ol') window.pixivOL?.suspend();
        if (this.currentPage === 'upload' && page !== 'upload') window.upload?.suspendTemp();
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

    setPageFeatureState(page, state, featureKey = '') {
        const pageElement = document.getElementById(`page-${page}`);
        if (!pageElement) return;

        if (state === 'ready') {
            pageElement.inert = false;
            pageElement.removeAttribute('aria-busy');
            delete pageElement.dataset.featureLoadError;
            return;
        }

        // Inline onclick handlers are registered by the lazy script. Keep the
        // page non-interactive until those globals exist, including on failure.
        pageElement.inert = true;
        if (state === 'loading') {
            pageElement.setAttribute('aria-busy', 'true');
            delete pageElement.dataset.featureLoadError;
        } else {
            pageElement.removeAttribute('aria-busy');
            pageElement.dataset.featureLoadError = featureKey;
        }
    }

    activateFeature(key, page, activation, errorMessage) {
        if (this.featureActivationPromises[key]) {
            return this.featureActivationPromises[key];
        }

        this.setPageFeatureState(page, 'loading');
        const activationPromise = Promise.resolve()
            .then(activation)
            .then(result => {
                this.setPageFeatureState(page, 'ready');
                return result;
            })
            .catch(error => {
                console.error(`Failed to activate feature ${key}:`, error);
                this.setPageFeatureState(page, 'error', key);
                this.showToast(errorMessage, 'error');
                return null;
            })
            .finally(() => {
                delete this.featureActivationPromises[key];
            });

        this.featureActivationPromises[key] = activationPromise;
        return activationPromise;
    }

    activateUploadPage() {
        return this.activateFeature('upload-page', 'upload', async () => {
            await window.auth.loadFeature('upload');
            await this.loadUploadData();
            if(this.currentPage==='upload'&&this.currentTab==='temp-upload')await window.upload.enterTemp();
        }, '上传功能加载失败，请重试');
    }

    activateEmojiLibraryPage() {
        return this.activateFeature('emoji-library-page', 'emoji-library', async () => {
            const emojiLibrary = await window.auth.loadFeature('emoji');
            if (!emojiLibrary.initialized) {
                await emojiLibrary.init();
            }
        }, '表情包功能加载失败，请重试');
    }

    activateEmojiUploadTab() {
        return this.activateFeature('emoji-upload-tab', 'upload', async () => {
            await window.auth.loadFeature('emoji');
        }, '表情包上传功能加载失败，请重试');
    }
    
    /**
     * 页面切换后的数据加载处理
     */
    handlePageSwitch(page) {
        switch (page) {
            case 'home':
                this.loadSystemStatus();
                this.loadHomeGroupChips();
                this.loadHomeRankings();
                break;
            case 'management':
                this.applyRolePreferences();
                break;
            case 'upload':
                this.activateUploadPage();
                break;
            case 'emoji-library':
                this.activateEmojiLibraryPage();
                break;
            case 'pixiv-ol':
                if (!window.auth.isAdmin()) {
                    this.switchPage('home');
                    return;
                }
                this.activateFeature('pixiv-ol-page', 'pixiv-ol', async () => {
                    await window.auth.loadStyle('/static/css/pixiv-ol.css?v=20261004l');
                    const feature = await window.auth.loadFeature('pixiv');
                    await feature.init();
                }, 'Pixiv-ol 加载失败，请重试');
                break;
            case 'profile':
                window.PicManagerShell.openProfile();
                break;
            case 'settings':
                this.loadSystemStatus();
                if (window.auth.isAdmin()) {
                    this.activateFeature('pixiv-settings', 'settings', async () => {
                        await window.auth.loadStyle('/static/css/pixiv-ol.css?v=20261004l');
                        const feature = await window.auth.loadFeature('pixiv');
                        await feature.initSettings();
                    }, 'Pixiv 设置加载失败，请重试');
                }
                break;
            case 'rankings':
                this.loadRankings();
                break;
        }
    }

    switchTab(tab) {
        // 防止重复切换
        if (this.currentTab === tab) return;
        if (this.currentTab === 'temp-upload' && tab !== 'temp-upload') window.upload?.suspendTemp();
        
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
                this.loadImageSearchOptions();
                break;
            case 'group-management':
                this.loadGroups();
                break;
            case 'character-management':
                this.loadCharacters();
                break;
            case 'feature-tag-management':
                this.loadFeatureTags();
                break;
            case 'temp-upload':
                // 调用upload对象的loadTempImages方法
                if (window.upload) {
                    upload.enterTemp();
                }
                break;
            case 'emoji-upload':
                this.activateEmojiUploadTab();
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
        const [groups, characters, featureTags] = await Promise.all([
            this.loadGroupsData(false, true),
            this.loadCharactersData(false, true),
            this.loadFeatureTagsData(false, true)
        ]);

        await this.updateUploadOptions({ groups, characters, featureTags }, false);
        await this.updateTempCount();
    }
    
    /**
     * 加载分组数据（带缓存）
     */
    async loadGroupsData(forceRefresh = false, throwOnError = false) {
        try {
            const groups = await this.loadCachedEntity('groups', () => api.getGroups(), { forceRefresh });
            this.allGroups = groups;
            
            // 学习拼音
            if (window.PinyinSearch) {
                window.PinyinSearch.learnWords(groups.map(g => g.name));
            }
            
            return groups;
        } catch (error) {
            if (throwOnError) throw error;
            this.showToast('加载分组失败', 'error');
            return this.allGroups || [];
        }
    }
    
    /**
     * 加载角色数据（带缓存）
     */
    async loadCharactersData(forceRefresh = false, throwOnError = false) {
        try {
            const characters = await this.loadCachedEntity('characters', () => api.getCharacters(), { forceRefresh });
            this.allCharacters = characters;
            
            // 学习拼音
            if (window.PinyinSearch) {
                window.PinyinSearch.learnWords(characters.map(c => c.name));
            }
            
            return characters;
        } catch (error) {
            if (throwOnError) throw error;
            this.showToast('加载角色失败', 'error');
            return this.allCharacters || [];
        }
    }

    async updateUploadOptions(data = null, reportError = true) {
        try {
            const { groups, characters, featureTags } = data || await (async () => {
                const [groups, characters, featureTags] = await Promise.all([
                    api.getGroups(),
                    api.getCharacters(),
                    api.getFeatureTags()
                ]);
                return { groups, characters, featureTags };
            })();
            this.allGroups = groups;
            this.allCharacters = characters;
            this.allFeatureTags = featureTags;
            if (window.upload && upload.singleTagSelector) {
                upload.singleTagSelector.setData({ groups, characters, featureTags });
            }

            // 更新单张上传的分组选择器
            const singleGroupSelect = document.getElementById('single-group-select');
            if (!singleGroupSelect) return;
            singleGroupSelect.innerHTML = '<option value="">先选分组</option>';
            groups.forEach(group => {
                singleGroupSelect.innerHTML += `<option value="${group.id}">${this.escapeHomeRankingText(group.name)}</option>`;
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
            if (reportError) {
                this.showToast('加载上传选项失败', 'error');
                return false;
            }
            throw error;
        }
    }

    async loadGroups() {
        const groups = await this.loadGroupsData();
        this.renderGroupList(groups);
    }
    
    filterGroups(query) {
        const q = String(query || '').trim().toLowerCase();
        const filtered = !q
            ? this.allGroups
            : window.PinyinSearch.filter(this.allGroups, query, 'name');
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
                <div class="entity-list-main">
                    <img class="entity-avatar" src="${this.getEntityAvatar(group)}" alt="${this.escapeHomeRankingText(group.name)}的头像" loading="lazy" decoding="async" onerror="ui.handleEntityAvatarFallback(this)">
                    <div class="list-item-info">
                        <div class="list-item-name">${this.escapeHomeRankingText(group.name)}</div>
                        <div class="list-item-description">
                            ${this.escapeHomeRankingText(group.description || '无描述')}
                            ${group.aliases && group.aliases.length ? ` | 别称: ${this.escapeHomeRankingText(group.aliases.join(' / '))}` : ''}
                        </div>
                    </div>
                </div>
                <div class="list-item-actions">
                    ${window.auth.isRoot()?`<button class="action-btn" onclick="managePixivMappings('group',${group.id})">Pixiv 标签</button>`:''}<button class="action-btn edit" onclick="ui.editGroup(${group.id})">编辑</button>
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
            const avatar = this.getEntityAvatar({
                avatar_url: item.avatar_url || `https://q1.qlogo.cn/g?b=qq&nk=${encodeURIComponent(item.qq_number)}&s=100`
            });
            return `
                <div class="leaderboard-item">
                    <div class="leaderboard-rank">${index + 1}</div>
                    <img class="leaderboard-avatar" src="${avatar}" alt="头像" onerror="this.style.display='none'">
                    <div class="leaderboard-info">
                        <div class="leaderboard-name">${this.escapeHomeRankingText(item.nickname)}</div>
                        <div class="leaderboard-sub">QQ: ${this.escapeHomeRankingText(item.qq_number)}</div>
                    </div>
                    <div class="leaderboard-score">${item.score}</div>
                </div>
            `;
        }).join('');
    }

    async loadHomeRankings() {
        const contributionContainer = document.getElementById('home-contribution-ranking');
        const groupContainer = document.getElementById('home-recent-group-ranking');
        if (!contributionContainer || !groupContainer) return;

        try {
            const data = await api.getRankings(5);
            this.renderHomeContributionRanking(data.contribution || []);
            this.renderHomeRecentGroupRanking(data.recent_groups || [], data.recent_days || 30);
        } catch (error) {
            contributionContainer.innerHTML = '<div class="home-ranking-empty">贡献排行暂时无法加载</div>';
            groupContainer.innerHTML = '<div class="home-ranking-empty">分组排行暂时无法加载</div>';
            console.error('加载首页排行失败:', error);
        }
    }

    escapeHomeRankingText(value) {
        return window.PicManagerSecurity.escapeHTML(value);
    }

    getEntityAvatar(item) {
        const fallback = '/favicon.ico';
        if (!item || !item.avatar_url) return fallback;
        try {
            const url = new URL(item.avatar_url, window.location.origin);
            return ['http:', 'https:'].includes(url.protocol)
                ? this.escapeHomeRankingText(url.href)
                : fallback;
        } catch (error) {
            return fallback;
        }
    }

    handleEntityAvatarFallback(image) {
        image.onerror = null;
        image.src = '/favicon.ico';
    }

    renderAvatarUploader(prefix, currentUrl = '') {
        const hasCustomAvatar = Boolean(currentUrl && currentUrl !== '/favicon.ico');
        const preview = hasCustomAvatar ? this.getEntityAvatar({ avatar_url: currentUrl }) : '/favicon.ico';
        return `
            <div class="avatar-upload-field" data-avatar-prefix="${prefix}">
                <input type="hidden" id="${prefix}-avatar-url" value="${hasCustomAvatar ? this.escapeHomeRankingText(currentUrl) : ''}">
                <input type="file" id="${prefix}-avatar-file" accept="image/jpeg,image/png,image/webp,image/gif,image/bmp" hidden>
                <button type="button" class="avatar-upload-preview" onclick="document.getElementById('${prefix}-avatar-file').click()" aria-label="选择并裁剪头像">
                    <img id="${prefix}-avatar-preview" src="${preview}" alt="头像预览" onerror="ui.handleEntityAvatarFallback(this)">
                    <span>选择图片</span>
                </button>
                <div class="avatar-upload-actions">
                    <button type="button" class="btn-link" onclick="document.getElementById('${prefix}-avatar-file').click()">上传并裁剪</button>
                    <button type="button" class="btn-link avatar-reset-button" onclick="ui.resetAvatarUpload('${prefix}')">恢复网页图标</button>
                    <small>正方形框选；保存后自动平滑缩放并压缩至 256 KiB 内。</small>
                </div>
            </div>
        `;
    }

    bindAvatarUploader(prefix) {
        const input = document.getElementById(`${prefix}-avatar-file`);
        if (!input) return;
        input.addEventListener('change', () => {
            const file = input.files?.[0];
            input.value = '';
            if (file) this.openAvatarCropper(prefix, file);
        });
    }

    resetAvatarUpload(prefix) {
        const hidden = document.getElementById(`${prefix}-avatar-url`);
        const preview = document.getElementById(`${prefix}-avatar-preview`);
        if (hidden) hidden.value = '';
        if (preview) preview.src = '/favicon.ico';
    }

    openAvatarCropper(prefix, file) {
        if (!file.type.startsWith('image/')) {
            this.showToast('请选择图片文件', 'error');
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            this.showToast('头像原图不能超过 10 MiB', 'error');
            return;
        }

        const objectUrl = URL.createObjectURL(file);
        const content = `
            <div class="avatar-crop-dialog">
                <p class="avatar-crop-hint">拖动画面调整位置，使用滑杆缩放；正方形框内区域会成为头像。</p>
                <div class="avatar-crop-viewport" id="avatar-crop-viewport">
                    <img id="avatar-crop-image" src="${objectUrl}" alt="待裁剪头像" draggable="false">
                    <span class="avatar-crop-frame" aria-hidden="true"></span>
                </div>
                <label class="avatar-crop-zoom">缩放
                    <input id="avatar-crop-zoom" type="range" min="1" max="4" step="0.01" value="1">
                </label>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.cancelAvatarCropper()">取消</button>
                    <button type="button" class="btn btn-primary" id="avatar-crop-confirm" onclick="ui.confirmAvatarCropper()">裁剪并上传</button>
                </div>
            </div>
        `;
        this.showModal('裁剪头像', content, true);
        this.avatarCropState = { prefix, file, objectUrl, x: 0, y: 0, zoom: 1, dragging: false };
        this.initializeAvatarCropper();
    }

    initializeAvatarCropper() {
        const state = this.avatarCropState;
        const viewport = document.getElementById('avatar-crop-viewport');
        const image = document.getElementById('avatar-crop-image');
        const zoom = document.getElementById('avatar-crop-zoom');
        if (!state || !viewport || !image || !zoom) return;

        const initializeImage = () => {
            state.naturalWidth = image.naturalWidth;
            state.naturalHeight = image.naturalHeight;
            state.baseScale = Math.max(viewport.clientWidth / image.naturalWidth, viewport.clientHeight / image.naturalHeight);
            state.x = 0;
            state.y = 0;
            this.updateAvatarCropTransform();
        };
        if (image.complete && image.naturalWidth) {
            initializeImage();
        } else {
            image.addEventListener('load', initializeImage, { once: true });
            image.addEventListener('error', () => {
                this.showToast('头像图片解码失败，请换用 JPEG、PNG 或 WebP 图片', 'error');
                this.releaseAvatarCropState();
                this.closeModal();
            }, { once: true });
        }
        zoom.addEventListener('input', () => {
            state.zoom = Number(zoom.value);
            this.updateAvatarCropTransform();
        });
        viewport.addEventListener('pointerdown', event => {
            state.dragging = true;
            state.pointerX = event.clientX;
            state.pointerY = event.clientY;
            viewport.setPointerCapture(event.pointerId);
        });
        viewport.addEventListener('pointermove', event => {
            if (!state.dragging) return;
            state.x += event.clientX - state.pointerX;
            state.y += event.clientY - state.pointerY;
            state.pointerX = event.clientX;
            state.pointerY = event.clientY;
            this.updateAvatarCropTransform();
        });
        const endDrag = () => { state.dragging = false; };
        viewport.addEventListener('pointerup', endDrag);
        viewport.addEventListener('pointercancel', endDrag);
    }

    updateAvatarCropTransform() {
        const state = this.avatarCropState;
        const viewport = document.getElementById('avatar-crop-viewport');
        const image = document.getElementById('avatar-crop-image');
        if (!state?.baseScale || !viewport || !image) return;

        const scale = state.baseScale * state.zoom;
        const width = state.naturalWidth * scale;
        const height = state.naturalHeight * scale;
        const maxX = Math.max(0, (width - viewport.clientWidth) / 2);
        const maxY = Math.max(0, (height - viewport.clientHeight) / 2);
        state.x = Math.max(-maxX, Math.min(maxX, state.x));
        state.y = Math.max(-maxY, Math.min(maxY, state.y));
        image.style.width = `${width}px`;
        image.style.height = `${height}px`;
        image.style.transform = `translate(calc(-50% + ${state.x}px), calc(-50% + ${state.y}px))`;
    }

    async confirmAvatarCropper() {
        const state = this.avatarCropState;
        const viewport = document.getElementById('avatar-crop-viewport');
        const button = document.getElementById('avatar-crop-confirm');
        if (!state || !viewport || !button) {
            this.showToast('头像裁剪器尚未准备好，请重新选择图片', 'error');
            return;
        }
        if (!state.baseScale) {
            this.showToast('头像仍在解码，请稍候再试', 'error');
            return;
        }

        button.disabled = true;
        button.textContent = '处理中…';
        try {
            const scale = state.baseScale * state.zoom;
            const sourceSide = viewport.clientWidth / scale;
            const centerX = state.naturalWidth / 2 - state.x / scale;
            const centerY = state.naturalHeight / 2 - state.y / scale;
            const sourceX = Math.max(0, Math.min(state.naturalWidth - sourceSide, centerX - sourceSide / 2));
            const sourceY = Math.max(0, Math.min(state.naturalHeight - sourceSide, centerY - sourceSide / 2));
            const canvas = document.createElement('canvas');
            canvas.width = 512;
            canvas.height = 512;
            const context = canvas.getContext('2d');
            if (!context) throw new Error('当前浏览器不支持头像裁剪');
            context.imageSmoothingEnabled = true;
            context.imageSmoothingQuality = 'high';
            const source = document.getElementById('avatar-crop-image');
            let imageSource;
            try {
                imageSource = await createImageBitmap(state.file, { imageOrientation: 'from-image' });
            } catch {
                throw new Error('头像图片解码失败，请换用 JPEG、PNG 或 WebP 图片');
            }
            try {
                context.drawImage(imageSource, sourceX, sourceY, sourceSide, sourceSide, 0, 0, canvas.width, canvas.height);
            } finally {
                imageSource.close();
            }
            let blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp', 0.88));
            if (!blob || blob.type !== 'image/webp') {
                blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
            }
            if (!blob) throw new Error('生成裁剪图片失败');
            state.abortController = new AbortController();
            const result = await api.processAvatar(blob, { signal: state.abortController.signal });
            state.abortController = null;
            const hidden = document.getElementById(`${state.prefix}-avatar-url`);
            const preview = document.getElementById(`${state.prefix}-avatar-preview`);
            if (hidden) hidden.value = result.avatar_url;
            if (preview) preview.src = `${result.avatar_url}?v=${Date.now()}`;
            this.releaseAvatarCropState();
            this.closeModal();
            this.showToast(`头像已处理（${Math.ceil(result.file_size / 1024)} KiB）`, 'success');
        } catch (error) {
            state.abortController = null;
            if (error.message === '头像上传已取消') return;
            this.showToast(`头像处理失败: ${error.message}`, 'error');
            button.disabled = false;
            button.textContent = '裁剪并上传';
        }
    }

    cancelAvatarCropper() {
        this.releaseAvatarCropState();
        this.closeModal();
    }

    releaseAvatarCropState() {
        this.avatarCropState?.abortController?.abort();
        if (this.avatarCropState?.objectUrl) URL.revokeObjectURL(this.avatarCropState.objectUrl);
        this.avatarCropState = null;
    }

    getHomeRankingAvatar(item) {
        const fallback = `https://q1.qlogo.cn/g?b=qq&nk=${encodeURIComponent(item.qq_number || '')}&s=100`;
        if (!item.avatar_url) return fallback;
        try {
            const url = new URL(item.avatar_url, window.location.origin);
            return ['http:', 'https:'].includes(url.protocol) ? this.escapeHomeRankingText(url.href) : fallback;
        } catch (error) {
            return fallback;
        }
    }

    renderHomeContributionRanking(items) {
        const container = document.getElementById('home-contribution-ranking');
        if (!container) return;
        if (!items.length) {
            container.innerHTML = '<div class="home-ranking-empty">还没有贡献记录</div>';
            return;
        }

        container.innerHTML = items.map((item, index) => {
            const avatar = this.getHomeRankingAvatar(item);
            return `
                <div class="home-ranking-row">
                    <span class="home-ranking-position">${index + 1}</span>
                    <img class="home-ranking-avatar" src="${avatar}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'">
                    <span class="home-ranking-name">${this.escapeHomeRankingText(item.nickname)}</span>
                    <strong>${item.score}<small>贡献</small></strong>
                </div>
            `;
        }).join('');
    }

    renderHomeRecentGroupRanking(items, days) {
        const container = document.getElementById('home-recent-group-ranking');
        if (!container) return;
        if (!items.length) {
            container.innerHTML = `<div class="home-ranking-empty">近 ${days} 天还没有新上传图片</div>`;
            return;
        }

        container.innerHTML = items.map((item, index) => `
            <div class="home-ranking-row">
                <span class="home-ranking-position">${index + 1}</span>
                <img class="home-ranking-avatar" src="${this.getEntityAvatar(item)}" alt="" loading="lazy" decoding="async" onerror="ui.handleEntityAvatarFallback(this)">
                <span class="home-ranking-name">${this.escapeHomeRankingText(item.name)}</span>
                <strong>${item.count}<small>张</small></strong>
            </div>
        `).join('');
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
                <img class="leaderboard-avatar" src="${this.getEntityAvatar(item)}" alt="" loading="lazy" decoding="async" onerror="ui.handleEntityAvatarFallback(this)">
                <div class="leaderboard-info">
                    <div class="leaderboard-name">${this.escapeHomeRankingText(item.name)}</div>
                    <div class="leaderboard-sub">${this.escapeHomeRankingText(item.group_name || '未分组')}</div>
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
                <img class="leaderboard-thumb" src="${this.getThumbnailUrl(item)}" alt="图片" loading="lazy" decoding="async" fetchpriority="low" onerror="ui.handleImageFallback(this)">
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
        
        // 再按名称、全拼、首字母或昵称筛选
        if (query) {
            filtered = window.PinyinSearch.filter(filtered, query, 'name');
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
            renderOption: (item) => `<div class="option-main">${this.escapeHomeRankingText(item.name)}</div>`,
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
                <div class="entity-list-main">
                    <img class="entity-avatar" src="${this.getEntityAvatar(character)}" alt="${this.escapeHomeRankingText(character.name)}的头像" loading="lazy" decoding="async" onerror="ui.handleEntityAvatarFallback(this)">
                    <div class="list-item-info">
                        <div class="list-item-name">${this.escapeHomeRankingText(character.name)}</div>
                        <div class="list-item-description">
                            分组: ${this.escapeHomeRankingText(character.group_name || '未分组')}
                            ${character.nicknames && character.nicknames.length ? ` | 昵称: ${this.escapeHomeRankingText(character.nicknames.join(' / '))}` : ''}
                            ${character.feature_tags && character.feature_tags.length ? ` | 特征: ${this.escapeHomeRankingText(character.feature_tags.map(tag => tag.name).join(' / '))}` : ''}
                        </div>
                    </div>
                </div>
                <div class="list-item-actions">
                    ${window.auth.isRoot()?`<button class="action-btn" onclick="managePixivMappings('character',${character.id})">Pixiv 标签</button>`:''}<button class="action-btn edit" onclick="ui.editCharacter(${character.id})">编辑</button>
                    <button class="action-btn delete" onclick="ui.deleteCharacter(${character.id})">删除</button>
                </div>
            </div>
        `).join('');
    }

    async loadFeatureTags() {
        const tags = await this.loadFeatureTagsData();
        this.renderFeatureTagList(tags);
    }

    filterFeatureTags(query) {
        const source = this.allFeatureTags || [];
        const q = String(query || '').trim().toLowerCase();
        const filtered = !q
            ? source
            : window.PinyinSearch.filter(source, query, 'name');
        this.renderFeatureTagList(filtered);
    }

    renderFeatureTagList(tags) {
        const container = document.getElementById('feature-tag-list');
        if (!container) return;
        if (!tags.length) {
            container.innerHTML = '<div class="empty-state">暂无特征标签</div>';
            return;
        }
        container.innerHTML = tags.map(tag => `
            <div class="list-item">
                <div class="list-item-info">
                    <div class="list-item-name">${this.escapeHomeRankingText(tag.name)}</div>
                    <div class="list-item-description">
                        ${this.escapeHomeRankingText(tag.description || '无描述')}
                        ${tag.aliases && tag.aliases.length ? ` | 别称: ${this.escapeHomeRankingText(tag.aliases.join(' / '))}` : ''}
                    </div>
                </div>
                <div class="list-item-actions">
                    ${window.auth.isRoot()?`<button class="action-btn" onclick="managePixivMappings('feature',${tag.id})">Pixiv 标签</button>`:''}
                    <button class="action-btn edit" onclick="ui.editFeatureTag(${tag.id})">编辑</button>
                    <button class="action-btn delete" onclick="ui.deleteFeatureTag(${tag.id})">删除</button>
                </div>
            </div>
        `).join('');
    }

    async updateTempCount() {
        if (!this.isAdminView()) {
            const badge = document.getElementById('temp-count-badge');
            const countSpan = document.getElementById('temp-image-count');
            if (badge) badge.style.display = 'none';
            if (countSpan) countSpan.textContent = '0';
            return;
        }

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
            const avatar = document.createElement('img');
            avatar.className = 'orbit-chip-avatar';
            avatar.src = this.getEntityAvatar(group);
            avatar.alt = '';
            avatar.loading = 'lazy';
            avatar.onerror = () => this.handleEntityAvatarFallback(avatar);
            const label = document.createElement('span');
            label.className = 'orbit-chip-label';
            label.textContent = group.image_count > 0
                ? `${group.name} · ${group.image_count}张`
                : group.name;
            chip.append(avatar, label);
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
            const homeEmojis = document.getElementById('home-total-emojis');
            const homeGroups = document.getElementById('home-total-groups');
            const homeCharacters = document.getElementById('home-total-characters');
            if (homeImages) homeImages.textContent = status.total_images;
            if (homeEmojis) homeEmojis.textContent = status.total_emojis || 0;
            if (homeGroups) homeGroups.textContent = status.total_groups;
            if (homeCharacters) homeCharacters.textContent = status.total_characters;
            
            const statImages = document.getElementById('stat-images');
            const statGroups = document.getElementById('stat-groups');
            const statCharacters = document.getElementById('stat-characters');
            if (statImages) statImages.textContent = status.total_images;
            if (statGroups) statGroups.textContent = status.total_groups;
            if (statCharacters) statCharacters.textContent = status.total_characters;

            if (this.currentPage === 'settings' && this.isAdminView()) {
                await this.loadSystemDiagnostics();
            }
        } catch (error) {
            this.showToast('加载页面数据失败', 'error');
        }
    }

    async loadSystemDiagnostics() {
        try {
            const status = await api.getSystemDiagnostics();
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
            refreshPixivCheckQueue();
        } catch (error) {
            console.error('加载系统诊断失败:', error);
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

    parseAliasInput(elementId) {
        const element = document.getElementById(elementId);
        return element
            ? element.value.split(',').map(item => item.trim()).filter(Boolean)
            : [];
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
                    <label for="group-aliases">分组别称</label>
                    <input type="text" id="group-aliases" class="form-input" placeholder="多个别称用英文逗号分隔">
                </div>
                <div class="form-group">
                    <label>分组头像</label>
                    ${this.renderAvatarUploader('group')}
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
        this.bindAvatarUploader('group');
    }

    async createGroup(isNested = false) {
        try {
            const data = {
                name: document.getElementById('group-name').value,
                aliases: this.parseAliasInput('group-aliases'),
                avatar_url: document.getElementById('group-avatar-url').value || null,
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
            const featureTags = await api.getFeatureTags();
            const groupOptions = groups.map(group => 
                `<option value="${group.id}">${this.escapeHomeRankingText(group.name)}</option>`
            ).join('');
            
            const content = `
                <form id="create-character-form" onsubmit="event.preventDefault(); ui.createCharacter(${isNested});">
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
                        <label>角色头像</label>
                        ${this.renderAvatarUploader('character')}
                    </div>
                    <div class="form-group">
                        <label>特征标签</label>
                        <div id="create-character-feature-selector"></div>
                        <button type="button" class="btn-link" onclick="ui.showCreateFeatureTagModal(true)">添加特征</button>
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
            const featureSelector = new ImageTagSelector('create-character-feature-selector', {
                title: '选择角色特征标签',
                allowedTypes: ['feature_tag']
            });
            window.imageTagSelectors['create-character-feature-selector'] = featureSelector;
            featureSelector.setData({ groups: [], characters: [], featureTags });
            this.bindAvatarUploader('character');

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
                feature_tag_ids: window.imageTagSelectors['create-character-feature-selector']
                    ? window.imageTagSelectors['create-character-feature-selector'].getValue().feature_tag_ids
                    : [],
                avatar_url: document.getElementById('character-avatar-url').value || null,
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
    showCreateFeatureTagModal(isNested = false) {
        const content = `
            <form id="create-feature-tag-form">
                <div class="form-group">
                    <label for="feature-tag-name">特征名称</label>
                    <input type="text" id="feature-tag-name" class="form-input" required>
                </div>
                <div class="form-group">
                    <label for="feature-tag-aliases">特征别称</label>
                    <input type="text" id="feature-tag-aliases" class="form-input" placeholder="多个别称用英文逗号分隔">
                </div>
                <div class="form-group">
                    <label for="feature-tag-description">备注</label>
                    <textarea id="feature-tag-description" class="form-textarea"></textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        this.showModal('添加特征标签', content, isNested);
        document.getElementById('create-feature-tag-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.createFeatureTag(isNested);
        });
    }

    async createFeatureTag(isNested = false) {
        try {
            const tag = await api.createFeatureTag({
                name: document.getElementById('feature-tag-name').value,
                aliases: this.parseAliasInput('feature-tag-aliases'),
                description: document.getElementById('feature-tag-description').value || null
            });
            this.invalidateCache('featureTags');
            await this.loadFeatureTagsData(true);
            this.showToast('特征标签创建成功', 'success');
            this.closeModal();
            this.loadFeatureTags();
            this.updateUploadOptions();
            if (isNested && tag && tag.id) {
                await this.refreshModalSelectors(tag.id, 'feature_tag');
            }
            return tag;
        } catch (error) {
            this.showToast(`创建特征标签失败: ${error.message}`, 'error');
        }
    }

    async editFeatureTag(tagId) {
        const tags = await this.loadFeatureTagsData();
        const tag = tags.find(item => item.id === tagId);
        if (!tag) return;
        const content = `
            <form id="edit-feature-tag-form">
                <div class="form-group">
                    <label for="edit-feature-tag-name">特征名称</label>
                    <input type="text" id="edit-feature-tag-name" class="form-input" value="${this.escapeHomeRankingText(tag.name)}" required>
                </div>
                <div class="form-group">
                    <label for="edit-feature-tag-aliases">特征别称</label>
                    <input type="text" id="edit-feature-tag-aliases" class="form-input" value="${this.escapeHomeRankingText((tag.aliases || []).join(', '))}" placeholder="多个别称用英文逗号分隔">
                </div>
                <div class="form-group">
                    <label for="edit-feature-tag-description">备注</label>
                    <textarea id="edit-feature-tag-description" class="form-textarea">${this.escapeHomeRankingText(tag.description || '')}</textarea>
                </div>
                <div class="form-actions">
                    <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                    <button type="submit" class="btn btn-primary">保存</button>
                </div>
            </form>
        `;
        this.showModal('编辑特征标签', content);
        window.PicManagerShell.enhanceTagEditor('edit-feature-tag-form','feature',tagId);
        document.getElementById('edit-feature-tag-form').addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.updateFeatureTag(tagId);
        });
    }

    async updateFeatureTag(tagId) {
        try {
            await api.updateFeatureTag(tagId, {
                name: document.getElementById('edit-feature-tag-name').value,
                aliases: this.parseAliasInput('edit-feature-tag-aliases'),
                description: document.getElementById('edit-feature-tag-description').value || null
            });
            this.invalidateCache('featureTags');
            this.showToast('特征标签更新成功', 'success');
            this.closeModal();
            await this.loadFeatureTagsData(true);
            this.loadFeatureTags();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`更新特征标签失败: ${error.message}`, 'error');
        }
    }

    async deleteFeatureTag(tagId) {
        if (!confirm('确定要删除这个特征标签吗？')) return;
        try {
            await api.deleteFeatureTag(tagId);
            this.invalidateCache('featureTags');
            this.showToast('特征标签删除成功', 'success');
            await this.loadFeatureTagsData(true);
            this.loadFeatureTags();
            this.updateUploadOptions();
        } catch (error) {
            this.showToast(`删除特征标签失败: ${error.message}`, 'error');
        }
    }

    async editGroup(groupId) {
        try {
            const group = await this.loadGroupsData(true);
            const currentGroup = group.find(g => g.id === groupId);
            
            if (!currentGroup) {
                this.showToast('分组不存在', 'error');
                return;
            }
            
            const content = `
                <form id="edit-group-form">
                    <div class="form-group">
                        <label for="edit-group-name">分组名称</label>
                        <input type="text" id="edit-group-name" class="form-input" value="${this.escapeHomeRankingText(currentGroup.name)}" required>
                    </div>
                    <div class="form-group">
                        <label for="edit-group-aliases">分组别称</label>
                        <input type="text" id="edit-group-aliases" class="form-input" value="${this.escapeHomeRankingText((currentGroup.aliases || []).join(', '))}" placeholder="多个别称用英文逗号分隔">
                    </div>
                    <div class="form-group">
                        <label>分组头像</label>
                        ${this.renderAvatarUploader('edit-group', currentGroup.avatar_url)}
                    </div>
                    <div class="form-group">
                        <label for="edit-group-description">备注</label>
                        <textarea id="edit-group-description" class="form-textarea">${this.escapeHomeRankingText(currentGroup.description || '')}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑分组', content);
            window.PicManagerShell.enhanceTagEditor('edit-group-form','group',groupId);
            
            document.getElementById('edit-group-form').addEventListener('submit', async (e) => {
                e.preventDefault();
                await this.updateGroup(groupId);
            });
            this.bindAvatarUploader('edit-group');
        } catch (error) {
            this.showToast(`加载分组信息失败: ${error.message}`, 'error');
        }
    }
    
    async updateGroup(groupId) {
        try {
            const data = {
                name: document.getElementById('edit-group-name').value,
                aliases: this.parseAliasInput('edit-group-aliases'),
                avatar_url: document.getElementById('edit-group-avatar-url').value || null,
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
            const [characters,groups,featureTags] = await Promise.all([this.loadCharactersData(true),this.loadGroupsData(true),this.loadFeatureTagsData(true)]);
            const currentCharacter = characters.find(c => c.id === characterId);
            
            if (!currentCharacter) {
                this.showToast('角色不存在', 'error');
                return;
            }
            
            const groupOptions = groups.map(group => 
                `<option value="${group.id}" ${group.id === currentCharacter.group_id ? 'selected' : ''}>${this.escapeHomeRankingText(group.name)}</option>`
            ).join('');
            const selectedFeatureIds = currentCharacter.feature_tag_ids || (currentCharacter.feature_tags || []).map(tag => tag.id);
            
            const content = `
                <form id="edit-character-form" onsubmit="event.preventDefault(); ui.updateCharacter(${characterId});">
                    <div class="form-group">
                        <label for="edit-character-name">角色名称</label>
                        <input type="text" id="edit-character-name" class="form-input" value="${this.escapeHomeRankingText(currentCharacter.name)}" required>
                    </div>
                    <div class="form-group">
                        <label for="edit-character-group">所属分组</label>
                        <select id="edit-character-group" class="form-select" required>
                            ${groupOptions}
                        </select>
                    </div>
                    <div class="form-group">
                        <label for="edit-character-nicknames">角色昵称</label>
                        <input type="text" id="edit-character-nicknames" class="form-input" value="${this.escapeHomeRankingText((currentCharacter.nicknames || []).join(', '))}" placeholder="多个昵称用英文逗号分隔">
                    </div>
                    <div class="form-group">
                        <label>角色头像</label>
                        ${this.renderAvatarUploader('edit-character', currentCharacter.avatar_url)}
                    </div>
                    <div class="form-group">
                        <label>特征标签</label>
                        <div id="edit-character-feature-selector"></div>
                        <button type="button" class="btn-link" onclick="ui.showCreateFeatureTagModal(true)">添加特征</button>
                    </div>
                    <div class="form-group">
                        <label for="edit-character-description">备注</label>
                        <textarea id="edit-character-description" class="form-textarea">${this.escapeHomeRankingText(currentCharacter.description || '')}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑角色', content);
            window.PicManagerShell.enhanceTagEditor('edit-character-form','character',characterId);
            const featureSelector = new ImageTagSelector('edit-character-feature-selector', {
                title: '选择角色特征标签',
                allowedTypes: ['feature_tag']
            });
            window.imageTagSelectors['edit-character-feature-selector'] = featureSelector;
            featureSelector.setData({ groups: [], characters: [], featureTags });
            featureSelector.setSelected({ group_ids: [], character_ids: [], feature_tag_ids: selectedFeatureIds });
            this.bindAvatarUploader('edit-character');
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
                feature_tag_ids: window.imageTagSelectors['edit-character-feature-selector']
                    ? window.imageTagSelectors['edit-character-feature-selector'].getValue().feature_tag_ids
                    : [],
                avatar_url: document.getElementById('edit-character-avatar-url').value || null,
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

    renderDetailChips(items, type, fallback = '无') {
        const list = items || [];
        if (!list.length) return `<span class="detail-chip detail-chip-muted">${fallback}</span>`;
        return list.map(item => `
            <span class="detail-chip detail-chip-${type}">
                <span>${this.escapeHomeRankingText(item.name)}</span>
                ${item.group_name && type === 'character' ? `<small>${this.escapeHomeRankingText(item.group_name)}</small>` : ''}
            </span>
        `).join('');
    }

    renderImageMeta(image, compact = false) {
        const size = image.file_size ? `${(image.file_size / 1024 / 1024).toFixed(2)} MB` : '未知';
        const resolution = image.width && image.height ? `${image.width} x ${image.height}` : '未知';
        return [
            ['图片编号', image.image_id],
            ['原始文件', image.original_filename || '未知'],
            ['文件大小', size],
            ['分辨率', resolution],
            ['年龄分级', image.age_rating === 'all' ? '全年龄' : String(image.age_rating || 'all').toUpperCase()],
            ['PID', image.pid || '无'],
            ['画师', image.artist?.name || '未校验'],
            ['Pixiv 标签', (image.pixiv_tags || []).map(tag=>tag.translated_name || tag.name).join(' · ') || '无'],
            ['创建时间', new Date(image.created_at).toLocaleString()]
        ].filter(([label]) => !compact || !['画师', 'Pixiv 标签'].includes(label)).map(([label, value]) => `
            <div class="detail-meta-item">
                <span>${label}</span>
                <strong>${label==='画师'&&image.artist?`<button type="button" class="px-text-button" data-artist="${this.escapeHomeRankingText(image.artist.id)}" onclick="ui.showArtistImages(this.dataset.artist)">${this.escapeHomeRankingText(value)}</button>`:this.escapeHomeRankingText(value)}</strong>
            </div>
        `).join('');
    }

    showArtistImages(artist) {
        this.closeImageDetail(false);
        this.closeModal();this.pagination.currentPage=1;this.switchPage('management');
        const field=document.getElementById('search-artist');if(field)field.value=artist;
        this.loadImages({artist});
    }
    
    // 图片编辑和删除
    async editImage(imageId) {
        try {
            const [image, groups, characters, featureTags] = await Promise.all([
                api.getImage(imageId),
                api.getGroups(),
                api.getCharacters(),
                api.getFeatureTags()
            ]);
            const pixiv = await auth.loadFeature('pixiv');
            await auth.loadStyle('/static/css/pixiv-ol.css?v=20261004l');
            const rawTags = (image.pixiv_tags || []).filter(tag => tag && tag.name);
            let mappings = [], mappingError = '';
            if (rawTags.length) {
                try {
                    mappings = await api.request('/pixiv-ol/tag-mappings');
                    if (!Array.isArray(mappings)) throw new Error('Invalid mappings');
                }
                catch (_) { mappings = []; mappingError = '关联记录暂时无法加载，图片标签仍可编辑。'; }
            }
            const draft = {
                group_ids: (image.groups || []).map(group => group.id),
                character_ids: (image.characters || []).map(character => character.id),
                feature_tag_ids: (image.feature_tags || []).map(tag => tag.id)
            };
            const normalize = value => String(value).normalize('NFKC').trim().toLocaleLowerCase();
            const evidence = rawTags.flatMap(tag => {
                const candidates = mappings.filter(row => normalize(row.tag) === normalize(tag.name) && row.target_type !== 'ignore');
                const selected = candidates.find(row => draft[`${row.target_type === 'feature' ? 'feature_tag' : row.target_type}_ids`]?.includes(row.target_id));
                const mapping = selected || candidates[0];
                return mapping ? [{pixiv_tag:tag.name, type:mapping.target_type, id:mapping.target_id}] : [];
            });
            
            const content = `
                <form id="edit-image-form" onsubmit="event.preventDefault(); ui.updateImage('${imageId}');">
                    <div class="image-edit-intro"><img src="${this.getThumbnailUrl(image)}" alt="" onerror="ui.handleImageFallback(this)"><div><strong>${this.escapeHomeRankingText(image.pid || image.image_id)}</strong><p>确认图片的分组、角色与特征</p></div></div>
                    <section class="image-edit-section">
                        <h4>图片标签</h4>
                        <div id="edit-image-tag-selector"></div>
                        <div class="px-legacy-tags" hidden></div>
                    </section>
                    <section class="image-edit-section image-edit-pixiv" ${rawTags.length ? '' : 'hidden'}>
                        <h4>Pixiv 原始标签</h4><p class="image-edit-hint">点击标签或拖到上方已选标签，建立可复用的关联。</p>
                        <div class="px-source-tags"></div><p class="px-tag-feedback" role="status"></p>
                    </section>
                    <div class="image-edit-fields">
                    <div class="form-group">
                        <label for="edit-image-pid">PID</label>
                        <input type="text" id="edit-image-pid" class="form-input" value="${this.escapeHomeRankingText(image.pid || '')}">
                    </div>
                    <div class="form-group">
                        <label for="edit-image-age-rating">年龄分级</label>
                        <select id="edit-image-age-rating" class="form-select">
                            ${['all', 'r12', 'r16', 'r18'].map(value => `<option value="${value}" ${value === (image.age_rating || 'all') ? 'selected' : ''}>${value === 'all' ? '全年龄' : value.toUpperCase()}</option>`).join('')}
                        </select>
                    </div>
                    </div>
                    <div class="form-group">
                        <label for="edit-image-description">备注</label>
                        <textarea id="edit-image-description" class="form-textarea" rows="3">${this.escapeHomeRankingText(image.description || '')}</textarea>
                    </div>
                    <div class="form-actions">
                        <button type="button" class="btn btn-secondary" onclick="ui.closeModal()">取消</button>
                        <button type="submit" class="btn btn-primary">保存</button>
                    </div>
                </form>
            `;
            
            this.showModal('编辑图片', content);
            const layer = document.querySelector('#modal-body > .modal-layer:last-child');
            const editor = pixiv.cartTagEditor(layer, {tags:rawTags,match:{evidence}}, draft, {
                selectorId:'edit-image-tag-selector', title:'编辑图片标签', data:{groups,characters,featureTags}
            });
            layer._onModalClose = () => editor.destroy();
            if (mappingError) layer.querySelector('.px-tag-feedback').textContent = mappingError;
            
        } catch (error) {
            this.showToast(`加载图片信息失败: ${error.message}`, 'error');
        }
    }
    
    async updateImage(imageId) {
        try {
            const selectedTags = window.imageTagSelectors['edit-image-tag-selector']
                ? window.imageTagSelectors['edit-image-tag-selector'].getValue()
                : { group_ids: [], character_ids: [], feature_tag_ids: [] };
            const selectedCharacters = selectedTags.character_ids || [];
            
            if (selectedCharacters.length === 0) {
                this.showToast('请选择至少一个角色', 'error');
                return;
            }
            if ((selectedTags.group_ids || []).length === 0) {
                this.showToast('请至少添加一个分组标签', 'error');
                return;
            }
            
            const data = {
                character_ids: selectedCharacters,
                group_ids: selectedTags.group_ids || [],
                feature_tag_ids: selectedTags.feature_tag_ids || [],
                age_rating: document.getElementById('edit-image-age-rating')?.value || 'all',
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
            if (this.libraryReader?.dataset.imageId === imageId) this.closeImageDetail();
            this.closeModal();
            this.loadImages(null);
            this.loadSystemStatus();
        } catch (error) {
            this.showToast(`删除图片失败: ${error.message}`, 'error');
        }
    }

    async showImageDetail(imageId, source = null) {
        return this.openLibraryReader(imageId, source);
    }

    toggleDetailAgeReveal(button) {
        const media = button.closest('.image-detail-media');
        if (!media) return;
        const reveal = !media.classList.contains('age-revealed');
        media.classList.toggle('age-revealed', reveal);
        media.dataset.ageRevealed = String(reveal);
        const rating = media.classList.contains('is-r18') ? 'R18' : 'R16';
        button.setAttribute('aria-expanded', String(reveal));
        button.textContent = reveal ? `隐藏 ${rating} 内容` : `揭示 ${rating} 内容`;
        const original = media.querySelector('.image-detail-original');
        if (reveal && original?.dataset.sensitiveSrc) {
            media.classList.remove('is-original-loaded', 'is-original-error');
            media.querySelector('.library-preview-loader')?.removeAttribute('hidden');
            original.onerror = () => this.handleOriginalError(original);
            original.src = original.dataset.sensitiveSrc;
            delete original.dataset.sensitiveSrc;
        }
        const downloadButton = media.closest('.image-detail-card')?.querySelector('.detail-protected-download');
        if (downloadButton) {
            downloadButton.disabled = !reveal;
            downloadButton.title = reveal ? '' : '请先揭示受限内容';
        }
    }
}

// 全局函数
function searchImages() {
    ui.pagination.currentPage = 1;
    ui.loadImages(ui.getSearchParams());
}

function setAgeRatingFilter(rating, activeButton) {
    const input = document.getElementById('search-age-rating');
    if (input) input.value = rating || '';
    document.querySelectorAll('.age-filter-tab').forEach(button => {
        const active = button === activeButton;
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', String(active));
    });
    window.queryPanels?.update('image-search-panel');
    searchImages();
}

function clearSearch() {
    // 清空所有搜索条件
    document.getElementById('search-group-input').value = '';
    document.getElementById('search-group').value = '';
    document.getElementById('search-character-input').value = '';
    document.getElementById('search-character').value = '';
    document.getElementById('search-pid').value = '';
    if(document.getElementById('search-artist'))document.getElementById('search-artist').value='';
    const ageRatingInput = document.getElementById('search-age-rating');
    if (ageRatingInput) ageRatingInput.value = '';
    document.querySelectorAll('.age-filter-tab').forEach(button => {
        const active = button.dataset.ageRating === '';
        button.classList.toggle('active', active);
        button.setAttribute('aria-selected', String(active));
    });
    
    const imageIdInput = document.getElementById('search-image-id');
    if (imageIdInput) imageIdInput.value = '';
    
    // 重置角色过滤
    ui.filteredCharacters = ui.allCharacters;
    ui.renderCharacterDropdown();
    
    // 重新加载图片
    ui.pagination.currentPage = 1;
    ui.activeImageSearchParams = {};
    window.queryPanels?.update('image-search-panel');
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
        if (ui.currentPage === 'home') {
            ui.loadHomeGroupChips();
            ui.loadHomeRankings();
        }
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

async function deleteInvalidRecords() {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }
    try {
        const preview = await api.cleanupPreview();
        const count = Number(preview.missing_records || 0);
        if (count === 0) {
            ui.showToast('没有可删除的档案', 'info');
            return;
        }
        const message = [
            `将永久删除 ${count} 条没有原图的档案记录。`,
            '相关浏览计数和重复比对记录也会删除。',
            '',
            '此操作无法恢复，确认继续吗？'
        ].join('\n');
        if (!confirm(message)) return;

        const result = await api.cleanupOrphaned('delete');
        ui.showToast(`已删除 ${result.count} 条档案`, 'success');
        ui.loadImages(null);
        ui.loadSystemStatus();
    } catch (error) {
        ui.showToast(`删除失败: ${error.message}`, 'error');
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

async function scanExistingDuplicates(localValidation=false) {
    if (!ui.isAdminView()) {
        ui.showToast('只有管理员可以执行维护操作', 'warning');
        return;
    }

    const button = document.getElementById('scan-duplicates-button');
    if (button?.disabled) return;
    let deleted = 0;
    let distinguished = 0;
    let deferred = 0;
    let scanned = 0;
    const excludedPairs = [];
    try {
        if (button) {
            button.disabled = true;
            button.textContent = '检查中…';
        }
        const uploadFeature = await window.auth.loadFeature('upload');
        while (true) {
            if (localValidation && window.localValidationStop) return {status:'stopped',deferred};
            const result = await api.scanExistingDuplicates(25, excludedPairs, localValidation);
            scanned = Math.max(scanned, Number(result.scanned_images || 0));
            const groups = result.groups || [];
            if (groups.length === 0) break;

            for (const group of groups) {
                if (localValidation && window.localValidationStop) return {status:'stopped',deferred};
                const decision = await uploadFeature.resolveDuplicateChoice({
                    duplicates: group.images || [],
                });
                if (localValidation && window.localValidationStop) return {status:'stopped',deferred};
                if (!decision) {
                    ui.showToast(`已停止；本次删除 ${deleted} 份重复文件`, 'info');
                    return {status:'stopped',deferred};
                }
                if (decision.action === 'later') {
                    excludedPairs.push(group.image_ids || []);
                    deferred += 1;
                    continue;
                }
                const resolved = await api.resolveExistingDuplicates(
                    group.image_ids || [],
                    decision.action,
                    decision.keep || null,
                    decision.metadataSources || {},
                );
                deleted += Number(resolved.deleted ?? resolved.archived ?? 0);
                if (decision.action === 'distinct') distinguished += 1;
            }
        }

        ui.showToast(
            `查重完成：扫描 ${scanned} 张，删除 ${deleted} 份，保存 ${distinguished} 对，暂缓 ${deferred} 对`,
            'success'
        );
        ui.loadImages(null);
        ui.loadSystemStatus();
        return {status:'complete',deferred,deleted,distinguished};
    } catch (error) {
        ui.showToast(`重复比对失败: ${error.message}`, 'error');return {status:'error',message:error.message};
    } finally {
        if (button) {
            button.disabled = false;
            button.textContent = '查重';
        }
    }
}

function escapeMaintenanceHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[character]);
}

function formatMaintenanceBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '—';
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function reviewPixivCheck(result, onConfirm=null) {
    await window.auth.loadStyle('/static/css/pixiv-ol.css?v=20261004l');
    if(result.queue_processing&&(window.pixivValidationStop||ui.currentPage!=='settings'||!ui.isAdminView()))return null;
    return new Promise(resolve=>{
        const safe=value=>ui.escapeHomeRankingText(value??'');
        const autoAllowed=result.auto_review_safe&&result.artwork.page_count===1;const art=result.artwork, pages=Array.from({length:Math.min(art.page_count,1000)},(_,index)=>index);
        const dialog=document.createElement('dialog');dialog.className='px-dialog px-reader px-check-reader';
        dialog.innerHTML=`<button class="px-icon-button px-dialog-close" aria-label="关闭" data-close>×</button><div class="px-detail-cover"><img alt="校验作品原图"><button class="px-reader-arrow px-reader-prev" aria-label="上一页">‹</button><button class="px-reader-arrow px-reader-next" aria-label="下一页">›</button><span class="px-reader-status"></span></div><div class="px-detail-body"><h3>${safe(art.title)}</h3><p>画师 · ${safe(art.author)}</p><p>当前车牌 · ${safe(result.current.pid)}</p><div class="px-tags">${art.tags.map(tag=>`<span>${safe(tag.translated_name||tag.name)}</span>`).join('')}</div><div class="px-reader-pagination"><button class="px-button" data-view-local>查看库内原图</button><select data-view-page aria-label="查看 Pixiv 页码">${pages.map(page=>`<option value="${page}">第 ${page+1} 页</option>`).join('')}</select></div><label>库内现图对应哪一页<select data-current-page required><option value="">请确认对应页</option>${pages.map(page=>`<option value="${page}">${art.pid}_p${page} · 第 ${page+1} 页</option>`).join('')}</select></label><p class="px-help">保留库内现图，并补全车牌、画师和 Pixiv 来源标签。勾选其他页可补入库，沿用现图的分组与标签；已入库的页会自动跳过。</p><div class="px-pages">${pages.map(page=>`<label><input type="checkbox" data-extra-page value="${page}" ${result.imported_pages.includes(page)?'disabled':''}><button class="px-text-button" data-page="${page}">第 ${page+1} 页${result.imported_pages.includes(page)?' · 已入库':''}</button></label>`).join('')}</div><label><input type="checkbox" data-upgrade ${pixivAutoReviewEnabled&&autoAllowed?'checked':''}>匹配内容且存在高清版本时替换现图</label><label class="px-check-auto"><input type="checkbox" data-auto-choice ${autoAllowed?'':'disabled'} ${pixivAutoReviewEnabled&&autoAllowed?'checked':''}>自动审核 · 加载完成后 10 秒确认</label><p class="px-help" data-auto-status>${autoAllowed?'可取消倒计时或修改选择，页面隐藏时暂停。':'多页或对应关系不明确，需手动确认。'}</p><p class="px-error" role="alert" data-error></p><div class="px-dialog-actions"><button class="px-button" data-defer>稍后确认</button><button class="px-button px-primary" data-confirm>确认校验</button></div></div>`;
        dialog.querySelector('.px-detail-body').prepend(dialog.querySelector('[data-close]'));
        document.body.appendChild(dialog);dialog.showModal();
        const image=dialog.querySelector('img'), status=dialog.querySelector('.px-reader-status');
        const view=dialog.querySelector('[data-view-page]'), current=dialog.querySelector('[data-current-page]');let page=0,previewReady=false,autoTimer=null,seconds=10,settled=false,submitting=false;
        const matchNote=({preview_failed:'自动比对预览失败，请手动对照库内图片选择对应页。',
            ambiguous:'多页外观高度相似，无法唯一判断，请手动选择对应页。',
            no_match:'未找到可靠的页码匹配，请手动选择对应页。'})[result.page_matching?.status];
        if(matchNote){const note=document.createElement('p');note.className='px-help';note.textContent=matchNote;current.parentElement.after(note);}
        const auto=dialog.querySelector('[data-auto-choice]'),autoStatus=dialog.querySelector('[data-auto-status]');
        const showPage=value=>{
            previewReady=false;stopAuto();
            page=Math.max(0,Math.min(pages.length-1,value));view.value=String(page);
            status.textContent=`第 ${page+1} 页 · 正在加载原图…`;
            image.onload=()=>{status.textContent=`第 ${page+1} / ${pages.length} 页 · Pixiv 原图`;previewReady=true;startAuto();};
            image.onerror=()=>status.textContent='原图加载失败，可重选页码重试';
            image.src=`/api/system/pixiv-check/${result.review_id}/original?page=${page}`;
            dialog.querySelector('.px-reader-prev').disabled=page===0;dialog.querySelector('.px-reader-next').disabled=page===pages.length-1;
        };
        const finish=choice=>{if(settled||submitting)return;settled=true;stopAuto();window.cancelPixivCheckReview=null;dialog.close();dialog.remove();resolve(choice);};
        const stopAuto=()=>{clearInterval(autoTimer);autoTimer=null;seconds=10;};
        const startAuto=()=>{stopAuto();if(settled||!autoAllowed||!auto.checked||!previewReady)return;autoStatus.textContent='10 秒后确认，可随时取消自动审核';autoTimer=setInterval(()=>{if(window.pixivValidationStop){finish(null);return;}if(document.hidden){autoStatus.textContent='页面隐藏，倒计时已暂停';return;}seconds--;autoStatus.textContent=`${seconds} 秒后确认`;if(seconds<=0)dialog.querySelector('[data-confirm]').click();},1000);};
        auto.onchange=()=>{if(auto.checked)startAuto();else{stopAuto();autoStatus.textContent='已取消自动审核';}};
        dialog.addEventListener('change',event=>{if(event.target===auto)return;stopAuto();auto.checked=false;autoStatus.textContent='选择已修改，请手动确认';});
        window.cancelPixivCheckReview=()=>finish(null);
        dialog.querySelector('[data-close]').onclick=()=>finish(null);
        if(result.queue_processing)dialog.querySelector('[data-defer]').textContent='稍后处理，下一张';
        dialog.querySelector('[data-defer]').onclick=()=>finish(result.queue_processing?{deferred:true}:null);
        dialog.addEventListener('cancel',event=>{event.preventDefault();finish(null);});
        dialog.querySelector('.px-reader-prev').onclick=()=>showPage(page-1);
        dialog.querySelector('.px-reader-next').onclick=()=>showPage(page+1);
        view.onchange=()=>showPage(Number(view.value));
        dialog.querySelectorAll('[data-page]').forEach(node=>node.onclick=()=>showPage(Number(node.dataset.page)));
        dialog.querySelector('[data-view-local]').onclick=()=>{stopAuto();auto.checked=false;autoStatus.textContent='正在查看库内图片，请手动确认';image.onload=()=>status.textContent='库内现图 · 原图';image.src=result.current.preview_url;};
        const updateSelection=()=>dialog.querySelectorAll('[data-extra-page]').forEach(node=>{
            node.disabled=result.imported_pages.includes(Number(node.value))||(current.value!==''&&node.value===current.value);
            if(node.disabled) node.checked=false;
        });
        current.value=result.suggested_page==null?'':String(result.suggested_page);
        current.onchange=()=>{updateSelection();if(current.value!=='')showPage(Number(current.value));};updateSelection();
        dialog.querySelector('[data-confirm]').onclick=async()=>{
            if(submitting)return;
            const selected=Array.from(dialog.querySelectorAll('[data-extra-page]:checked'),node=>Number(node.value));
            const error=dialog.querySelector('[data-error]');
            if(current.value===''){error.textContent='请先确认库内现图对应的页码';return;}
            if(selected.length>100){error.textContent='每次最多补入 100 页';return;}
            if(selected.length&&!result.current.group_ids.length){error.textContent='请先为库内现图设置分组，再补入其他页';return;}
            const choice={review_id:result.review_id,current_page:Number(current.value),pages:selected,upgrade:dialog.querySelector('[data-upgrade]').checked};
            if(!onConfirm){finish(choice);return;}
            stopAuto();auto.checked=false;submitting=true;error.textContent='';
            const controls=Array.from(dialog.querySelectorAll('button,input,select'),node=>[node,node.disabled]);
            controls.forEach(([node])=>node.disabled=true);
            const confirm=dialog.querySelector('[data-confirm]');confirm.textContent='正在保存…';
            try{const saved=await onConfirm(choice);submitting=false;finish({...choice,saved});}
            catch(failure){error.textContent=pixivCheckErrorMessage(failure.message);autoStatus.textContent='保存未完成，选择已保留，可调整后重试。';}
            finally{submitting=false;if(!settled){controls.forEach(([node,disabled])=>node.disabled=disabled);confirm.textContent='确认校验';}}
        };
        showPage(result.suggested_page??0);
    });
}

let pixivAutoReviewEnabled = false;

function reviewPixivUpgrade(result) {
    const current = result.current || {};
    const candidate = result.candidate || {};
    const safe = escapeMaintenanceHtml;
    return new Promise(resolve => {
        ui.showModal(`Pixiv 原图 · PID ${safe(current.pid)}`, `
            <section class="duplicate-review duplicate-review-large pixiv-upgrade-review">
                <p>右侧是 Pixiv 找到的更高分辨率原图。只有选择“覆盖原图”才会替换库内文件。</p>
                <div class="duplicate-compare-grid">
                    <article class="duplicate-compare-card">
                        <header><strong>当前原图</strong><span>ID ${safe(current.image_id)}</span></header>
                        <img src="${safe(current.preview_url)}" alt="当前原图">
                        <dl class="duplicate-metadata">
                            <div><dt>分辨率</dt><dd>${safe(current.width)} × ${safe(current.height)}</dd></div>
                            <div><dt>大小</dt><dd>${safe(formatMaintenanceBytes(current.file_size))}</dd></div>
                        </dl>
                    </article>
                    <article class="duplicate-compare-card pixiv-upgrade-candidate">
                        <header><strong>Pixiv 原图</strong><span>第 ${Number(candidate.page_index || 0) + 1} 张</span></header>
                        <img src="${safe(candidate.preview_url)}" alt="Pixiv 高清候选图">
                        <dl class="duplicate-metadata">
                            <div><dt>分辨率</dt><dd>${safe(candidate.width)} × ${safe(candidate.height)}</dd></div>
                            <div><dt>大小</dt><dd>${safe(formatMaintenanceBytes(candidate.file_size))}</dd></div>
                        </dl>
                    </article>
                </div>
                <label class="pixiv-auto-review-toggle">
                    <input type="checkbox" data-pixiv-auto-review ${pixivAutoReviewEnabled ? 'checked' : ''}>
                    <span>
                        <strong>自动审核</strong>
                        <small>10 秒倒计时后自动选择“覆盖原图”，可随时取消</small>
                    </span>
                    <em data-pixiv-auto-status aria-live="polite"></em>
                </label>
                <div class="duplicate-decision-actions pixiv-upgrade-actions">
                    <a class="btn btn-secondary" href="${safe(result.artwork_url)}" target="_blank" rel="noopener noreferrer">打开 Pixiv 作品页</a>
                    <button type="button" class="btn btn-secondary" data-pixiv-action="skip">保留现图</button>
                    <button type="button" class="btn btn-primary pixiv-auto-replace" data-pixiv-action="replace">
                        <span class="pixiv-auto-spinner" aria-hidden="true"></span>
                        <span data-pixiv-replace-label>覆盖原图</span>
                    </button>
                </div>
            </section>
        `);
        const layer = document.getElementById('modal-body')?.lastElementChild;
        const autoToggle = layer?.querySelector('[data-pixiv-auto-review]');
        const autoStatus = layer?.querySelector('[data-pixiv-auto-status]');
        const replaceButton = layer?.querySelector('[data-pixiv-action="replace"]');
        const replaceLabel = layer?.querySelector('[data-pixiv-replace-label]');
        let settled = false;
        let countdownTimer = null;

        const clearCountdown = () => {
            if (countdownTimer !== null) {
                window.clearInterval(countdownTimer);
                countdownTimer = null;
            }
        };

        const stopCountdown = () => {
            clearCountdown();
            replaceButton?.classList.remove('is-counting');
            if (replaceLabel) replaceLabel.textContent = '覆盖原图';
            if (autoStatus) autoStatus.textContent = '';
        };

        const finish = action => {
            if (settled) return;
            settled = true;
            clearCountdown();
            if (layer) delete layer._onModalClose;
            ui.closeModal();
            resolve(action);
        };

        const startCountdown = () => {
            stopCountdown();
            let seconds = 10;
            replaceButton?.classList.add('is-counting');
            const renderCountdown = () => {
                if (replaceLabel) replaceLabel.textContent = `覆盖原图（${seconds}）`;
                if (autoStatus) autoStatus.textContent = `${seconds} 秒后自动覆盖`;
            };
            renderCountdown();
            countdownTimer = window.setInterval(() => {
                seconds -= 1;
                if (seconds <= 0) {
                    clearCountdown();
                    if (replaceLabel) replaceLabel.textContent = '正在自动覆盖…';
                    if (autoStatus) autoStatus.textContent = '正在执行自动审核';
                    finish('replace');
                    return;
                }
                renderCountdown();
            }, 1000);
        };

        if (layer) {
            layer._onModalClose = () => {
                clearCountdown();
                if (!settled) {
                    settled = true;
                    resolve(null);
                }
            };
        }
        layer?.querySelectorAll('[data-pixiv-action]').forEach(button => {
            button.addEventListener('click', () => finish(button.dataset.pixivAction));
        });
        autoToggle?.addEventListener('change', () => {
            pixivAutoReviewEnabled = autoToggle.checked;
            if (pixivAutoReviewEnabled) startCountdown();
            else stopCountdown();
        });
        if (pixivAutoReviewEnabled) startCountdown();
    });
}

function updatePixivUpgradeProgress({ checked = 0, total = null, state = 'running', detail = '' } = {}) {
    const panel = document.getElementById('pixiv-upgrade-progress');
    const label = document.getElementById('pixiv-upgrade-progress-label');
    const count = document.getElementById('pixiv-upgrade-progress-count');
    const bar = document.getElementById('pixiv-upgrade-progress-bar');
    const detailElement = document.getElementById('pixiv-upgrade-progress-detail');
    if (!panel || !label || !count || !bar || !detailElement) return;

    const labels = {
        running: 'Pixiv 校验中',
        review: '扫描完成，部分作品待确认',
        stopped: 'Pixiv 校验已停止',
        complete: 'Pixiv 后台扫描完成',
        error: 'Pixiv 校验失败',
        partial: '扫描完成，部分图片需重试',
    };
    panel.hidden = false;
    panel.dataset.state = state;
    label.textContent = labels[state] || labels.running;
    detailElement.textContent = detail;

    if (total === null) {
        bar.removeAttribute('value');
        count.textContent = '正在统计…';
        return;
    }
    const safeTotal = Math.max(0, Number(total) || 0);
    const safeChecked = Math.min(safeTotal, Math.max(0, Number(checked) || 0));
    bar.max = Math.max(1, safeTotal);
    bar.value = safeTotal === 0 ? 1 : safeChecked;
    const percent = safeTotal === 0 ? 100 : Math.round((safeChecked / safeTotal) * 100);
    count.textContent = `${safeChecked} / ${safeTotal} · ${percent}%`;
}

const pixivCheckQueueState = {runId:null,timer:null,polling:false,reviewBusy:false,processing:false,autoPaused:false,starting:false,offset:0,deferred:new Set()};

function pixivCheckErrorMessage(error) {
    return ({check_busy:'另一个管理员正在运行校验',check_review_expired:'确认项已失效，请重新校验',
        image_changed:'库内图片已变化，请重新校验',account_changed:'Pixiv 账号已变更，请重新校验',
        reauth_required:'请先重新连接 Pixiv 账号',permission_revoked:'管理员权限已撤销',
        check_database_busy:'数据库暂时繁忙，可重新校验',
        artwork_unsupported:'作品类型暂不支持或信息不完整，已保留原 PID',download_failed:'下载失败，选择已保留，可重试',
        external_error:'Pixiv 暂时不可用，可稍后重新校验',check_processing_failed:'此项处理失败，可重新校验'})[error]||error;
}

function renderPixivCheckImports(imports,total) {
    if(!imports.length)return '';
    const safe=escapeMaintenanceHtml,labels={queued:'排队补入',running:'正在补入',retry:'等待重试',
        awaiting_duplicate:'需要查重确认',failed:'补入失败',partial:'待继续'};
    return `<div class="pixiv-check-queue-heading"><strong>补入任务 ${Number(total)||imports.length}</strong><small>需要查重的页保留在这里，确认后继续入库。</small></div>${imports.map(job=>
        `<article class="pixiv-check-import"><strong>${safe(job.pid)} · ${safe(labels[job.status]||job.status)} · ${Number(job.done)||0} / ${job.pages.length} 页</strong>${job.error?`<p>${safe(pixivCheckErrorMessage(job.error))}</p>`:''}${job.status==='awaiting_duplicate'?`<p>第 ${Number(job.page)+1} 页疑似与库内图片重复：</p><div class="pixiv-check-duplicate-options">${job.duplicates.map(image=>`<div><button class="px-text-button" data-check-image="${safe(image.image_id)}"><img src="/resource/thumbs/${encodeURIComponent(image.image_id)}.webp" loading="lazy" alt="查看库内候选图片"></button><button class="btn btn-secondary" data-check-import="existing" data-job="${Number(job.id)}" data-image="${safe(image.image_id)}">保留此图</button></div>`).join('')}<button class="btn btn-secondary" data-check-import="different" data-job="${Number(job.id)}">确认为不同图片，继续补入</button></div>`:''}${['failed','partial'].includes(job.status)?`<button class="btn btn-secondary" data-check-import="retry" data-job="${Number(job.id)}">重试补入</button>`:''}</article>`).join('')}`;
}

const pixivCheckImportBusy=new Set();
async function actOnPixivCheckImport(button) {
    const id=Number(button.dataset.job);if(pixivCheckImportBusy.has(id))return;
    pixivCheckImportBusy.add(id);button.disabled=true;
    try {
        if(button.dataset.checkImport==='retry')await api.retryPixivCheckImport(id);
        else await api.resolvePixivCheckImport(id,button.dataset.checkImport,button.dataset.image||null);
        ui.showToast('已提交，补入任务将继续处理','success');
    }catch(error){ui.showToast(pixivCheckErrorMessage(error.message),'error');}
    finally{pixivCheckImportBusy.delete(id);button.disabled=false;refreshPixivCheckQueue();}
}

async function refreshPixivCheckQueue() {
    const state=pixivCheckQueueState;
    if(state.polling||!ui.isAdminView())return;
    state.polling=true;clearTimeout(state.timer);
    let keepPolling=false;
    try {
        const data=await api.getPixivCheckQueue(null,state.offset),run=data.run,imports=data.imports||[];
        state.runId=run?.id||null;
        if(state.offset>=data.review_count&&state.offset)state.offset=0;
        const counts=run?.counts||{},active=run?.status==='running';
        const button=document.getElementById('scan-pixiv-upgrades-button'),stop=document.getElementById('pixiv-check-stop');
        if(button){button.disabled=active||state.starting;button.textContent=active?'后台校验中…':'Pixiv 校验';}
        if(stop)stop.hidden=!active;
        if(run)updatePixivUpgradeProgress({checked:run.total-(counts.queued||0)-(counts.running||0),total:run.total,
            state:active?'running':run.status==='cancelled'?'stopped':run.status==='failed'?'error':data.review_count?'review':counts.failed?'partial':'complete',
            detail:`${run.workers} 个并发线程 · 排队 ${counts.queued||0} · 处理中 ${counts.running||0} · 待确认 ${data.review_count} · 失败 ${counts.failed||0} · 补入待处理 ${data.import_count||0}；已生成 ${run.fingerprints} 张指纹 · 清除失效 PID ${run.invalid_pids||0}${run.error?`；${pixivCheckErrorMessage(run.error)}`:''}`});
        const panel=document.getElementById('pixiv-check-review-queue');
        if(panel){
            const safe=escapeMaintenanceHtml;
            panel.hidden=!data.review_count&&!run?.errors?.length&&!imports.length;
            panel.innerHTML=`<div class="pixiv-check-queue-heading pixiv-check-review-heading"><strong>待处理 <span>${data.review_count}</span></strong><button class="btn btn-secondary" data-start-reviews ${!data.review_count||state.reviewBusy||state.processing?'disabled':''}>${state.processing?'正在处理…':'开始处理'}</button><small>逐张确认后自动进入下一张；稍后处理跳过当前张，关闭窗口可暂停。</small></div><div class="pixiv-check-queue-items">${data.reviews.map(review=>`<article class="pixiv-check-queue-item"><div><strong>${safe(review.title||review.pid)}</strong><small>${safe(review.pid)} · ${Number(review.page_count)||1} 页</small></div></article>`).join('')}</div>${data.review_count>20?`<div class="pixiv-check-queue-pages"><button class="btn btn-secondary" data-queue-prev ${state.offset?'':'disabled'}>上一组</button><span>${Math.floor(state.offset/20)+1} / ${Math.ceil(data.review_count/20)}</span><button class="btn btn-secondary" data-queue-next ${state.offset+20<data.review_count?'':'disabled'}>下一组</button></div>`:''}${run?.errors?.length?`<details class="validation-advanced"><summary>失败项（可重新校验）</summary>${run.errors.map(item=>`<p>${safe(item.image_id||'指纹任务')}：${safe(pixivCheckErrorMessage(item.error))}</p>`).join('')}</details>`:''}`;
            const startReviews=panel.querySelector('[data-start-reviews]');
            if(startReviews)startReviews.onclick=startProcessingPixivChecks;
            panel.insertAdjacentHTML('beforeend',renderPixivCheckImports(imports,data.import_count||0));
            panel.querySelectorAll('[data-check-import]').forEach(node=>node.onclick=()=>actOnPixivCheckImport(node));
            panel.querySelectorAll('[data-check-image]').forEach(node=>node.onclick=()=>ui.showImageDetail(node.dataset.checkImage));
            panel.querySelectorAll('[data-check-image] img').forEach(image=>image.onerror=()=>{
                image.onerror=null;image.src='/static/icon/Pic.ico';
            });
            const prev=panel.querySelector('[data-queue-prev]'),next=panel.querySelector('[data-queue-next]');
            if(prev)prev.onclick=()=>{state.offset=Math.max(0,state.offset-20);refreshPixivCheckQueue();};
            if(next)next.onclick=()=>{state.offset+=20;refreshPixivCheckQueue();};
        }
        keepPolling=active||((data.review_count>0||imports.length>0)&&ui.currentPage==='settings');
        pixivAutoReviewEnabled=!!document.getElementById('pixiv-check-auto')?.checked;
        if(pixivAutoReviewEnabled&&!state.autoPaused&&!state.reviewBusy&&!state.processing&&!document.hidden&&ui.currentPage==='settings'){
            const review=data.reviews.find(item=>item.auto_review_safe&&!state.deferred.has(item.id));
            if(review)reviewQueuedPixivCheck(review.id);
        }
    } catch(error) {
        if(error.status!==401&&error.status!==403){keepPolling=ui.currentPage==='settings';updatePixivUpgradeProgress({state:'error',detail:pixivCheckErrorMessage(error.message)});}
    } finally {
        state.polling=false;
        if(keepPolling)state.timer=setTimeout(refreshPixivCheckQueue,1500);
    }
}

async function reviewQueuedPixivCheck(reviewId) {
    const state=pixivCheckQueueState;
    if(state.reviewBusy)return;
    state.reviewBusy=true;if(!state.processing)window.pixivValidationStop=false;
    try {
        const result=await api.getPixivCheckReview(reviewId);
        if(state.processing&&(window.pixivValidationStop||ui.currentPage!=='settings'||!ui.isAdminView()))return 'closed';
        result.queue_processing=state.processing;
        const choice=await reviewPixivCheck(result,choice=>api.resolvePixivCheck(choice));
        if(!choice){state.deferred.add(reviewId);if(state.processing)state.autoPaused=true;return 'closed';}
        if(choice.deferred){state.deferred.add(reviewId);return 'deferred';}
        const saved=choice.saved||await api.resolvePixivCheck(choice);
        ui.showToast(`${saved.pid}：已补全画师与 Pixiv 标签${saved.upgraded?'，已更新高清原图':''}`,'success');
        window.pixivOL?.similaritySeen?.clear();
        ui.loadSystemStatus();
        return 'confirmed';
    } catch(error){state.deferred.add(reviewId);ui.showToast(pixivCheckErrorMessage(error.message),'error');return 'error';}
    finally{state.reviewBusy=false;refreshPixivCheckQueue();}
}

async function startProcessingPixivChecks() {
    const state=pixivCheckQueueState;
    if(state.processing||state.reviewBusy||!ui.isAdminView()||ui.currentPage!=='settings')return;
    state.processing=true;state.autoPaused=false;state.deferred.clear();
    window.pixivValidationStop=false;
    refreshPixivCheckQueue();
    const visited=new Set();
    const canContinue=()=>!window.pixivValidationStop&&ui.isAdminView()&&ui.currentPage==='settings';
    // Reload from the first page after each decision: confirmed rows leave the queue.
    // Walk past deferred rows so batches larger than 20 never stall at the first page.
    try {
        while(canContinue()){
            let review=null;
            for(let offset=0;canContinue();offset+=20){
                const data=await api.getPixivCheckQueue(null,offset);
                if(!canContinue())break;
                review=data.reviews.find(item=>!visited.has(item.id));
                if(review||offset+20>=data.review_count)break;
            }
            if(!review||!canContinue())break;
            visited.add(review.id);
            const outcome=await reviewQueuedPixivCheck(review.id);
            if(outcome==='closed'||outcome==='error')break;
        }
    }catch(error){state.autoPaused=true;ui.showToast(pixivCheckErrorMessage(error.message),'error');}
    finally{state.processing=false;state.autoPaused=true;state.offset=0;refreshPixivCheckQueue();}
}

async function scanPixivUpgrades() {
    if(!ui.isAdminView()){ui.showToast('只有管理员可以执行维护操作','warning');return;}
    const state=pixivCheckQueueState;
    if(state.starting)return;
    state.starting=true;state.autoPaused=false;state.offset=0;state.deferred.clear();window.pixivValidationStop=false;
    const button=document.getElementById('scan-pixiv-upgrades-button');if(button)button.disabled=true;
    try {
        const result=await api.startPixivCheckQueue();state.runId=result.id;
        ui.showToast('Pixiv 后台校验已开始，需要选择的作品会进入待确认队列','success');
    } catch(error){ui.showToast(pixivCheckErrorMessage(error.message),'error');}
    finally{state.starting=false;refreshPixivCheckQueue();}
}

async function stopPixivCheckQueue() {
    const state=pixivCheckQueueState;
    if(!state.runId)return;
    try {
        await api.stopPixivCheckQueue(state.runId);
        window.pixivValidationStop=true;window.cancelPixivCheckReview?.();
        ui.showToast('后台校验已停止，已完成的结果和待确认队列保留','info');
        await refreshPixivCheckQueue();
    } catch(error){ui.showToast(pixivCheckErrorMessage(error.message),'error');}
}


// Feature modules are loaded before this core class and contribute cohesive method sets.
(window.PicManagerUIModules || []).forEach(ModuleClass => {
    const descriptors = Object.getOwnPropertyDescriptors(ModuleClass.prototype);
    delete descriptors.constructor;
    Object.defineProperties(UIManager.prototype, descriptors);
});

// 创建全局UI实例
window.ui = new UIManager();
