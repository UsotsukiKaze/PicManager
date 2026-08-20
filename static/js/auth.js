// 用户认证管理
class AuthManager {
    constructor() {
        this.currentUser = null;
        this.isGuest = false;
        this.guestInfo = null;
        this.featureLoadPromises = {};
        this.featureAssets = {
            upload: {
                src: '/static/js/upload.js?v=20260820d',
                resolve: () => window.upload,
            },
            emoji: {
                src: '/static/js/emoji-library.js?v=20260820i',
                resolve: () => window.emojiLibrary,
            },
        };
    }

    async init() {
        const authSuccess = await this.checkAuth();
        if (!authSuccess) {
            // 认证失败，已重定向到登录页
            return;
        }

        await this.loadApplication();
        this.updateUI();

        // 认证成功后再初始化应用
        if (typeof initializeApp === 'function') {
            await initializeApp();
        }

        // 通知不是首屏依赖，在浏览器空闲时后台检查。
        this.scheduleNotificationCheck();
    }

    loadStyle(href) {
        return new Promise((resolve, reject) => {
            const existing = Array.from(document.styleSheets).find(sheet => sheet.href && sheet.href.includes(href));
            if (existing) {
                resolve();
                return;
            }
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = href;
            link.onload = resolve;
            link.onerror = () => reject(new Error(`Failed to load stylesheet: ${href}`));
            document.head.appendChild(link);
        });
    }

    loadScript(src) {
        return new Promise((resolve, reject) => {
            const existing = Array.from(document.scripts).find(script => script.src && script.src.includes(src));
            if (existing) {
                if (existing.dataset.loaded === 'true') {
                    resolve();
                } else {
                    existing.addEventListener('load', resolve, { once: true });
                    existing.addEventListener('error', () => reject(new Error(`Failed to load script: ${src}`)), { once: true });
                }
                return;
            }
            const script = document.createElement('script');
            script.src = src;
            script.async = false;
            script.onload = () => {
                script.dataset.loaded = 'true';
                resolve();
            };
            script.onerror = () => {
                script.remove();
                reject(new Error(`Failed to load script: ${src}`));
            };
            document.body.appendChild(script);
        });
    }

    loadFeature(name) {
        const feature = this.featureAssets[name];
        if (!feature) {
            return Promise.reject(new Error(`Unknown application feature: ${name}`));
        }

        const loadedFeature = feature.resolve();
        if (loadedFeature) return Promise.resolve(loadedFeature);
        if (this.featureLoadPromises[name]) return this.featureLoadPromises[name];

        const loadPromise = this.loadScript(feature.src)
            .then(() => {
                const resolvedFeature = feature.resolve();
                if (!resolvedFeature) {
                    throw new Error(`Feature did not initialize after loading: ${name}`);
                }
                return resolvedFeature;
            })
            .catch(error => {
                delete this.featureLoadPromises[name];
                throw error;
            });

        this.featureLoadPromises[name] = loadPromise;
        return loadPromise;
    }

    waitForDocumentBody() {
        if (document.body) return Promise.resolve();
        return new Promise(resolve => {
            document.addEventListener('DOMContentLoaded', resolve, { once: true });
        });
    }

    async loadApplication() {
        if (this.applicationLoadPromise) return this.applicationLoadPromise;

        this.applicationLoadPromise = (async () => {
            await this.waitForDocumentBody();
            const stylesReady = Promise.all([
                this.loadStyle('/static/css/style.css?v=20260820j'),
                this.loadStyle('/static/css/icons.css?v=20260812a'),
            ]);
            const scripts = [
                '/static/js/security.js?v=20260820a',
                '/static/js/pinyin-search.js?v=20260812a',
                '/static/js/character-selector.js?v=20260820a',
                '/static/js/tag-selector.js?v=20260820d',
                '/static/js/api.js?v=20260820h',
                '/static/js/upload-queue.js?v=20260820j',
                '/static/js/query-panel.js?v=20260820d',
                '/static/js/entity-cache.js?v=20260820a',
                '/static/js/search-selector.js?v=20260820d',
                '/static/js/image-list.js?v=20260820b',
                '/static/js/modal.js?v=20260820a',
                '/static/js/ui.js?v=20260820d',
                '/static/js/main.js?v=20260812c',
            ];

            // async=false 的动态 classic script 按插入顺序执行；一次性插入可让网络抓取并行。
            const scriptsReady = Promise.all(scripts.map(src => this.loadScript(src)));
            await stylesReady;
            await scriptsReady;

            document.querySelectorAll('[data-auth-src]').forEach(image => {
                image.src = image.dataset.authSrc;
                delete image.dataset.authSrc;
            });
            document.querySelectorAll('[data-auth-href]').forEach(link => {
                link.href = link.dataset.authHref;
                delete link.dataset.authHref;
            });
            document.documentElement.classList.remove('app-booting');
        })();

        try {
            await this.applicationLoadPromise;
        } catch (error) {
            this.applicationLoadPromise = null;
            throw error;
        }
    }

    scheduleNotificationCheck() {
        if (this.isGuest || !this.currentUser) return;
        const run = () => {
            this.checkNotifications().catch(error => {
                console.error('Notification check failed:', error);
            });
        };
        if ('requestIdleCallback' in window) {
            window.requestIdleCallback(run, { timeout: 5000 });
        } else {
            window.setTimeout(run, 0);
        }
    }

