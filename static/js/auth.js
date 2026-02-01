// 用户认证管理
class AuthManager {
    constructor() {
        this.currentUser = null;
        this.isGuest = false;
        this.guestInfo = null;
    }

    async init() {
        const authSuccess = await this.checkAuth();
        if (!authSuccess) {
            // 认证失败，已重定向到登录页
            return;
        }
        
        this.updateUI();
        
        // 认证成功后再初始化应用
        if (typeof initializeApp === 'function') {
            await initializeApp();
        }
        
        // 检查通知
        await this.checkNotifications();
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
            headerAvatar.style.display = 'none';
            headerUsername.textContent = `游客 (${this.guestInfo.guest_ip})`;
            headerRole.textContent = `剩余操作: ${this.guestInfo.remaining_operations}`;
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
                    `剩余操作: ${data.remaining_operations}`;
            }
        }
    }
}

// 全局认证管理器
const auth = new AuthManager();

// 退出登录
async function handleLogout() {
    try {
        await fetch('/auth/logout', { method: 'POST' });
        window.location.href = '/login';
    } catch (error) {
        window.location.href = '/login';
    }
}

// 页面加载时初始化认证
document.addEventListener('DOMContentLoaded', () => {
    auth.init();
});
