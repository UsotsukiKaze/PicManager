(function () {
    'use strict';

    const ACTIVE_STATES = new Set(['queued', 'uploading', 'processing', 'attention']);
    const FINISHED_STATES = new Set(['success', 'cancelled']);

    class UploadQueueDock {
        constructor() {
            this.tasks = [];
            this.nextId = 1;
            this.open = false;
            this.mount();
        }

        mount() {
            this.root = document.getElementById('upload-queue-dock');
            if (!this.root) return;
            this.toggleButton = document.getElementById('upload-queue-toggle');
            this.panel = document.getElementById('upload-queue-panel');
            this.list = document.getElementById('upload-queue-list');
            this.badge = document.getElementById('upload-queue-badge');
            this.summary = document.getElementById('upload-queue-summary');

            this.toggleButton?.addEventListener('click', () => {
                if (this.open) {
                    this.dismiss();
                    return;
                }
                this.root?.classList.remove('is-hover-dismissed');
                this.setOpen(true);
            });
            document.getElementById('upload-queue-close')?.addEventListener('click', event => {
                event.stopPropagation();
                this.dismiss();
            });
            this.root.addEventListener('pointerleave', () => {
                this.root?.classList.remove('is-hover-dismissed');
            });
            document.getElementById('upload-queue-clear')?.addEventListener('click', () => this.clearFinished());
            this.list?.addEventListener('click', event => {
                const action = event.target.closest('[data-queue-action]');
                if (!action) return;
                const taskId = Number(action.dataset.taskId);
                if (action.dataset.queueAction === 'retry') this.retry(taskId);
                if (action.dataset.queueAction === 'remove') this.remove(taskId);
            });
            window.addEventListener('beforeunload', event => {
                if (!this.tasks.some(task => ACTIVE_STATES.has(task.status))) return;
                event.preventDefault();
                event.returnValue = '';
            });
            this.root.hidden = false;
            this.render();
        }

        escape(value) {
            if (window.PicManagerSecurity) return window.PicManagerSecurity.escapeHTML(value);
            const node = document.createElement('span');
            node.textContent = String(value ?? '');
            return node.innerHTML;
        }

        setOpen(open) {
            this.open = Boolean(open);
            this.root?.classList.toggle('is-open', this.open);
            this.toggleButton?.setAttribute('aria-expanded', String(this.open));
            if (this.panel) this.panel.setAttribute('aria-hidden', String(!this.open));
        }

        dismiss() {
            this.setOpen(false);
            this.root?.classList.add('is-hover-dismissed');
        }

        add({ name, size = 0, status = 'queued', message = '等待上传', retry = null, dispose = null }) {
            const task = {
                id: this.nextId++,
                name: String(name || '未命名图片'),
                size: Number(size || 0),
                status,
                progress: 0,
                message,
                retry,
                dispose,
            };
            this.tasks.unshift(task);
            this.render();
            return task.id;
        }

        get(taskId) {
            return this.tasks.find(task => task.id === Number(taskId)) || null;
        }

        update(taskId, patch = {}) {
            const task = this.get(taskId);
            if (!task) return;
            Object.assign(task, patch);
            task.progress = Math.min(100, Math.max(0, Number(task.progress || 0)));
            this.render();
        }

        async retry(taskId) {
            const task = this.get(taskId);
            if (!task || task.status !== 'failed' || typeof task.retry !== 'function') return;
            this.update(taskId, { status: 'queued', progress: 0, message: '等待重试' });
            try {
                await task.retry();
            } catch (error) {
                // The owning upload flow records its own user-facing failure.
                console.error('Queued upload retry failed:', error);
            }
        }

        remove(taskId) {
            const index = this.tasks.findIndex(task => task.id === Number(taskId));
            if (index < 0 || ACTIVE_STATES.has(this.tasks[index].status)) return;
            const [task] = this.tasks.splice(index, 1);
            if (typeof task.dispose === 'function') task.dispose();
            this.render();
        }

        clearFinished() {
            const removed = this.tasks.filter(task => FINISHED_STATES.has(task.status));
            this.tasks = this.tasks.filter(task => !FINISHED_STATES.has(task.status));
            removed.forEach(task => {
                if (typeof task.dispose === 'function') task.dispose();
            });
            this.render();
        }

        formatSize(bytes) {
            if (!bytes) return '';
            if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KiB`;
            return `${(bytes / 1024 / 1024).toFixed(1)} MiB`;
        }

        renderTask(task) {
            const labels = {
                queued: '排队中',
                uploading: '上传中',
                processing: '服务器处理中',
                attention: '等待确认',
                success: '已完成',
                failed: '失败',
                cancelled: '已取消',
            };
            const retry = task.status === 'failed' && typeof task.retry === 'function'
                ? `<button type="button" data-queue-action="retry" data-task-id="${task.id}">重试</button>`
                : '';
            const removable = !ACTIVE_STATES.has(task.status)
                ? `<button type="button" data-queue-action="remove" data-task-id="${task.id}" aria-label="移除 ${this.escape(task.name)}">移除</button>`
                : '';
            return `
                <li class="upload-queue-item is-${task.status}">
                    <div class="upload-queue-item-head">
                        <strong title="${this.escape(task.name)}">${this.escape(task.name)}</strong>
                        <span>${this.formatSize(task.size)}</span>
                    </div>
                    <div class="upload-queue-item-state">
                        <span>${labels[task.status] || task.status}</span>
                        <small>${this.escape(task.message || '')}</small>
                    </div>
                    <progress max="100" value="${task.progress}" ${ACTIVE_STATES.has(task.status) ? '' : 'hidden'}></progress>
                    ${(retry || removable) ? `<div class="upload-queue-item-actions">${retry}${removable}</div>` : ''}
                </li>
            `;
        }

        render() {
            if (!this.root) return;
            const active = this.tasks.filter(task => ACTIVE_STATES.has(task.status));
            const progressValues = active.map(task => task.progress || 0);
            const progress = progressValues.length
                ? Math.round(progressValues.reduce((sum, value) => sum + value, 0) / progressValues.length)
                : 0;
            this.root.style.setProperty('--queue-progress', `${progress * 3.6}deg`);
            if (this.badge) {
                this.badge.textContent = String(active.length || this.tasks.length || 0);
                this.badge.hidden = this.tasks.length === 0;
            }
            if (this.summary) {
                const attention = this.tasks.filter(task => task.status === 'attention').length;
                const failed = this.tasks.filter(task => task.status === 'failed').length;
                this.summary.textContent = attention
                    ? `${attention} 项等待确认`
                    : failed
                        ? `${failed} 项失败`
                        : active.length
                            ? `${active.length} 项处理中`
                            : this.tasks.length
                                ? '上传任务已完成'
                                : '暂无上传任务';
            }
            if (this.list) {
                this.list.innerHTML = this.tasks.length
                    ? this.tasks.map(task => this.renderTask(task)).join('')
                    : '<li class="upload-queue-empty">提交图片后，进度会显示在这里</li>';
            }
            this.root.classList.toggle('has-attention', this.tasks.some(task => task.status === 'attention'));
            this.root.classList.toggle('has-failure', this.tasks.some(task => task.status === 'failed'));
        }
    }

    window.uploadQueue = new UploadQueueDock();
})();
