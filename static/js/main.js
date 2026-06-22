// 主应用程序入口
document.addEventListener('DOMContentLoaded', function() {
    console.log('PicManager 系统已加载');
    
    // 等待 auth 初始化完成后再初始化应用
    // auth.js 会在用户认证后调用 initializeApp
});

async function initializeApp() {
    try {
        // 首页只加载首屏需要的数据，其余内容等进入对应页面再加载
        await ui.loadSystemStatus();
        await ui.loadHomeGroupChips();

        // 榜单功能暂时隐藏，后续再启用
        
        ui.applyRolePreferences();
        ui.updateSidebarIndicator();
        
        // 只在上传页可见时更新temp计数
        setInterval(async () => {
            if (ui.currentPage === 'upload') {
                await ui.updateTempCount();
            }
        }, 30000);
        
        console.log('应用初始化完成');
    } catch (error) {
        console.error('应用初始化失败:', error);
        ui.showToast('系统初始化失败，请刷新页面重试', 'error');
    }
}

// 全局错误处理 - 只处理真正的意外错误
window.addEventListener('error', (event) => {
    console.error('全局错误:', event.error);
    // 不显示通用toast，让具体的catch块处理
});

// 全局未处理的Promise拒绝 - 只记录日志
window.addEventListener('unhandledrejection', (event) => {
    console.error('未处理的Promise拒绝:', event.reason);
    // 不显示通用toast，让具体的catch块处理
});
