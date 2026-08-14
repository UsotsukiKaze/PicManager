// API调用封装
class API {
    constructor(baseURL = '/api') {
        this.baseURL = baseURL;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const config = {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers,
            },
            ...options,
        };

        try {
            const response = await fetch(url, config);
            
            if (!response.ok) {
                let errorMessage = `HTTP ${response.status}`;
                try {
                    const errorData = await response.json();
                    errorMessage = errorData.detail || errorMessage;
                } catch {
                    // 无法解析JSON，使用默认错误消息
                }
                const requestError = new Error(errorMessage);
                requestError.status = response.status;
                throw requestError;
            }

            return await response.json();
        } catch (error) {
            // 区分网络错误和HTTP错误
            if (error.name === 'TypeError' && error.message === 'Failed to fetch') {
                console.error(`API Network Error (${endpoint}):`, error);
                throw new Error('网络连接失败，请检查网络');
            }
            console.error(`API Error (${endpoint}):`, error);
            throw error;
        }
    }

    // 分组相关API
    hasExplicitPage(options = {}) {
        return Object.prototype.hasOwnProperty.call(options, 'limit')
            || Object.prototype.hasOwnProperty.call(options, 'skip');
    }

    async requestAllPages(endpoint, baseParams = {}, options = {}) {
        const items = [];
        let skip = 0;
        let pageSize = options.pageSize ?? 100;
        const maxItems = options.maxItems ?? 10000;

        while (items.length < maxItems) {
            const params = new URLSearchParams(baseParams);
            params.set('limit', pageSize);
            params.set('skip', skip);

            let page;
            try {
                page = await this.request(`${endpoint}?${params.toString()}`);
            } catch (error) {
                if (error.status === 422 && items.length === 0 && pageSize > 1) {
                    pageSize = Math.max(1, Math.floor(pageSize / 2));
                    continue;
                }
                throw error;
            }

            if (!Array.isArray(page)) {
                throw new Error(`Invalid list response from ${endpoint}`);
            }
            items.push(...page);
            if (page.length < pageSize) break;
            skip += page.length;
        }

        if (items.length >= maxItems) {
            throw new Error(`List response from ${endpoint} exceeded ${maxItems} items`);
        }
        return items;
    }

    async getGroups(options = {}) {
        if (this.hasExplicitPage(options)) {
            const params = new URLSearchParams({
                limit: options.limit ?? 100,
                skip: options.skip ?? 0,
            });
            return this.request(`/groups/?${params.toString()}`);
        }
        return this.requestAllPages('/groups/');
    }

    async getPopularGroups(limit = 5) {
        return this.request(`/groups/popular?limit=${encodeURIComponent(limit)}`);
    }

    async createGroup(data) {
        return this.request('/groups/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateGroup(id, data) {
        return this.request(`/groups/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteGroup(id) {
        return this.request(`/groups/${id}`, {
            method: 'DELETE',
        });
    }

    // 角色相关API
    async getCharacters(groupId = null, options = {}) {
        const params = new URLSearchParams();
        if (groupId) {
            params.set('group_id', groupId);
        }
        if (!this.hasExplicitPage(options)) {
            return this.requestAllPages('/characters/', params);
        }
        params.set('limit', options.limit ?? 100);
        params.set('skip', options.skip ?? 0);
        return this.request(`/characters/?${params.toString()}`);
    }

    async createCharacter(data) {
        return this.request('/characters/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateCharacter(id, data) {
        return this.request(`/characters/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteCharacter(id) {
        return this.request(`/characters/${id}`, {
            method: 'DELETE',
        });
    }

    async processAvatar(file, options = {}) {
        const formData = new FormData();
        formData.append('file', file, 'avatar-crop.png');
        const controller = new AbortController();
        const timeoutMs = options.timeoutMs ?? 30000;
        const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
        const abortFromCaller = () => controller.abort();
        options.signal?.addEventListener('abort', abortFromCaller, { once: true });
        try {
            return await this.request('/avatars/process', {
                method: 'POST',
                headers: {},
                body: formData,
                signal: controller.signal,
            });
        } catch (error) {
            if (error.name === 'AbortError') {
                throw new Error(options.signal?.aborted ? '头像上传已取消' : '头像上传超时，请检查网络后重试');
            }
            throw error;
        } finally {
            window.clearTimeout(timeout);
            options.signal?.removeEventListener('abort', abortFromCaller);
        }
    }

    async getFeatureTags(options = {}) {
        if (!this.hasExplicitPage(options)) {
            return this.requestAllPages('/feature-tags/');
        }
        const params = new URLSearchParams();
        params.set('limit', options.limit ?? 100);
        params.set('skip', options.skip ?? 0);
        return this.request(`/feature-tags/?${params.toString()}`);
    }

    async createFeatureTag(data) {
        return this.request('/feature-tags/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateFeatureTag(id, data) {
        return this.request(`/feature-tags/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteFeatureTag(id) {
        return this.request(`/feature-tags/${id}`, {
            method: 'DELETE',
        });
    }

    async getEmotionTags(options = {}) {
        if (!this.hasExplicitPage(options)) {
            return this.requestAllPages('/emotion-tags/');
        }
        const params = new URLSearchParams();
        params.set('limit', options.limit ?? 100);
        params.set('skip', options.skip ?? 0);
        return this.request(`/emotion-tags/?${params.toString()}`);
    }

    async createEmotionTag(data) {
        return this.request('/emotion-tags/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateEmotionTag(id, data) {
        return this.request(`/emotion-tags/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteEmotionTag(id) {
        return this.request(`/emotion-tags/${id}`, {
            method: 'DELETE',
        });
    }

    async searchEmojis(params = {}) {
        const queryString = new URLSearchParams(
            Object.entries(params).filter(([_, v]) => v !== null && v !== '')
        ).toString();
        return this.request(`/emojis/search?${queryString}`);
    }

    async getEmoji(id) {
        return this.request(`/emojis/${encodeURIComponent(id)}`);
    }

    async uploadEmoji(file, metadata) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('character_ids', JSON.stringify(metadata.character_ids || []));
        formData.append('group_ids', JSON.stringify(metadata.group_ids || []));
        formData.append('emotion_ids', JSON.stringify(metadata.emotion_ids || []));
        if (metadata.description) formData.append('description', metadata.description);
        return this.request('/emojis/upload', {
            method: 'POST',
            headers: {},
            body: formData,
        });
    }

    async updateEmoji(id, metadata) {
        return this.request(`/emojis/${encodeURIComponent(id)}`, {
            method: 'PUT',
            body: JSON.stringify({
                group_ids: metadata.group_ids || [],
                character_ids: metadata.character_ids || [],
                emotion_ids: metadata.emotion_ids || [],
                description: metadata.description || null,
            }),
        });
    }

    async deleteEmoji(id) {
        return this.request(`/emojis/${id}`, {
            method: 'DELETE',
        });
    }

    // 图片相关API
    async searchImages(params = {}) {
        const queryString = new URLSearchParams(
            Object.entries(params).filter(([_, v]) => v !== null && v !== '')
        ).toString();
        
        return this.request(`/images/search?${queryString}`);
    }

    async getImage(id) {
        return this.request(`/images/${id}`);
    }

    getImageDownloadUrl(id) {
        return `${this.baseURL}/images/${encodeURIComponent(id)}/download`;
    }

    async updateImage(id, data) {
        return this.request(`/images/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteImage(id) {
        return this.request(`/images/${id}`, {
            method: 'DELETE',
        });
    }

    // 上传相关API
    async uploadSingleImage(file, metadata, onProgress = null) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('character_ids', JSON.stringify(metadata.character_ids));
        formData.append('group_ids', JSON.stringify(metadata.group_ids || []));
        formData.append('feature_tag_ids', JSON.stringify(metadata.feature_tag_ids || []));
        formData.append('age_rating', metadata.age_rating || 'all');
        formData.append('emotion_ids', JSON.stringify(metadata.emotion_ids || []));
        
        if (metadata.group_id) formData.append('group_id', metadata.group_id);
        if (metadata.pid) formData.append('pid', metadata.pid);
        if (metadata.description) formData.append('description', metadata.description);

        if (typeof onProgress === 'function') {
            return this.uploadWithProgress('/upload/single', formData, onProgress);
        }

        return this.request('/upload/single', {
            method: 'POST',
            headers: {}, // 让浏览器设置Content-Type
            body: formData,
        });
    }

    uploadWithProgress(endpoint, formData, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${this.baseURL}${endpoint}`);
            xhr.upload.onprogress = (event) => {
                if (event.lengthComputable) {
                    onProgress(Math.round((event.loaded / event.total) * 100));
                }
            };
            xhr.onload = () => {
                let data = null;
                try {
                    data = xhr.responseText ? JSON.parse(xhr.responseText) : null;
                } catch {
                    data = null;
                }
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(data);
                } else {
                    const error = new Error((data && data.detail) || `HTTP ${xhr.status}`);
                    error.status = xhr.status;
                    reject(error);
                }
            };
            xhr.onerror = () => reject(new Error('网络连接失败，请检查网络'));
            xhr.ontimeout = () => reject(new Error('上传超时，请稍后重试'));
            xhr.timeout = 5 * 60 * 1000;
            xhr.send(formData);
        });
    }

    async getTempCount() {
        return this.request('/upload/temp-count');
    }

    async getTempImages() {
        return this.request('/upload/temp-images');
    }

    async uploadTempImage(data) {
        return this.request('/upload/temp', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }    
    async resolveDuplicateImage(token, keep, metadataSources = {}) {
        return this.request('/upload/duplicates/resolve', {
            method: 'POST',
            body: JSON.stringify({ token, keep, metadata_sources: metadataSources }),
        });
    }
    async deleteTempImage(filename) {
        return this.request(`/upload/temp/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
    }
    // 系统相关API
    async getSystemStatus() {
        return this.request('/system/status');
    }

    async getSystemDiagnostics() {
        return this.request('/system/diagnostics');
    }

    async cleanupPreview() {
        return this.request('/system/cleanup-preview');
    }

    async syncImageStatus() {
        return this.request('/system/sync-image-status', {
            method: 'POST',
        });
    }

    async cleanupOrphaned(mode = 'archive') {
        return this.request(`/system/cleanup?mode=${encodeURIComponent(mode)}`, {
            method: 'POST',
        });
    }

    async rebuildThumbnails(limit = 200, force = false) {
        return this.request(`/system/rebuild-thumbnails?limit=${encodeURIComponent(limit)}&force=${encodeURIComponent(force)}`, {
            method: 'POST',
        });
    }

    async scanStoreOrphans() {
        return this.request('/system/scan-store-orphans', {
            method: 'POST',
        });
    }

    async scanExistingDuplicates(limit = 25, excludedPairs = []) {
        return this.request(`/system/duplicates/scan?limit=${encodeURIComponent(limit)}`, {
            method: 'POST',
            body: JSON.stringify({ excluded_pairs: excludedPairs }),
        });
    }

    async resolveExistingDuplicates(imageIds, action, keepImageId = null, metadataSources = {}) {
        return this.request('/system/duplicates/resolve', {
            method: 'POST',
            body: JSON.stringify({
                image_ids: imageIds,
                action,
                keep_image_id: keepImageId,
                metadata_sources: metadataSources,
            }),
        });
    }

    // 榜单
    async getRankings(limit = 10) {
        return this.request(`/rankings?limit=${limit}`);
    }
}

// 创建全局API实例
window.api = new API();
