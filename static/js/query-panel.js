(function () {
    'use strict';

    class QueryPanelController {
        constructor() {
            document.addEventListener('click', event => {
                const toggle = event.target.closest('[data-query-toggle]');
                if (toggle) {
                    this.toggle(toggle.dataset.queryToggle);
                    return;
                }
                const apply = event.target.closest('[data-query-apply]');
                if (apply) window.setTimeout(() => this.collapseAfterApply(apply.dataset.queryApply), 0);
            });
            document.addEventListener('input', event => {
                if (event.target.matches('[data-query-count]')) this.updateForField(event.target);
            });
            document.addEventListener('change', event => {
                if (event.target.matches('[data-query-count]')) this.updateForField(event.target);
            });
            document.addEventListener('keydown', event => {
                if (event.key !== 'Escape') return;
                const panel = event.target.closest('.query-panel.is-expanded');
                if (panel) this.setExpanded(panel.id, false);
            });
            document.querySelectorAll('.query-panel').forEach(panel => this.update(panel.id));
        }

        panel(panelId) {
            return document.getElementById(panelId);
        }

        setExpanded(panelId, expanded) {
            const panel = this.panel(panelId);
            const toggle = document.querySelector(`[data-query-toggle="${panelId}"]`);
            if (!panel || !toggle) return;
            panel.classList.toggle('is-expanded', expanded);
            panel.setAttribute('aria-hidden', String(!expanded));
            toggle.classList.toggle('is-active', expanded);
            toggle.setAttribute('aria-expanded', String(expanded));
            if (expanded) {
                window.setTimeout(() => {
                    panel.querySelector('input:not([type="hidden"]), select, button')?.focus({ preventScroll: true });
                }, 170);
            } else if (panel.contains(document.activeElement)) {
                toggle.focus({ preventScroll: true });
            }
        }

        toggle(panelId) {
            const panel = this.panel(panelId);
            if (!panel) return;
            this.setExpanded(panelId, !panel.classList.contains('is-expanded'));
        }

        fieldHasValue(field) {
            if (field.disabled) return false;
            if (field.type === 'checkbox' || field.type === 'radio') return field.checked;
            return String(field.value || '').trim() !== '';
        }

        updateForField(field) {
            const panel = field.closest('.query-panel');
            if (panel) this.update(panel.id);
        }

        update(panelId) {
            const panel = this.panel(panelId);
            if (!panel) return 0;
            const count = Array.from(panel.querySelectorAll('[data-query-count]'))
                .filter(field => this.fieldHasValue(field)).length;
            document.querySelectorAll(`[data-query-badge-for="${panelId}"]`).forEach(badge => {
                badge.textContent = String(count);
                badge.hidden = count === 0;
            });
            document.querySelectorAll(`[data-query-summary-for="${panelId}"]`).forEach(summary => {
                summary.textContent = count ? `已启用 ${count} 项条件` : '需要时展开，不占用列表空间';
            });
            return count;
        }

        collapseAfterApply(panelId) {
            this.update(panelId);
            if (window.matchMedia('(max-width: 768px)').matches) this.setExpanded(panelId, false);
        }
    }

    window.queryPanels = new QueryPanelController();
})();
