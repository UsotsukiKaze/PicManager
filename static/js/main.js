// 主应用程序入口
document.addEventListener('DOMContentLoaded', function() {
    console.log('PicManager 系统已加载');
    
    // 初始化应用
    initializeApp();
});

async function initializeApp() {
    try {
        // 预热阶段：提前加载数据并建立拼音索引
        console.log('正在预热数据...');
        await preheatData();
        
        // 加载系统状态
        await ui.loadSystemStatus();
        await ui.updateTempCount();
        
        // 预先初始化搜索选项（不等待切换标签页）
        await ui.initializeSearchSelectors();
        
        // 默认加载图片列表（首次进入强制加载）
        ui.currentTab = null; // 重置以确保能加载
        ui.switchTab('image-list');
        
        // 设置定时更新temp计数
        setInterval(async () => {
            await ui.updateTempCount();
        }, 30000); // 每30秒更新一次
        
        console.log('应用初始化完成');
    } catch (error) {
        console.error('应用初始化失败:', error);
        ui.showToast('系统初始化失败，请刷新页面重试', 'error');
    }
}

/**
 * 预热数据：加载分组和角色数据，建立拼音索引
 */
async function preheatData() {
    try {
        const [groups, characters] = await Promise.all([
            api.getGroups(),
            api.getCharacters()
        ]);
        
        // 预热拼音索引
        if (window.PinyinSearch) {
            const allNames = [
                ...groups.map(g => g.name),
                ...characters.map(c => c.name)
            ];
            window.PinyinSearch.learnWords(allNames);
            
            const stats = window.PinyinSearch.getStats();
            console.log(`拼音索引预热完成: ${stats.cachedChars} 个字符, ${stats.indexedWords} 个词汇`);
        }
        
        // 缓存数据到ui实例
        ui.allGroups = groups;
        ui.allCharacters = characters;
        
        console.log(`数据预热完成: ${groups.length} 个分组, ${characters.length} 个角色`);
    } catch (error) {
        console.error('数据预热失败:', error);
    }
}

// 全局错误处理
window.addEventListener('error', (event) => {
    console.error('全局错误:', event.error);
    ui.showToast('发生未知错误，请查看控制台', 'error');
});

// 全局未处理的Promise拒绝
window.addEventListener('unhandledrejection', (event) => {
    console.error('未处理的Promise拒绝:', event.reason);
    ui.showToast('网络请求失败，请检查网络连接', 'error');
});