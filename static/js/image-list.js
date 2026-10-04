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

    async handleOriginalLoad(img) {
        if (img.dataset.sensitiveSrc) return;
        const media = img.closest('.image-detail-media');
        const reader = media?.closest('.library-reader');
        const src = img.src;
        try { await img.decode(); } catch (_) {
            if (img.isConnected && img.src === src) this.handleOriginalError(img);
            return;
        }
        if (reader) await reader.opening;
        if (!img.isConnected || img.src !== src) return;
        media?.classList.remove('is-original-error');
        media?.classList.add('is-original-loaded');
    }

    handleOriginalError(img) {
        img.onerror = null;
        const media = img.closest('.image-detail-media');
        if (!media) return;
        media.classList.add('is-original-error');
        const status = media.querySelector('.image-detail-loading');
        if (status) status.textContent = '原图加载失败，当前显示缩略图';
        media.querySelector('.library-preview-loader')?.setAttribute('hidden', '');
        const retry = media.querySelector('[data-library-retry-original]');
        if (retry) retry.hidden = false;
    }

    renderImageGrid(images) {
        const grid = document.getElementById('image-grid');
        if (!grid) return;
        this.libraryImages = images;
        
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
            <article class="image-card library-image-card ${restricted ? `is-age-restricted is-${rating}` : ''}" data-image-id="${image.image_id}" data-age-revealed="false">
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
                </button>
                <div class="image-card-info library-card-footer">
                    <div class="library-card-identity">
                        <div class="library-role-avatars">${(image.characters?.length ? image.characters.slice(0, 3) : [{}]).map(character => `<img src="${this.getEntityAvatar(character)}" alt="" loading="lazy" decoding="async" onerror="ui.handleEntityAvatarFallback(this)">`).join('')}</div>
                        <div class="library-role-labels"><h4 title="${this.escapeHomeRankingText((image.characters || []).map(character => character.name).join(' · '))}">${this.escapeHomeRankingText((image.characters || []).map(character => character.name).join(' · ') || '未设置角色')}</h4>
                        <p class="library-card-author" title="${this.escapeHomeRankingText((image.groups || []).map(group => group.name).join(' · '))}">${this.escapeHomeRankingText((image.groups || []).map(group => group.name).join(' · ') || '未设置分组')}</p></div>
                    </div>
                    <div class="library-card-actions">
                        <button type="button" class="btn btn-primary" data-library-detail>查看详情</button>
                        <button type="button" class="library-icon-button" data-library-download aria-label="下载原图" ${restricted ? 'disabled title="请先揭示受限内容"' : ''}>${this.libraryIcon('download')}</button>
                    </div>
                </div>
                ${restricted ? `<button type="button" class="image-card-reveal" aria-expanded="false" aria-controls="image-card-media-${image.image_id}">揭示 ${ratingLabel}</button>` : ''}
            </article>
        `;
        }).join('');

        grid.querySelectorAll('.image-card').forEach(card => {
            const open = () => {
                if (card.classList.contains('is-age-restricted') && !card.classList.contains('age-revealed')) {
                    this.toggleAgeReveal(card, true);
                    return;
                }
                const imageId = card.getAttribute('data-image-id');
                this.showImageDetail(imageId, card.querySelector('.image-card-open'));
            };
            card.querySelector('.image-card-open').addEventListener('click', open);
            card.querySelector('[data-library-detail]').addEventListener('click', open);
            card.querySelector('[data-library-download]').addEventListener('click', () => this.downloadImage(card.dataset.imageId));
            card.querySelector('.image-card-reveal')?.addEventListener('click', () => this.toggleAgeReveal(card));
            card.addEventListener('pointerleave', () => card.classList.remove('library-resting'));
            card.addEventListener('pointermove', () => {
                if (card.dataset.readerHover === 'false') card.classList.remove('library-resting');
            });
            card.addEventListener('focusin', () => card.classList.remove('library-resting'));
        });
        this.observeThumbnails(grid);
    }

    libraryIcon(name) {
        const paths = {
            close: '<path d="m6 6 12 12M6 18 18 6"/>',
            download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
            edit: '<path d="m16 3 5 5-12 12-6 1 1-6ZM13 6l5 5"/>',
            trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
            spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5Z"/>'
        };
        return `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ''}</svg>`;
    }

    renderLibraryDetailInfo(image) {
        const esc = value => this.escapeHomeRankingText(value);
        const workId = /^(\d+)(?:_p\d+)?$/.exec(String(image.pid || ''))?.[1];
        const title = esc(image.pid || image.image_id);
        const rating = this.normalizeAgeRating(image.age_rating);
        const restricted = rating === 'r16' || rating === 'r18';
        return `<div class="library-detail-scroll">
            <span class="library-detail-eyebrow">ARTWORK DETAILS</span>
            <h3 id="library-detail-title">${workId ? `<a class="library-artwork-title" href="https://www.pixiv.net/artworks/${workId}" target="_blank" rel="noopener noreferrer" aria-label="在 Pixiv 打开 ${title}">${title}</a>` : title}</h3>
            ${image.artist ? `<button type="button" class="library-artist" data-library-artist="${esc(image.artist.id)}"><img src="/static/icon/Pic.ico" alt="" width="42" height="42"><span>${esc(image.artist.name)}</span></button>` : ''}
            ${this.isAdminView() ? `<section class="library-validation" aria-label="校验状态"><span class="${image.local_verified ? 'is-verified' : ''}">本地${image.local_verified ? '已校验' : '待校验'}</span><span class="${image.pixiv_verified ? 'is-verified' : ''}">Pixiv${image.pixiv_verified ? '已校验' : '待校验'}</span></section>` : ''}
            ${[['分组', image.groups, 'group'], ['角色', image.characters, 'character'], ['特征', image.feature_tags, 'feature_tag']].map(([label, tags, type]) => `<section class="detail-tag-section"><label>${label}</label><div class="detail-chip-row">${this.renderDetailChips(tags, type)}</div></section>`).join('')}
            ${(image.pixiv_tags || []).length ? `<section class="detail-tag-section"><label>Pixiv 标签</label><div class="detail-chip-row">${image.pixiv_tags.map(tag => `<span class="detail-chip">${esc(tag.translated_name || tag.name)}</span>`).join('')}</div></section>` : ''}
            ${image.description ? `<div class="detail-note"><span>备注</span><p>${esc(image.description)}</p></div>` : ''}
            <details class="library-file-info"><summary>文件信息</summary><div class="detail-meta-grid">${this.renderImageMeta(image, true)}</div></details>
            <p class="library-detail-error" role="status" hidden></p>
        </div><div class="library-detail-actions">
            <button type="button" class="btn btn-primary detail-protected-download" data-library-action="download" ${restricted ? 'disabled title="请先揭示受限内容"' : ''}>${this.libraryIcon('download')}下载原图</button>
            <button type="button" class="library-icon-button" data-library-action="edit" aria-label="编辑图片" title="编辑图片">${this.libraryIcon('edit')}</button>
            <button type="button" class="library-icon-button library-delete" data-library-action="delete" aria-label="删除图片" title="删除图片">${this.libraryIcon('trash')}</button>
        </div>`;
    }

    closeImageDetail(restoreFocus = true) {
        const reader = this.libraryReader;
        if (!reader) return;
        this.libraryReader = null;
        ++this.libraryDetailGeneration;
        reader.close();
        reader.remove();
        const source = this.libraryReaderSource;
        const card = source?.closest('.library-image-card');
        if (restoreFocus && source?.isConnected) source.focus({ preventScroll: true });
        if (card?.isConnected) {
            card.classList.add('library-resting');
            card.dataset.readerHover = String(card.matches(':hover'));
        }
    }

    async openLibraryReader(imageId, source = null) {
        this.closeImageDetail(false);
        source = source || Array.from(document.querySelectorAll('#image-grid .image-card')).find(card => card.dataset.imageId === imageId)?.querySelector('.image-card-open');
        this.libraryReaderSource = source || document.activeElement;
        const sourceImage = source?.querySelector('img');
        const sourceRect = sourceImage?.getBoundingClientRect();
        const cached = (this.libraryImages || []).find(image => image.image_id === imageId);
        const reader = document.createElement('dialog');
        reader.className = 'library-reader image-detail-card';
        reader.setAttribute('aria-labelledby', 'library-detail-title');
        reader.innerHTML = `<div class="image-detail-media">
            <img class="image-detail-preview" alt="" aria-hidden="true" onerror="ui.handleImageFallback(this)">
            <img class="image-detail-original" alt="图片 ${this.escapeHomeRankingText(imageId)}" decoding="async" fetchpriority="high" onload="ui.handleOriginalLoad(this)" onerror="ui.handleOriginalError(this)">
            <div class="library-preview-loader" role="status" aria-label="正在加载原图"><span class="library-loading-orbit" aria-hidden="true"><i></i><i></i><i></i></span>${this.libraryIcon('spark')}</div>
            <span class="image-detail-loading" role="status">正在加载原图…</span>
            <button type="button" class="library-original-retry" data-library-retry-original hidden>重试原图</button>
            <button type="button" class="library-reader-close" aria-label="关闭详情">${this.libraryIcon('close')}</button>
            <button type="button" class="library-reader-arrow library-reader-prev" aria-label="上一张">‹</button>
            <button type="button" class="library-reader-arrow library-reader-next" aria-label="下一张">›</button>
        </div><div class="image-detail-panel"><h3 id="library-detail-title">图片 ${this.escapeHomeRankingText(imageId)}</h3><p role="status">正在加载详情…</p></div>`;
        reader.querySelector('.image-detail-preview').src = sourceImage?.currentSrc || this.getThumbnailUrl(cached || { image_id: imageId });
        this.libraryReader = reader;
        const generation = this.libraryDetailGeneration = (this.libraryDetailGeneration || 0) + 1;
        const current = () => reader.isConnected && this.libraryReader === reader && generation === this.libraryDetailGeneration;
        const apply = image => {
            if (!current()) return;
            reader.dataset.imageId = image.image_id;
            const ratio = Number(image.width) / Number(image.height);
            if (Number.isFinite(ratio) && ratio > 0) reader.style.setProperty('--library-image-ratio', String(ratio));
            const media = reader.querySelector('.image-detail-media');
            const rating = this.normalizeAgeRating(image.age_rating), restricted = rating === 'r16' || rating === 'r18';
            const wasRestricted = media.classList.contains('is-age-restricted-detail');
            media.classList.toggle('is-age-restricted-detail', restricted);
            media.classList.toggle('is-r16', rating === 'r16');
            media.classList.toggle('is-r18', rating === 'r18');
            if (restricted && !wasRestricted) {
                media.classList.remove('age-revealed', 'is-original-loaded');
                media.insertAdjacentHTML('beforeend', `<span class="age-rating-badge age-rating-badge-detail">${rating.toUpperCase()}</span><button type="button" class="detail-age-reveal" aria-expanded="false" onclick="ui.toggleDetailAgeReveal(this)">揭示 ${rating.toUpperCase()} 内容</button>`);
            } else if (!restricted) {
                media.querySelector('.detail-age-reveal')?.remove();
                media.querySelector('.age-rating-badge')?.remove();
            }
            const original = media.querySelector('.image-detail-original');
            const blocked = restricted && !media.classList.contains('age-revealed');
            const url = this.getImageUrl(image);
            if (blocked) original.dataset.sensitiveSrc = url;
            else delete original.dataset.sensitiveSrc;
            const displayUrl = blocked ? this.getThumbnailUrl(image) : url;
            if (original.getAttribute('src') !== displayUrl) {
                media.classList.remove('is-original-loaded', 'is-original-error');
                original.onerror = () => this.handleOriginalError(original);
                media.querySelector('.image-detail-loading').textContent = '正在加载原图…';
                media.querySelector('.library-preview-loader').hidden = false;
                media.querySelector('[data-library-retry-original]').hidden = true;
                original.src = displayUrl;
            }
            reader.querySelector('.image-detail-panel').innerHTML = this.renderLibraryDetailInfo(image);
            const download = reader.querySelector('.detail-protected-download');
            download.disabled = blocked;
            download.title = blocked ? '请先揭示受限内容' : '';
        };
        reader.addEventListener('cancel', event => { event.preventDefault(); this.closeImageDetail(); });
        let backdropDown = false;
        reader.addEventListener('pointerdown', event => { backdropDown = event.target === reader; });
        reader.addEventListener('click', event => {
            if (event.target === reader && backdropDown) return this.closeImageDetail();
            if (event.target.closest('.library-reader-close')) return this.closeImageDetail();
            const artist = event.target.closest('[data-library-artist]');
            if (artist) return this.showArtistImages(artist.dataset.libraryArtist);
            const action = event.target.closest('[data-library-action]')?.dataset.libraryAction;
            if (action === 'download') this.downloadImage(imageId);
            if (action === 'edit') { this.closeImageDetail(false); this.editImage(imageId); }
            if (action === 'delete') this.deleteImage(imageId);
        });
        const images = this.libraryImages || [], index = images.findIndex(image => image.image_id === imageId);
        const navigate = delta => {
            const next = images[index + delta];
            if (index >= 0 && next) this.showImageDetail(next.image_id);
        };
        for (const [selector, delta] of [['.library-reader-prev', -1], ['.library-reader-next', 1]]) {
            const button = reader.querySelector(selector);
            button.hidden = index < 0 || images.length < 2;
            button.disabled = !images[index + delta];
            button.onclick = () => navigate(delta);
        }
        reader.addEventListener('keydown', event => {
            if (event.target.matches('input,textarea,select') || Array.from(document.querySelectorAll('dialog[open]')).at(-1) !== reader) return;
            if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); navigate(event.key === 'ArrowLeft' ? -1 : 1); }
        });
        reader.querySelector('[data-library-retry-original]').onclick = () => {
            const media = reader.querySelector('.image-detail-media'), original = media.querySelector('.image-detail-original');
            if (media.classList.contains('is-age-restricted-detail') && !media.classList.contains('age-revealed')) return;
            media.classList.remove('is-original-error');
            media.querySelector('.library-preview-loader').hidden = false;
            media.querySelector('.image-detail-loading').textContent = '正在加载原图…';
            reader.querySelector('[data-library-retry-original]').hidden = true;
            original.onerror = () => this.handleOriginalError(original);
            const url = original.src; original.removeAttribute('src'); original.src = url;
        };
        document.body.append(reader);
        if (cached) apply(cached);
        reader.showModal();
        reader.querySelector('.library-reader-close').focus({ preventScroll: true });
        reader.opening = Promise.resolve();
        if (!matchMedia('(prefers-reduced-motion:reduce)').matches) {
            const media = reader.querySelector('.image-detail-media'), target = media.getBoundingClientRect();
            const from = sourceRect?.width && sourceRect?.height ? `translate(${sourceRect.left - target.left}px,${sourceRect.top - target.top}px) scale(${sourceRect.width / target.width},${sourceRect.height / target.height})` : 'scale(.92)';
            const picture = media.animate([{ transform: from, opacity: .7 }, { transform: 'none', opacity: 1 }], { duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)' });
            const info = reader.querySelector('.image-detail-panel').animate([{ opacity: 0, transform: 'translateY(14px)' }, { opacity: 1, transform: 'none' }], { duration: 280, delay: 100, fill: 'backwards' });
            reader.opening = picture.finished.catch(() => {});
            reader.addEventListener('close', () => { picture.cancel(); info.cancel(); }, { once: true });
        }
        try {
            const image = await api.getImage(imageId);
            apply(image);
        } catch (error) {
            if (!current()) return;
            if (error.status === 404 || /404|Image not found/.test(error.message || '')) {
                this.closeImageDetail();
                this.showModal('这张图现在打不开', `<div class="empty-state"><p>这张图的原文件找不到了，可以重新检查一下。</p>${this.isAdminView() ? '<button type="button" class="btn btn-primary" onclick="syncImageStatus()">重新检查</button>' : ''}</div>`);
            } else {
                const panel = reader.querySelector('.image-detail-panel');
                if (!cached) {
                    reader.querySelector('.library-preview-loader').hidden = true;
                    reader.querySelector('.image-detail-loading').textContent = '图片信息加载失败';
                }
                const status = panel.querySelector('.library-detail-error') || panel.querySelector('[role="status"]');
                status.hidden = false;
                status.textContent = '详情加载失败，请重试。';
                const retry = document.createElement('button'); retry.className = 'btn btn-secondary'; retry.textContent = '重试详情';
                retry.onclick = () => this.showImageDetail(imageId, source); status.after(retry);
            }
        }
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
        const download = card.querySelector('[data-library-download]');
        if (download) { download.disabled = !reveal; download.title = reveal ? '' : '请先揭示受限内容'; }
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
            artist: document.getElementById('search-artist')?.value || null,
            age_rating: document.getElementById('search-age-rating')?.value || null
        };
    }
    }

    window.PicManagerUIModules = window.PicManagerUIModules || [];
    window.PicManagerUIModules.push(ImageListModule);
})();
