(function () {
    'use strict';

    class ImageListModule {
    async loadImages(params = undefined) {
        const requestId = ++this.imageLoadRequestId;
        const grid = document.getElementById('image-grid');
        if (grid) {
            grid.setAttribute('aria-busy', 'true');
            grid.innerHTML = '<div class="image-grid-state image-grid-loading" role="status">正在加载图片…</div>';
        }
        try {
            this.applyRolePreferences();
            if (params !== undefined && params !== null) {
                this.activeImageSearchParams = { ...params };
            }

            const searchParams = {
                ...(this.activeImageSearchParams || {}),
                limit: this.pagination.limit,
                offset: (this.pagination.currentPage - 1) * this.pagination.limit
            };

            const result = await api.searchImages(searchParams);
            if (requestId !== this.imageLoadRequestId) return;
            const totalPages = Math.max(1, Math.ceil((result.total || 0) / this.pagination.limit));
            if ((result.images || []).length === 0 && (result.total || 0) > 0 && this.pagination.currentPage > totalPages) {
                this.pagination.currentPage = totalPages;
                return this.loadImages(null);
            }

            this.renderImageGrid(result.images || []);
            this.updatePagination(result);
            grid?.setAttribute('aria-busy', 'false');
        } catch (error) {
            if (requestId === this.imageLoadRequestId) {
                if (grid) {
                    grid.setAttribute('aria-busy', 'false');
                    grid.innerHTML = `
                        <div class="image-grid-state image-grid-error" role="alert">
                            <p>图片加载失败，请检查网络后重试。</p>
                            <button type="button" class="btn btn-primary" onclick="ui.loadImages(null)">重新加载</button>
                        </div>
                    `;
                }
                this.showToast('加载图片失败', 'error');
            }
        }
    }

    async loadFeatureTagsData(forceRefresh = false, throwOnError = false) {
        try {
            const tags = await this.loadCachedEntity('featureTags', () => api.getFeatureTags(), { forceRefresh });
            this.allFeatureTags = tags;
            if (window.PinyinSearch) {
                window.PinyinSearch.learnWords(tags.map(tag => tag.name));
            }
            return tags;
        } catch (error) {
            if (throwOnError) throw error;
            this.showToast('加载特征标签失败', 'error');
            return this.allFeatureTags || [];
        }
    }

    getImageVersion(image) {
        const version = image.updated_at || image.file_checked_at || image.created_at || image.file_size || '1';
        return encodeURIComponent(String(version));
    }

    getImageUrl(image) {
        return `/resource/originals/${encodeURIComponent(image.image_id)}?v=${this.getImageVersion(image)}`;
    }

    getThumbnailUrl(image) {
        return `/resource/thumbs/${encodeURIComponent(image.image_id)}.webp?v=${this.getImageVersion(image)}`;
    }

    getPreviewUrl(image) {
        return `/resource/previews/${encodeURIComponent(image.image_id)}.webp?v=${this.getImageVersion(image)}`;
    }

    downloadImage(imageId) {
        const link = document.createElement('a');
        link.href = api.getImageDownloadUrl(imageId);
        link.download = '';
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
    }

    handleImageFallback(img) {
        img.onerror = null;
        img.src = '/static/images/placeholder.png';
    }

    observeThumbnails(container) {
        if (this.thumbnailObserver) {
            this.thumbnailObserver.disconnect();
            this.thumbnailObserver = null;
        }

        const thumbnails = Array.from(container.querySelectorAll('img[data-thumbnail-src]'));
        const loadThumbnail = (img) => {
            const src = img.dataset.thumbnailSrc;
            if (!src) return;
            img.src = src;
            delete img.dataset.thumbnailSrc;
        };

        if (!('IntersectionObserver' in window)) {
            thumbnails.forEach(loadThumbnail);
            return;
        }

        this.thumbnailObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach((entry) => {
                if (!entry.isIntersecting) return;
                loadThumbnail(entry.target);
                observer.unobserve(entry.target);
            });
        }, {
            rootMargin: '600px 0px',
            threshold: 0.01
        });
        thumbnails.forEach((img) => this.thumbnailObserver.observe(img));
    }

    handleOriginalLoad(img) {
        img.closest('.image-detail-media')?.classList.add('is-original-loaded');
    }

    handleOriginalError(img) {
        img.onerror = null;
        const media = img.closest('.image-detail-media');
        if (!media) return;
        media.classList.add('is-original-error');
        const status = media.querySelector('.image-detail-loading');
        if (status) status.textContent = '原图加载失败，当前显示缩略图';
    }

    renderImageGrid(images) {
        const grid = document.getElementById('image-grid');
        if (!grid) return;
        
        if (images.length === 0) {
            if (this.thumbnailObserver) {
                this.thumbnailObserver.disconnect();
                this.thumbnailObserver = null;
            }
            grid.setAttribute('aria-busy', 'false');
            grid.innerHTML = '<div class="empty-state" role="status">未找到图片</div>';
            return;
        }

        grid.innerHTML = images.map(image => {
            const rating = this.normalizeAgeRating(image.age_rating);
            const restricted = rating === 'r16' || rating === 'r18';
            const ratingLabel = rating.toUpperCase();
            const cardLabel = this.escapeHomeRankingText(`${this.formatImageTags(image)}，图片 ${image.image_id}${restricted ? `，${ratingLabel} 内容，尚未揭示` : ''}`);
            return `
            <article class="image-card ${restricted ? `is-age-restricted is-${rating}` : ''}" data-image-id="${image.image_id}" data-age-revealed="false">
                <button type="button" class="image-card-open" aria-label="${cardLabel}">
                    <div class="image-card-media" id="image-card-media-${image.image_id}">
                        <img class="image-card-img" src="/static/images/placeholder.png"
                             data-thumbnail-src="${this.getThumbnailUrl(image)}"
                             alt="${cardLabel}" loading="lazy" decoding="async"
                             fetchpriority="low"
                             onerror="ui.handleImageFallback(this)">
                        ${restricted ? `
                            <span class="age-rating-badge">${ratingLabel}</span>
                            <span class="age-content-curtain" aria-hidden="true">受限内容已隐藏</span>
                        ` : ''}
                    </div>
                    <div class="image-card-info">
                        <div class="image-card-id">${image.image_id}</div>
                        <div class="image-card-characters">
                            ${this.formatImageTags(image)}
                        </div>
                        ${image.pid ? `<div class="image-card-pid">PID: ${this.escapeHomeRankingText(image.pid)}</div>` : ''}
                    </div>
                </button>
                ${restricted ? `<button type="button" class="image-card-reveal" aria-expanded="false" aria-controls="image-card-media-${image.image_id}">揭示 ${ratingLabel}</button>` : ''}
            </article>
        `;
        }).join('');

        grid.querySelectorAll('.image-card').forEach(card => {
            card.querySelector('.image-card-open').addEventListener('click', () => {
                if (card.classList.contains('is-age-restricted') && !card.classList.contains('age-revealed')) {
                    this.toggleAgeReveal(card, true);
                    return;
                }
                const imageId = card.getAttribute('data-image-id');
                this.showImageDetail(imageId);
            });
            card.querySelector('.image-card-reveal')?.addEventListener('click', () => this.toggleAgeReveal(card));
        });
        this.observeThumbnails(grid);
    }

    normalizeAgeRating(value) {
        return String(value || 'all').trim().toLowerCase();
    }

    toggleAgeReveal(card, forceReveal = null) {
        const reveal = forceReveal === null ? !card.classList.contains('age-revealed') : Boolean(forceReveal);
        card.classList.toggle('age-revealed', reveal);
        card.dataset.ageRevealed = String(reveal);
        const button = card.querySelector('.image-card-reveal');
        const rating = card.classList.contains('is-r18') ? 'R18' : 'R16';
        if (button) {
            button.setAttribute('aria-expanded', String(reveal));
            button.textContent = reveal ? `隐藏 ${rating}` : `揭示 ${rating}`;
        }
        const openButton = card.querySelector('.image-card-open');
        if (openButton) {
            openButton.setAttribute('aria-label', openButton.getAttribute('aria-label').replace('，尚未揭示', reveal ? '，已揭示' : '，尚未揭示').replace('，已揭示', reveal ? '，已揭示' : '，尚未揭示'));
        }
    }

    formatImageTags(image) {
        const groups = image.groups || [];
        const characters = image.characters || [];
        const usedGroupIds = new Set();
        const parts = groups.map(group => {
            const names = characters
                .filter(character => character.group_id === group.id)
                .map(character => this.escapeHomeRankingText(character.name));
            usedGroupIds.add(group.id);
            return [this.escapeHomeRankingText(group.name), ...names].join('-');
        });
        characters
            .filter(character => !usedGroupIds.has(character.group_id))
            .forEach(character => {
                const groupName = character.group_name || (character.group && character.group.name);
                parts.push([groupName, character.name]
                    .filter(Boolean)
                    .map(value => this.escapeHomeRankingText(value))
                    .join('-'));
            });
        return parts.length ? parts.join(' ') : '未添加标签';
    }

    buildPageWindow(totalPages, currentPage) {
        const maxButtons = Math.max(7, this.pagination.maxButtons || 11);
        if (totalPages <= maxButtons) {
            return Array.from({ length: totalPages }, (_, index) => index + 1);
        }

        const dynamicRadius = Math.min(4, Math.max(2, Math.floor(totalPages * 0.04)));
        let start = Math.max(2, currentPage - dynamicRadius);
        let end = Math.min(totalPages - 1, currentPage + dynamicRadius);
        const innerLimit = maxButtons - 2;

        while ((end - start + 1) < innerLimit && start > 2) start--;
        while ((end - start + 1) < innerLimit && end < totalPages - 1) end++;

        const pages = [1];
        if (start > 2) pages.push('gap-start');
        for (let page = start; page <= end; page++) pages.push(page);
        if (end < totalPages - 1) pages.push('gap-end');
        pages.push(totalPages);
        return pages;
    }

    updatePagination(result) {
        const total = result.total || 0;
        this.pagination.totalPages = Math.max(1, Math.ceil(total / this.pagination.limit));
        
        const paginationContainer = document.getElementById('pagination');
        if (!paginationContainer) return;
        if (this.pagination.totalPages <= 1 && total <= this.pagination.limit) {
            paginationContainer.innerHTML = '';
            return;
        }

        const pageItems = this.buildPageWindow(this.pagination.totalPages, this.pagination.currentPage);
        const isAdmin = this.isAdminView();
        let html = `
            <button class="pagination-btn pagination-edge" ${this.pagination.currentPage === 1 ? 'disabled' : ''} 
                    onclick="ui.changePage(1)">首页</button>
            <button class="pagination-btn" ${this.pagination.currentPage === 1 ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.currentPage - 1})">上一页</button>
        `;

        pageItems.forEach((item) => {
            if (typeof item === 'string') {
                html += '<span class="pagination-ellipsis">...</span>';
                return;
            }
            html += `
                <button class="pagination-btn ${item === this.pagination.currentPage ? 'active' : ''}" 
                        onclick="ui.changePage(${item})">${item}</button>
            `;
        });

        html += `
            <button class="pagination-btn" ${this.pagination.currentPage === this.pagination.totalPages ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.currentPage + 1})">下一页</button>
            <button class="pagination-btn pagination-edge" ${this.pagination.currentPage === this.pagination.totalPages ? 'disabled' : ''} 
                    onclick="ui.changePage(${this.pagination.totalPages})">末页</button>
            <span class="pagination-summary">${this.pagination.currentPage} / ${this.pagination.totalPages} · ${total}</span>
            ${isAdmin ? `
                <select class="pagination-size" onchange="ui.changePageSize(this.value)" aria-label="每页数量">
                    ${[20, 50, 100].map(size => `<option value="${size}" ${size === this.pagination.limit ? 'selected' : ''}>${size}/页</option>`).join('')}
                </select>
            ` : '<span class="pagination-size locked">20/页</span>'}
            <span class="pagination-jump">
                <input class="pagination-input" id="pagination-jump-input" type="number" min="1" max="${this.pagination.totalPages}" value="${this.pagination.currentPage}" aria-label="跳转页码">
                <button class="pagination-btn" onclick="ui.jumpToPage()">跳转</button>
            </span>
        `;

        paginationContainer.innerHTML = html;
    }

    changePage(page) {
        if (page < 1 || page > this.pagination.totalPages) return;
        this.pagination.currentPage = page;
        this.loadImages(null);
    }

    changePageSize(value) {
        if (!this.isAdminView()) return;
        const nextLimit = parseInt(value, 10);
        if (!Number.isFinite(nextLimit) || ![20, 50, 100].includes(nextLimit) || nextLimit === this.pagination.limit) return;
        this.pagination.limit = nextLimit;
        this.pagination.currentPage = 1;
        this.loadImages(null);
    }

    jumpToPage() {
        const input = document.getElementById('pagination-jump-input');
        const page = parseInt(input?.value, 10);
        if (!Number.isFinite(page)) return;
        this.changePage(Math.min(Math.max(page, 1), this.pagination.totalPages));
    }
    getSearchParams() {
        return {
            group_id: document.getElementById('search-group').value || null,
            character_id: document.getElementById('search-character').value || null,
            pid: document.getElementById('search-pid').value || null,
            age_rating: document.getElementById('search-age-rating')?.value || null
        };
    }
    }

    window.PicManagerUIModules = window.PicManagerUIModules || [];
    window.PicManagerUIModules.push(ImageListModule);
})();