    async checkAuth() {
        try {
            const response = await fetch('/auth/me');
            if (!response.ok) {
                // 未登录，跳转到登录页
                window.location.href = '/login';
                return false;
            }

            const data = await response.json();
            
            if (data.is_guest) {
                this.isGuest = true;
                this.guestInfo = data;
                this.currentUser = null;
            } else {
                this.isGuest = false;
                this.currentUser = data.user;
                this.guestInfo = null;
            }
            return true;
        } catch (error) {
            console.error('Auth check failed:', error);
            window.location.href = '/login';
            return false;
        }
    }

    updateUI() {
        const userBar = document.getElementById('top-user-bar');
        const headerAvatar = document.getElementById('header-avatar');
        const headerUsername = document.getElementById('header-username');
        const headerRole = document.getElementById('header-role');

        if (this.isGuest) {
            headerAvatar.src = '/favicon.ico';
            headerAvatar.alt = '网站图标';
            headerAvatar.style.display = 'block';
            headerAvatar.onerror = () => { headerAvatar.style.display = 'none'; };
            headerUsername.textContent = this.guestInfo.guest_name || '游客';
            headerRole.textContent = `今天还能提交: ${this.guestInfo.remaining_operations}`;
            headerRole.className = 'user-role-small role-guest';
        } else if (this.currentUser) {
            if (this.currentUser.avatar_url) {
                headerAvatar.src = this.currentUser.avatar_url;
                headerAvatar.style.display = 'block';
            }
            headerUsername.textContent = this.currentUser.nickname || this.currentUser.qq_number;
            
            const roleMap = {
                'root': { text: 'Root', class: 'role-root' },
                'admin': { text: '管理员', class: 'role-admin' },
                'user': { text: '用户', class: 'role-user' }
            };
            const roleInfo = roleMap[this.currentUser.role] || { text: '用户', class: 'role-user' };
            headerRole.textContent = roleInfo.text;
            headerRole.className = `user-role-small ${roleInfo.class}`;
        }

        // 权限控制 - 隐藏temp目录上传（对游客和普通用户）
        this.applyPermissions();
    }

    applyPermissions() {
        const isAdmin = this.currentUser && 
            (this.currentUser.role === 'root' || this.currentUser.role === 'admin');
        
        // temp目录上传标签页 - 仅管理员可见
        const tempUploadTab = document.querySelector('[data-tab="temp-upload"]');
        if (tempUploadTab) {
            if (!isAdmin) {
                tempUploadTab.style.display = 'none';
            } else {
                tempUploadTab.style.display = '';
            }
        }

        document.querySelectorAll('.admin-maintenance').forEach(section => {
            section.style.display = isAdmin ? '' : 'none';
        });

        if (window.ui && typeof window.ui.applyRolePreferences === 'function') {
            window.ui.applyRolePreferences();
        }
    }

    async checkNotifications() {
        if (this.isGuest || !this.currentUser) {
            return;
        }

        try {
            const response = await fetch('/auth/notifications');
            if (!response.ok) return;

            const data = await response.json();
            const approved = data.approved || 0;
            const rejected = data.rejected || 0;
            const total = approved + rejected;

            if (total > 0) {
                const message = `有 ${total} 条审核结果更新（通过 ${approved}，驳回 ${rejected}），可到个人中心查看详情`;
                if (window.ui && typeof window.ui.showToast === 'function') {
                    window.ui.showToast(message, 'info');
                } else {
                    console.log(message);
                }
            }
        } catch (error) {
            console.error('通知检查失败:', error);
        }
    }

    isAdmin() {
        return this.currentUser && 
            (this.currentUser.role === 'root' || this.currentUser.role === 'admin');
    }

    isRoot() {
        return this.currentUser && this.currentUser.role === 'root';
    }

    canDirectUpload() {
        // 只有管理员可以直接上传
        return this.isAdmin();
    }

    async checkGuestLimit() {
        if (!this.isGuest) {
            return { canOperate: true };
        }

        try {
            const response = await fetch('/auth/guest-limit');
            if (!response.ok) {
                return { canOperate: false, message: '无法检查操作限制' };
            }

            const data = await response.json();
            if (data.remaining_operations <= 0) {
                return { 
                    canOperate: false, 
                    message: '今日操作次数已用完，请明天再试或登录账号' 
                };
            }

            return { canOperate: true, remaining: data.remaining_operations };
        } catch (error) {
            return { canOperate: false, message: '检查操作限制失败' };
        }
    }

    async refreshGuestLimit() {
        if (this.isGuest) {
            const response = await fetch('/auth/guest-limit');
            if (response.ok) {
                const data = await response.json();
                this.guestInfo.remaining_operations = data.remaining_operations;
                document.getElementById('header-role').textContent = 
                    `今天还能提交: ${data.remaining_operations}`;
            }
        }
    }
}

// 全局认证管理器
const auth = new AuthManager();
window.auth = auth;

// 退出登录
async function handleLogout() {
    try {
        await fetch('/auth/logout', { method: 'POST' });
        window.location.href = '/login';
    } catch (error) {
        window.location.href = '/login';
    }
}

// 认证引导脚本位于 head：尽快拦截匿名访问，通过后才加载管理应用。
auth.init().catch(error => {
    console.error('Application bootstrap failed:', error);
    window.location.replace('/login');
});
