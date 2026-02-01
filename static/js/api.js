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
                throw new Error(errorMessage);
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
    async getGroups() {
        return this.request('/groups/');
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
    async getCharacters(groupId = null) {
        const params = groupId ? `?group_id=${groupId}` : '';
        return this.request(`/characters/${params}`);
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
    async uploadSingleImage(file, metadata) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('character_ids', JSON.stringify(metadata.character_ids));
        
        if (metadata.group_id) formData.append('group_id', metadata.group_id);
        if (metadata.pid) formData.append('pid', metadata.pid);
        if (metadata.description) formData.append('description', metadata.description);

        return this.request('/upload/single', {
            method: 'POST',
            headers: {}, // 让浏览器设置Content-Type
            body: formData,
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
    async deleteTempImage(filename) {
        return this.request(`/upload/temp/${encodeURIComponent(filename)}`, {
            method: 'DELETE'
        });
    }
    // 系统相关API
    async getSystemStatus() {
        return this.request('/system/status');
    }

    async cleanupOrphaned() {
        return this.request('/system/cleanup', {
            method: 'POST',
        });
    }

    // 榜单
    async getRankings(limit = 10) {
        return this.request(`/rankings?limit=${limit}`);
    }
}

// 创建全局API实例
window.api = new API();