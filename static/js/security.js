(function () {
    'use strict';

    const htmlEntities = Object.freeze({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    });

    function escapeHTML(value) {
        return String(value ?? '').replace(/[&<>"']/g, character => htmlEntities[character]);
    }

    function safeURL(value, fallback = '') {
        const candidate = String(value ?? '').trim();
        if (!candidate) return fallback;
        try {
            const url = new URL(candidate, window.location.origin);
            return ['http:', 'https:', 'blob:'].includes(url.protocol)
                ? escapeHTML(url.href)
                : fallback;
        } catch (error) {
            return fallback;
        }
    }

    window.PicManagerSecurity = Object.freeze({ escapeHTML, safeURL });
})();
