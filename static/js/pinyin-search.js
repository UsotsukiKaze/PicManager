/**
 * Unified text search for Chinese entity names.
 *
 * The public match/filter/learnWords surface is intentionally compatible with
 * the legacy implementation. Transliteration is delegated to the locally
 * hosted pinyin-pro build; this module owns normalization, caching and ranking.
 */
const PinyinSearch = {
    wordIndex: new Map(),
    engineWarningShown: false,

    get engine() {
        return window.pinyinPro || null;
    },

    normalize(value) {
        return String(value ?? '')
            .normalize('NFKC')
            .toLowerCase()
            .replace(/\s+/g, ' ')
            .trim();
    },

    compact(value) {
        return this.normalize(value).replace(/[\p{P}\p{S}\s]+/gu, '');
    },

    warnIfEngineMissing() {
        if (this.engine || this.engineWarningShown) return;
        this.engineWarningShown = true;
        console.warn('pinyin-pro is unavailable; falling back to direct text search');
    },

    buildRecord(text) {
        const source = String(text ?? '');
        const direct = this.compact(source);
        const engine = this.engine;
        this.warnIfEngineMissing();

        if (!engine || !source) {
            return { source, direct, full: direct, initials: direct };
        }

        const commonOptions = {
            toneType: 'none',
            separator: '',
            nonZh: 'consecutive',
        };
        const full = this.compact(engine.pinyin(source, commonOptions));
        const initials = this.compact(engine.pinyin(source, {
            ...commonOptions,
            pattern: 'first',
        }));

        return { source, direct, full, initials };
    },

    getRecord(text) {
        const source = String(text ?? '');
        if (!this.wordIndex.has(source)) {
            this.wordIndex.set(source, this.buildRecord(source));
        }
        return this.wordIndex.get(source);
    },

    getPinyinInitials(text) {
        return this.getRecord(text).initials;
    },

    getFullPinyin(text) {
        return this.getRecord(text).full;
    },

    getCharPinyin(char) {
        return this.getPinyinInitials(char);
    },

    learn(text) {
        if (!text) return '';
        return this.getPinyinInitials(text);
    },

    learnWords(words) {
        if (!Array.isArray(words)) return;
        words.forEach(word => this.learn(word));
    },

    scoreRecord(record, query) {
        const q = this.compact(query);
        if (!q || !record.direct) return 0;

        if (record.direct === q) return 1000;
        if (record.direct.startsWith(q)) return 920;
        if (record.direct.includes(q)) return 840;
        if (record.full === q) return 760;
        if (record.full.startsWith(q)) return 700;
        if (record.full.includes(q)) return 640;
        if (record.initials === q) return 580;
        if (record.initials.startsWith(q)) return 540;
        if (record.initials.includes(q)) return 500;

        return 0;
    },

    valueList(item, key = 'name') {
        if (typeof item === 'string') return [item];
        if (!item || typeof item !== 'object') return [];

        const values = [item[key]];
        for (const field of ['aliases', 'nicknames']) {
            const entries = Array.isArray(item[field]) ? item[field] : [];
            entries.forEach(entry => {
                if (typeof entry === 'string') {
                    values.push(entry);
                } else if (entry && typeof entry === 'object') {
                    values.push(entry.name ?? entry.alias ?? entry.nickname);
                }
            });
        }
        return values.filter(value => value !== null && value !== undefined && String(value).trim());
    },

    score(item, query, key = 'name') {
        if (!this.compact(query)) return 1;
        const values = this.valueList(item, key);
        let best = 0;
        values.forEach((value, index) => {
            const matchedScore = this.scoreRecord(this.getRecord(value), query);
            if (!matchedScore) return;
            const primaryBonus = index === 0 ? 20 : 0;
            best = Math.max(best, matchedScore + primaryBonus);
        });
        return best;
    },

    match(text, query) {
        if (!this.compact(query)) return true;
        if (!text) return false;
        return this.scoreRecord(this.getRecord(text), query) > 0;
    },

    filter(items, query, key = 'name') {
        if (!Array.isArray(items) || !this.compact(query)) return items;
        return items
            .map((item, index) => ({ item, index, score: this.score(item, query, key) }))
            .filter(result => result.score > 0)
            .sort((left, right) => right.score - left.score || left.index - right.index)
            .map(result => result.item);
    },

    registerCustomPinyin(dictionary) {
        if (!dictionary || typeof dictionary !== 'object' || !this.engine?.customPinyin) return false;
        this.engine.customPinyin(dictionary);
        this.clear();
        return true;
    },

    getStats() {
        return {
            indexedWords: this.wordIndex.size,
            engineReady: Boolean(this.engine),
        };
    },

    clear() {
        this.wordIndex.clear();
    },
};

window.PinyinSearch = PinyinSearch;
