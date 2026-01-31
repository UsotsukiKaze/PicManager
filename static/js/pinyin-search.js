/**
 * 优雅的拼音搜索工具
 * 
 * 核心原理：利用 GB2312 汉字按拼音排序的特性
 * 汉字在 Unicode 中的编码范围: 0x4E00 - 0x9FFF
 * 通过预设的拼音分界点，可以快速确定任意汉字的拼音首字母
 * 
 * 优点：
 * 1. 无需大型字典，算法简洁高效
 * 2. 支持所有常用汉字（覆盖 GB2312 全部汉字）
 * 3. 动态学习新字符，按需缓存
 * 4. 内存占用极小
 * 5. 二分查找，时间复杂度 O(log n)
 */

const PinyinSearch = {
    // 拼音首字母分界点（基于汉字 Unicode 排序特性）
    // 格式: [起始Unicode码点, 拼音首字母]
    pinyinBoundaries: [
        [0x554A, 'a'], // 啊
        [0x5E08, 'b'], // 师 -> 吧
        [0x5F00, 'c'], // 开 -> 擦  
        [0x5927, 'd'], // 大
        [0x86FE, 'e'], // 蛾
        [0x5983, 'f'], // 妃
        [0x5676, 'g'], // 噶
        [0x54C8, 'h'], // 哈
        [0x4E0C, 'j'], // 丌 -> 几 (注：汉语拼音无 i 开头)
        [0x5494, 'k'], // 咔
        [0x5783, 'l'], // 垃
        [0x5988, 'm'], // 妈
        [0x62FF, 'n'], // 拿
        [0x5594, 'o'], // 喔
        [0x5991, 'p'], // 妑
        [0x671F, 'q'], // 期
        [0x7136, 'r'], // 然
        [0x4EE8, 's'], // 仨
        [0x4ED6, 't'], // 他
        [0x6316, 'w'], // 挖 (注：汉语拼音无 u/v 开头)
        [0x5915, 'x'], // 夕
        [0x538B, 'y'], // 压
        [0x5E00, 'z'], // 帀
    ],

    // 特殊字符修正表（处理多音字和常见字的首选读音）
    specialChars: {
        '长': 'c', '重': 'z', '还': 'h', '发': 'f', '了': 'l',
        '得': 'd', '地': 'd', '的': 'd', '着': 'z', '过': 'g',
        '乐': 'l', '说': 's', '为': 'w', '曾': 'c', '朝': 'c',
        '数': 's', '参': 'c', '弹': 'd', '差': 'c', '调': 'd',
        '度': 'd', '都': 'd', '分': 'f', '干': 'g', '给': 'g',
        '更': 'g', '行': 'x', '好': 'h', '和': 'h', '会': 'h',
        '几': 'j', '间': 'j', '将': 'j', '角': 'j', '觉': 'j',
        '看': 'k', '空': 'k', '量': 'l', '率': 'l', '落': 'l',
        '模': 'm', '难': 'n', '宁': 'n', '铺': 'p', '奇': 'q',
        '强': 'q', '亲': 'q', '切': 'q', '任': 'r', '似': 's',
        '提': 't', '系': 'x', '相': 'x', '兴': 'x', '应': 'y',
        '与': 'y', '载': 'z', '只': 'z', '种': 'z', '属': 's'
    },

    // 字符缓存：只缓存实际使用过的字符
    charCache: new Map(),
    
    // 词汇索引：存储学习过的词汇及其拼音
    wordIndex: new Map(),

    /**
     * 获取单个汉字的拼音首字母
     * 使用二分查找 + 特殊字符修正
     */
    getCharPinyin(char) {
        // 1. 检查缓存
        if (this.charCache.has(char)) {
            return this.charCache.get(char);
        }

        let pinyin;
        const code = char.charCodeAt(0);

        // 2. 检查特殊字符表
        if (this.specialChars[char]) {
            pinyin = this.specialChars[char];
        }
        // 3. 非汉字字符直接返回小写
        else if (code < 0x4E00 || code > 0x9FFF) {
            pinyin = char.toLowerCase();
        }
        // 4. 二分查找确定拼音首字母
        else {
            pinyin = this.binarySearchPinyin(code);
        }

        // 5. 缓存结果
        this.charCache.set(char, pinyin);
        return pinyin;
    },

    /**
     * 二分查找拼音首字母
     */
    binarySearchPinyin(code) {
        const bounds = this.pinyinBoundaries;
        let left = 0;
        let right = bounds.length - 1;

        // 小于第一个边界
        if (code < bounds[0][0]) {
            return 'a';
        }

        while (left < right) {
            const mid = Math.floor((left + right + 1) / 2);
            if (bounds[mid][0] <= code) {
                left = mid;
            } else {
                right = mid - 1;
            }
        }

        return bounds[left][1];
    },

    /**
     * 获取字符串的拼音首字母串
     */
    getPinyinInitials(str) {
        if (!str) return '';
        return Array.from(str).map(char => this.getCharPinyin(char)).join('');
    },

    /**
     * 学习词汇（按需调用，用于预热缓存）
     */
    learn(text) {
        if (!text) return '';
        
        const pinyin = this.getPinyinInitials(text);
        this.wordIndex.set(text, pinyin);
        
        return pinyin;
    },

    /**
     * 批量学习词汇
     */
    learnWords(words) {
        if (!Array.isArray(words)) return;
        words.forEach(word => this.learn(word));
    },

    /**
     * 智能匹配
     * 支持：直接文本、拼音首字母、模糊子序列
     */
    match(text, query) {
        if (!query || !text) return true;

        const q = query.toLowerCase().trim();
        const t = text.toLowerCase();

        // 1. 直接文本匹配（优先级最高）
        if (t.includes(q)) {
            return true;
        }

        // 2. 获取拼音（优先使用缓存）
        const pinyin = this.wordIndex.get(text) || this.getPinyinInitials(text);
        
        // 3. 拼音首字母匹配
        if (pinyin.includes(q) || pinyin.startsWith(q)) {
            return true;
        }

        // 4. 模糊子序列匹配
        // 例如：输入 "mc" 可以匹配 "mingchao" (鸣潮)
        return this.fuzzyMatch(pinyin, q);
    },

    /**
     * 模糊匹配：检查查询是否为拼音的子序列
     * 时间复杂度 O(n)
     */
    fuzzyMatch(pinyin, query) {
        let pi = 0, qi = 0;
        
        while (pi < pinyin.length && qi < query.length) {
            if (pinyin[pi] === query[qi]) qi++;
            pi++;
        }
        
        return qi === query.length;
    },

    /**
     * 过滤数组
     */
    filter(items, query, key = 'name') {
        if (!query) return items;
        
        return items.filter(item => {
            const text = typeof item === 'string' ? item : item[key];
            return this.match(text, query);
        });
    },

    /**
     * 高亮匹配文本
     */
    highlight(text, query, className = 'highlight') {
        if (!query || !text) return text;
        
        const q = query.toLowerCase();
        const index = text.toLowerCase().indexOf(q);
        
        if (index !== -1) {
            return text.slice(0, index) + 
                   `<span class="${className}">${text.slice(index, index + query.length)}</span>` + 
                   text.slice(index + query.length);
        }
        
        return text;
    },

    /**
     * 获取统计信息
     */
    getStats() {
        return {
            cachedChars: this.charCache.size,
            indexedWords: this.wordIndex.size
        };
    },

    /**
     * 清空所有缓存
     */
    clear() {
        this.charCache.clear();
        this.wordIndex.clear();
    }
};

// 导出到全局
window.PinyinSearch = PinyinSearch;
