import { reducedMotion } from '../state/appearance';
import '../styles/account-motion.css';

const ease = 'cubic-bezier(.2,.8,.2,1)';
const smooth = (value: number) => { const t = Math.max(0, Math.min(1, value)); return t * t * (3 - 2 * t); };
type AccountWindow = Window & { PicManagerAccountMotion?: AccountMotionApi };
export type AccountMotionApi = ReturnType<typeof createAccountMotion>;

/** One lifetime per settings activation or embedded profile document. */
export function createAccountMotion(root: HTMLElement, kind: 'settings' | 'profile', onReady?: () => void) {
  const doc = root.ownerDocument, win = doc.defaultView as AccountWindow;
  const animations = new Set<Animation>(), slots = new WeakMap<Element, Map<string, Animation>>();
  const observed = new WeakSet<Element>(), entered = new WeakSet<Element>(), values = new WeakMap<Element, string>();
  const folds = new WeakMap<HTMLElement, boolean>();
  const listeners = new AbortController();
  let disposed = false, ready = false, scheduled = 0;
  let selector: Animation[] = [], selectorCleanup: (() => void) | undefined;
  const quiet = () => reducedMotion() || doc.documentElement.dataset.motion === 'reduced';
  function play(element: Element, frames: Keyframe[], duration: number, name: string, delay = 0) {
    let map = slots.get(element); if (!map) { map = new Map(); slots.set(element, map); }
    map.get(name)?.cancel();
    if (disposed || quiet()) return;
    const animation = element.animate(frames, { duration, delay, easing: ease, fill: 'both' });
    animation.id = `account-${name}`; animations.add(animation); map.set(name, animation);
    void animation.finished.then(() => {
      if (map!.get(name) === animation) map!.delete(name);
      animations.delete(animation); animation.cancel();
    }, () => { animations.delete(animation); if (map!.get(name) === animation) map!.delete(name); });
    return animation;
  }
  function enter(element: Element, delay = 0) {
    if (entered.has(element)) return;
    entered.add(element);
    if (element.matches('.maintenance-progress')) play(element, [{ height: '0px', opacity: 0, overflow: 'hidden' }, { height: `${element.getBoundingClientRect().height}px`, opacity: 1, overflow: 'hidden' }], 300, 'progress-open');
    else play(element, [{ opacity: .12, transform: 'translateY(8px)' }, { opacity: 1, transform: 'none' }], 340, 'card-in', delay);
  }
  const visible = new IntersectionObserver(entries => {
    entries.forEach(item => { if (item.isIntersecting) { enter(item.target); visible.unobserve(item.target); } });
  }, { rootMargin: '30px' });
  function clearSelector() {
    selector.forEach(animation => animation.cancel()); selector = [];
    selectorCleanup?.(); selectorCleanup = undefined;
  }
  function moveSelector(target: HTMLElement, full: boolean, from?: { x: number; width: number; cruising: boolean }) {
    const rail = root.querySelector<HTMLElement>('.profile-tabs'), indicator = root.querySelector<HTMLElement>('#profile-tab-indicator');
    if (!rail || !indicator) return;
    const buttons = [...rail.querySelectorAll<HTMLElement>('.profile-tab:not(.hidden)')];
    clearSelector();
    if (quiet() || !buttons.length) return;
    const inset = parseFloat(getComputedStyle(indicator).left) || 0;
    const boxes = buttons.map(button => ({ x: button.offsetLeft - inset, width: button.offsetWidth }));
    const index = Math.max(0, buttons.indexOf(target)), length = rail.scrollWidth - inset * 2;
    const start = from?.x ?? boxes[index]!.x, startWidth = from?.width ?? boxes[index]!.width;
    const end = full && buttons.length > 1 ? start + length : boxes[index]!.x + (from?.cruising && boxes[index]!.x < start ? length : 0);
    const duration = full && buttons.length > 1 ? 760 : 300;
    const echo = indicator.cloneNode() as HTMLElement; echo.removeAttribute('id'); echo.classList.add('account-indicator-echo'); rail.append(echo);
    rail.dataset.cruising = full && buttons.length > 1 ? 'true' : 'false';
    rail.classList.add('account-tabs-moving');
    const main: Keyframe[] = [], wrap: Keyframe[] = [], labels: Keyframe[][] = buttons.map(() => []);
    for (let i = 0; i <= 120; i++) {
      const t = i / 120, travel = smooth(t / .82), x = start + (end - start) * travel;
      const wrapped = ((x % length) + length) % length;
      let width = startWidth + (boxes[index]!.width - startWidth) * travel;
      if (full && buttons.length > 1) {
        const at = boxes.reduce((last, box, index) => box.x <= wrapped ? index : last, -1);
        const current = Math.max(0, at), next = (current + 1) % boxes.length;
        const span = (next ? boxes[next]!.x : length) - boxes[current]!.x;
        width = boxes[current]!.width + (boxes[next]!.width - boxes[current]!.width) * smooth((wrapped - boxes[current]!.x) / span);
      }
      const stretch = 1 + (t > .82 ? .018 * Math.sin((t - .82) / .18 * Math.PI * 2) : .025 * Math.sin(travel * Math.PI));
      main.push({ offset: t, transform: `translateX(${x}px) scaleX(${stretch})`, width: `${width}px` });
      wrap.push({ offset: t, transform: `translateX(${x - length}px) scaleX(${stretch})`, width: `${width}px` });
      buttons.forEach((_button, j) => {
        const distance = Math.abs(boxes[j]!.x + boxes[j]!.width / 2 - ((wrapped + width / 2) % length));
        const lit = smooth(1 - Math.min(distance, length - distance) / Math.max(width, boxes[j]!.width));
        labels[j]!.push({ offset: t, opacity: .65 + .35 * lit, color: `color-mix(in srgb,var(--primary-color) ${lit * 100}%,var(--text-secondary))` });
      });
    }
    selectorCleanup = () => { echo.remove(); rail.classList.remove('account-tabs-moving'); delete rail.dataset.cruising; };
    const epoch = Number(doc.timeline.currentTime || 0);
    for (const [element, frames] of [[indicator, main], [echo, wrap], ...buttons.map((button, i) => [button, labels[i]!])] as Array<[HTMLElement, Keyframe[]]>) {
      const animation = play(element, frames, duration, element === indicator ? full ? 'tab-loop' : 'tab-select' : 'tab-follow');
      if (animation) { animation.effect!.updateTiming({ easing: 'linear' }); animation.startTime = epoch; selector.push(animation); }
    }
    const current = selector[0];
    if (current) void current.finished.then(() => { if (selector[0] === current) clearSelector(); }, () => {});
    if (full) play(rail, [{ opacity: .3, transform: 'scaleX(.96)' }, { opacity: 1, transform: 'none' }], 260, 'tabs-open');
  }
  function fold(element: HTMLElement, opening: boolean, edit = false, priorHeight?: number) {
    const previous = priorHeight ?? element.getBoundingClientRect().height;
    slots.get(element)?.get('fold')?.cancel();
    folds.set(element, opening);
    const details = element as HTMLDetailsElement;
    if (edit) { element.style.display = 'flex'; element.dataset.expanded = String(opening); }
    else details.open = true;
    const full = element.getBoundingClientRect().height;
    const summary = element.querySelector(':scope>summary');
    const style = getComputedStyle(element);
    if (summary) summary.setAttribute('aria-expanded', String(opening));
    const collapsed = edit ? 0 : (summary?.getBoundingClientRect().height || 0) + parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + parseFloat(style.borderTopWidth || '0') + parseFloat(style.borderBottomWidth || '0');
    const finish = () => { if (folds.get(element) === opening) { if (edit && !opening) element.style.display = 'none'; else if (!edit) details.open = opening; } };
    const margins = edit ? [{ marginTop: opening ? '0px' : style.marginTop }, { marginTop: opening ? style.marginTop : '0px' }] : [{}, {}];
    const animation = play(element, [{ height: `${previous}px`, overflow: 'hidden', ...margins[0] }, { height: `${opening ? full : collapsed}px`, overflow: 'hidden', ...margins[1] }], opening ? 300 : 210, 'fold');
    if (animation) void animation.finished.then(finish, () => {}); else finish();
    if (opening) [...element.children].filter(child => child.tagName !== 'SUMMARY').forEach(child => play(child, [{ opacity: 0, transform: 'translateY(-3px)' }, { opacity: 1, transform: 'none' }], 220, 'fold-content', 30));
  }
  function refresh() {
    scheduled = 0; if (disposed) return;
    if (!ready) {
      if (kind === 'profile' && doc.documentElement.dataset.profileReady !== 'true') return;
      ready = true; onReady?.();
      root.classList.add('account-motion-root');
      if (kind === 'profile') {
        const active = root.querySelector<HTMLElement>('.profile-tab.active'); if (active) moveSelector(active, true);
        play(root.querySelector('.user-avatar') || root, [{ transform: 'scale(.94)' }, { transform: 'scale(1.015)', offset: .75 }, { transform: 'scale(1)' }], 360, 'avatar');
        const info = root.querySelector('.user-basic-info'); if (info) play(info, [{ opacity: 0, transform: 'translateX(6px)' }, { opacity: 1, transform: 'none' }], 340, 'identity', 40);
        const badge = root.querySelector('.user-role-badge'); if (badge) play(badge, [{ opacity: 0, scale: '.9' }, { opacity: 1, scale: '1.03', offset: .8 }, { opacity: 1, scale: '1' }], 300, 'badge', 110);
      }
    }
    const cards = root.querySelectorAll<HTMLElement>(kind === 'settings' ? '.settings-group,.stats-grid>.stat-card,.px-account-panel,.px-content-panel,.px-group-panel,.validation-card,.maintenance-progress' : '.user-card,.guest-card,.contribution-card,.preference-card,.request-card,.admin-card,.add-admin-card');
    let row = 0, top = -Infinity;
    cards.forEach(card => {
      if (observed.has(card) || !card.getClientRects().length) return;
      observed.add(card);
      const box = card.getBoundingClientRect();
      const host = doc === document ? 0 : (doc.defaultView!.frameElement?.getBoundingClientRect().top || 0);
      if (box.top + host < innerHeight && box.bottom + host > 0) {
        if (Math.abs(box.top - top) > 12) { row++; top = box.top; }
        enter(card, Math.min(row * 35, 140));
      } else visible.observe(card);
    });
    root.querySelectorAll<HTMLElement>('.stat-value,.score-value,.pending-count,.px-task-count,[id$="-progress-count"],#user-nickname').forEach(element => {
      const value = element.textContent || '', old = values.get(element); values.set(element, value);
      if (old !== value && element.getClientRects().length && value !== '--' && !(element.id === 'user-nickname' && old === undefined)) {
        play(element, [{ opacity: .25, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], 280, 'value');
      }
    });
    root.querySelectorAll<HTMLElement>('.score-fill,.preference-fill,progress').forEach(element => {
      const value = element.style.width || element.getAttribute('value') || '', old = values.get(element); values.set(element, value);
      if (old !== value && element.getClientRects().length && !element.matches('progress')) {
        const from = old && parseFloat(value) > 0 ? Math.min(1, parseFloat(old) / parseFloat(value)) : .02;
        play(element, [{ transform: `scaleX(${Math.max(.02, from || .02)})`, transformOrigin: 'left' }, { transform: 'scaleX(1)', transformOrigin: 'left' }], 500, 'progress');
      }
    });
    root.querySelectorAll<HTMLElement>('.preference-item').forEach((element, index) => { if (!entered.has(element) && element.getClientRects().length) { entered.add(element); play(element, [{ opacity: 0 }, { opacity: 1 }], 220, 'preference', Math.min(index * 25, 120)); } });
  }
  const observer = new MutationObserver(() => { if (!scheduled) scheduled = requestAnimationFrame(refresh); });
  observer.observe(kind === 'profile' ? doc.documentElement : root, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['style', 'class', 'hidden', 'open', 'value', 'data-profile-ready'] });
  const settle = () => { if (quiet()) [...animations].forEach(animation => { try { animation.finish(); } catch { animation.cancel(); } }); };
  const appearanceObserver = new MutationObserver(settle);
  appearanceObserver.observe(doc.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
  matchMedia('(prefers-reduced-motion:reduce)').addEventListener('change', settle, { signal: listeners.signal });
  root.addEventListener('input', event => {
    if ((event.target as HTMLElement).id !== 'pixiv-group-search') return;
    const previous = [...root.querySelectorAll<HTMLDetailsElement>('[data-group] details')].map(element => ({ element, open: element.open, height: element.getBoundingClientRect().height }));
    queueMicrotask(() => { if (!disposed) previous.forEach(({ element, open, height }) => { if (open !== element.open && element.getClientRects().length) fold(element, element.open, false, height); }); });
  }, { capture: true, signal: listeners.signal });
  root.addEventListener('input', () => {
    root.querySelectorAll<HTMLElement>('[data-save-state]').forEach(button => {
      if (button.dataset.saveState === 'saving') { button.dataset.saveDirty = 'true'; return; }
      button.textContent = button.dataset.saveLabel || button.textContent;
      delete button.dataset.saveState;
      const feedback = button.parentElement?.querySelector('.account-save-feedback'); if (feedback) feedback.textContent = '';
    });
  }, { signal: listeners.signal });
  root.addEventListener('click', event => {
    const target = (event.target as Element).closest<HTMLElement>('summary,.profile-tab');
    if (!target || !root.contains(target)) return;
    if (target.tagName === 'SUMMARY') {
      if ((event.target as Element).closest('button,a,input,select')) return;
      event.preventDefault(); const details = target.parentElement as HTMLDetailsElement;
      fold(details, !(folds.get(details) ?? details.open)); return;
    }
    if (target.classList.contains('hidden')) return;
    const indicator = root.querySelector<HTMLElement>('#profile-tab-indicator'), rail = root.querySelector<HTMLElement>('.profile-tabs');
    if (!indicator || !rail) return;
    const style = getComputedStyle(indicator), width = parseFloat(style.width), length = rail.scrollWidth - 8;
    const x = new DOMMatrixReadOnly(style.transform === 'none' ? undefined : style.transform).m41;
    const from = { x: ((x % length) + length) % length, width, cruising: rail.dataset.cruising === 'true' };
    const tabs = [...rail.querySelectorAll('.profile-tab:not(.hidden)')], before = tabs.findIndex(tab => tab.classList.contains('active'));
    const direction = Math.sign(tabs.indexOf(target) - before) || 1;
    queueMicrotask(() => {
      if (disposed) return; moveSelector(target, false, from);
      const panel = root.querySelector('.tab-panel.active');
      if (panel && tabs.indexOf(target) !== before) play(panel, [{ opacity: .2, transform: `translateX(${direction * 8}px)` }, { opacity: 1, transform: 'none' }], 300, 'panel');
    });
  }, { capture: true, signal: listeners.signal });
  const api = {
    edit(open: boolean) { const form = root.querySelector<HTMLElement>('#edit-nickname-form'); if (form) fold(form, open, true); },
    saving(button: HTMLElement | null, state: 'saving' | 'saved' | 'error', message = '') {
      if (!button || disposed) return;
      const label = button.dataset.saveLabel || button.textContent || ''; button.dataset.saveLabel = label;
      let feedback = button.parentElement?.querySelector<HTMLElement>(':scope>.account-save-feedback');
      if (!feedback) { feedback = doc.createElement('p'); feedback.className = 'account-save-feedback'; feedback.setAttribute('role', 'status'); button.after(feedback); }
      button.dataset.saveState = state;
      if (state === 'saving') delete button.dataset.saveDirty;
      button.style.minWidth = `${Math.max(button.offsetWidth, parseFloat(button.style.minWidth) || 0)}px`;
      button.textContent = state === 'saving' ? '正在保存…' : state === 'saved' ? '✓ 已保存' : label;
      feedback.textContent = message || (state === 'saved' ? '已保存' : ''); feedback.dataset.state = state;
      if (state === 'saved' && button.dataset.saveDirty) { button.textContent = label; feedback.textContent = '本次提交已保存，仍有未保存的修改'; }
      if (state === 'saved') play(button, [{ boxShadow: '0 0 0 0 var(--primary-soft)' }, { boxShadow: '0 0 0 5px var(--primary-soft)', offset: .4 }, { boxShadow: '0 0 0 0 transparent' }], 420, 'saved');
    },
    async remove(element: HTMLElement | null) {
      if (!element) return;
      const style = getComputedStyle(element);
      const animation = play(element, [{ height: `${element.offsetHeight}px`, opacity: 1, marginBottom: style.marginBottom, paddingTop: style.paddingTop, paddingBottom: style.paddingBottom, overflow: 'hidden' }, { height: '0px', opacity: 0, marginBottom: '0px', paddingTop: '0px', paddingBottom: '0px', overflow: 'hidden' }], 240, 'remove');
      try { await animation?.finished; } catch { /* Navigation may dispose this document. */ }
      if (!disposed) element.remove();
    },
    dispose() {
      disposed = true; cancelAnimationFrame(scheduled); listeners.abort(); observer.disconnect(); appearanceObserver.disconnect(); visible.disconnect(); clearSelector();
      animations.forEach(animation => animation.cancel()); animations.clear();
      root.classList.remove('account-motion-root');
      if (win.PicManagerAccountMotion === api) delete win.PicManagerAccountMotion;
    },
  };
  win.PicManagerAccountMotion = api;
  refresh(); return api;
}
