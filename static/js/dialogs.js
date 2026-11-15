(function () {
    'use strict';
    if (window.PicManagerDialogs) return;
    let active = false;
    // Ignore repeated actions while a decision is pending; never replay destructive clicks.
    function open(message, options = {}) {
        if (active) return Promise.resolve(false);
        active = true;
        return new Promise(resolve => {
            const previousFocus = document.activeElement;
            const dialog = document.createElement('dialog');
            dialog.className = 'pm-confirm-dialog';
            dialog.setAttribute('aria-labelledby', 'pm-confirm-title');
            dialog.setAttribute('aria-describedby', 'pm-confirm-message');
            dialog.innerHTML = '<div class="pm-confirm-card"><span class="pm-confirm-eyebrow">PICMANAGER</span><h2 id="pm-confirm-title"></h2><p id="pm-confirm-message"></p><div class="pm-confirm-actions"><button type="button" data-cancel>取消</button><button type="button" data-accept>确认</button></div></div>';
            dialog.querySelector('h2').textContent = options.title || '确认操作';
            dialog.querySelector('p').textContent = String(message);
            const cancel = dialog.querySelector('[data-cancel]');
            const accept = dialog.querySelector('[data-accept]');
            accept.textContent = options.confirmText || '确认';
            cancel.textContent = options.cancelText || '取消';
            const inertNodes = [];
            let settled = false;
            const finish = value => {
                if (settled) return;
                settled = true;
                document.removeEventListener('keydown', onKey, true);
                if (dialog.open && typeof dialog.close === 'function') dialog.close();
                dialog.remove();
                inertNodes.forEach(node => node.removeAttribute('inert'));
                active = false;
                if (previousFocus?.isConnected) previousFocus.focus({ preventScroll: true });
                resolve(value);
            };
            const onKey = event => {
                // Prevent shortcuts in the underlying reader/editor from firing.
                event.stopImmediatePropagation();
                if (event.key === 'Escape') { event.preventDefault(); finish(false); }
                if (event.key === 'Tab') {
                    event.preventDefault();
                    (document.activeElement === cancel ? accept : cancel).focus();
                }
            };
            cancel.onclick = () => finish(false);
            accept.onclick = () => finish(true);
            dialog.addEventListener('cancel', event => { event.preventDefault(); finish(false); });
            dialog.addEventListener('close', () => finish(false));
            document.body.append(dialog);
            // HTML dialog supplies the top layer, not a browser confirmation popup.
            if (typeof dialog.showModal === 'function') dialog.showModal();
            else {
                dialog.setAttribute('open', '');
                dialog.classList.add('pm-confirm-fallback');
                dialog.setAttribute('role', 'dialog');
                dialog.setAttribute('aria-modal', 'true');
                for (const node of document.body.children) {
                    if (node !== dialog && !node.hasAttribute('inert')) { node.setAttribute('inert', ''); inertNodes.push(node); }
                }
            }
            document.addEventListener('keydown', onKey, true);
            cancel.focus({ preventScroll: true });
        });
    }
    const style = document.createElement('style');
    style.textContent = `
.pm-confirm-dialog{box-sizing:border-box;position:fixed;inset:0;margin:auto;padding:0;width:min(440px,calc(100vw - 32px));max-height:calc(100dvh - 32px);overflow:auto;border:1px solid var(--border,#dce1e9);border-radius:18px;background:var(--surface-raised,#fff);color:var(--text-primary,#303540);box-shadow:0 24px 80px #11182740;font-family:inherit;}
.pm-confirm-dialog::backdrop{background:rgba(15,23,42,.48);}
.pm-confirm-card{padding:28px;}.pm-confirm-eyebrow{font-size:11px;letter-spacing:.16em;color:var(--primary-color,#426ea8);font-weight:700;}
.pm-confirm-dialog h2{font-size:21px;margin:12px 0;}.pm-confirm-dialog p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:14px;color:var(--text-secondary,#626d7e);margin:0 0 26px;}
.pm-confirm-actions{display:flex;justify-content:flex-end;gap:10px;}.pm-confirm-actions button{font:inherit;font-size:14px;padding:10px 22px;border-radius:9px;border:1px solid var(--border,#dce1e9);background:var(--surface-secondary,#e9ecf1);color:var(--text-primary,#303540);cursor:pointer;}
.pm-confirm-actions [data-accept]{background:var(--primary-color,#426ea8);color:var(--surface-raised,#fff);border-color:transparent;}.pm-confirm-actions button:focus-visible{outline:3px solid var(--primary-color,#426ea8);outline-offset:3px;}
.pm-confirm-fallback[open]{display:block;z-index:2147483647;box-shadow:0 0 0 100vmax #0f172a7a;}
@media(max-width:480px){.pm-confirm-card{padding:22px;}.pm-confirm-actions button{flex:1;}}
`;
    document.head.append(style);
    window.PicManagerDialogs = { confirm: open };
})();
