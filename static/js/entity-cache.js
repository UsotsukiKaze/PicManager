(function () {
    'use strict';

    class EntityCacheModule {
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

    async loadCachedEntity(key, loader, { forceRefresh = false, params = null } = {}) {
        if (!forceRefresh && this.isCacheValid(key, params)) {
            return this.dataCache[key].data;
        }

        const requestKey = `${key}:${JSON.stringify(params)}`;
        if (this.loadingStates[requestKey]) return this.loadingStates[requestKey];
        const generation = this.cacheGenerations[key] || 0;
        const request = Promise.resolve()
            .then(loader)
            .then(data => {
                if ((this.cacheGenerations[key] || 0) === generation) {
                    this.updateCache(key, data, params);
                }
                return data;
            })
            .finally(() => {
                if (this.loadingStates[requestKey] === request) delete this.loadingStates[requestKey];
            });
        this.loadingStates[requestKey] = request;
        return request;
    }
    
    /**
     * 使缓存失效
     */
    invalidateCache(key = null) {
        if (key) {
            this.cacheGenerations[key] = (this.cacheGenerations[key] || 0) + 1;
            this.dataCache[key] = { data: null, timestamp: 0, params: null };
        } else {
            Object.keys(this.dataCache).forEach(k => {
                this.cacheGenerations[k] = (this.cacheGenerations[k] || 0) + 1;
                this.dataCache[k] = { data: null, timestamp: 0, params: null };
            });
        }
    }
    }

    window.PicManagerUIModules = window.PicManagerUIModules || [];
    window.PicManagerUIModules.push(EntityCacheModule);
})();
