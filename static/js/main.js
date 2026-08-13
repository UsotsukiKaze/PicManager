// 主应用程序入口
document.addEventListener('DOMContentLoaded', function() {
    console.log('PicManager 系统已加载');
    
    // 等待 auth 初始化完成后再初始化应用
    // auth.js 会在用户认证后调用 initializeApp
});

async function initializeApp() {
    try {
        // 页面外壳已可用，首页模块并行加载且各自独立降级。
        const homeModules = [
            ['system status', () => ui.loadSystemStatus()],
            ['popular groups', () => ui.loadHomeGroupChips()],
            ['rankings', () => ui.loadHomeRankings()],
        ];
        Promise.allSettled(homeModules.map(([, load]) => load())).then(results => {
            results.forEach((result, index) => {
                if (result.status === 'rejected') {
                    console.error(`Failed to load ${homeModules[index][0]}:`, result.reason);
                }
            });
        });

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
