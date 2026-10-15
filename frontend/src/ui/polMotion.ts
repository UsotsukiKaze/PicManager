import { reducedMotion } from '../state/appearance';
import '../styles/pol-motion.css';

type Group = 'title' | 'surface' | 'feedback' | 'bridge' | 'mode' | 'tools';
type Track = { animation: Animation; dispose: () => void };
const ease = 'cubic-bezier(.2,.8,.2,1)';
const clock = () => Number(document.timeline.currentTime ?? performance.now());
const smooth = (value: number) => { const t = Math.max(0, Math.min(1, value)); return t * t * (3 - 2 * t); };

export function createPolMotion() {
  const tracks: Record<Group, Set<Track>> = { title: new Set(), surface: new Set(), feedback: new Set(), bridge: new Set(), mode: new Set(), tools: new Set() };
  let entry: { source: string; title: boolean; surface: boolean; toolsEpoch?: number } | undefined;
  let activeRoot: HTMLElement | undefined;
  let modeHandoff: { position: number; cruising: boolean } | undefined;
  let departure: Animation | undefined;
  function play(element: Element, frames: Keyframe[], options: KeyframeAnimationOptions, group: Group, name: string, cleanup?: () => void) {
    const animation = element.animate(frames, { easing: ease, fill: 'both', ...options });
    animation.id = `pol-${name}`;
    let disposed = false;
    const track: Track = { animation, dispose() {
      if (disposed) return;
      disposed = true; tracks[group].delete(track); cleanup?.(); animation.cancel();
    } };
    tracks[group].add(track);
    void animation.finished.then(track.dispose, track.dispose);
    return animation;
  }
  function clear(group: Group) { [...tracks[group]].forEach(track => track.dispose()); }
  function cancel() {
    departure?.cancel(); departure = undefined;
    clear('title'); clear('surface'); clear('feedback'); clear('bridge'); clear('mode'); clear('tools');
    entry = undefined; activeRoot = undefined; modeHandoff = undefined;
  }
  function prepare(source: string) {
    cancel(); entry = { source, title: false, surface: false };
  }
  async function depart() {
    const workspace = document.getElementById('workspace-scroll');
    if (!workspace || reducedMotion()) return;
    const opacity = getComputedStyle(workspace).opacity;
    departure = workspace.animate([{ opacity }, { opacity: .08 }], { duration: 150, easing: 'cubic-bezier(.4,0,.6,1)', fill: 'forwards' });
    departure.id = 'pol-page-out';
    try { await departure.finished; } catch { /* A newer navigation restores the workspace. */ }
  }
  function reveal() {
    const workspace = document.getElementById('workspace-scroll');
    if (!workspace) return;
    const opacity = departure ? getComputedStyle(workspace).opacity : '.12';
    departure?.cancel(); departure = undefined;
    if (!reducedMotion()) play(workspace, [{ opacity }, { opacity: 1 }], { duration: 300 }, 'bridge', 'page-in');
  }
  function enter(root: HTMLElement) {
    if (!entry) entry = { source: '/', title: false, surface: false };
    if (entry.title) return;
    entry.title = true; activeRoot = root;
    reveal();
    root.dataset.polSource = entry.source; root.dataset.polEntry = 'full';
    const icon = root.querySelector<HTMLElement>('.px-brand'), title = root.querySelector<HTMLElement>('.px-title-window h2');
    if (!icon || !title || reducedMotion()) { root.dataset.polTitle = 'idle'; return; }
    root.dataset.polTitle = 'pushing';
    const duration = innerWidth <= 640 ? 820 : 940, epoch = clock();
    const step = innerWidth <= 640 ? .75 : 1;
    const width = title.getBoundingClientRect().width;
    const smooth = (value: number) => { const t = Math.max(0, Math.min(1, value)); return t * t * (3 - 2 * t); };
    const poses: Keyframe[] = [], letters: Keyframe[] = [];
    for (let frame = 0; frame <= 120; frame++) {
      const t = frame / 120, push = smooth(t / .70), release = smooth((t - .76) / .24);
      const phase = Math.min(1, t / .70) * Math.PI * 4;
      const sway = t < .70 ? Math.sin(phase) * (4.5 - push * 1.5) : -Math.sin(Math.PI * release) * 1.2;
      const x = (-32 + 42 * push) * (1 - release), y = t < .70 ? -Math.abs(Math.sin(phase)) * 1.8 : 0;
      const titleX = t <= .70 ? (-width * .62 - 8) * (1 - push) + 3 * push
        : t <= .84 ? 3 - 3.8 * smooth((t - .70) / .14) : -.8 * (1 - smooth((t - .84) / .16));
      const opacity = smooth(t / .12);
      poses.push({ offset: t, transform: `translate(${x}px,${y * step}px) rotate(${sway * step}deg)`, transformOrigin: `${t < .70 ? Math.sin(phase) >= 0 ? 85 : 15 : 50}% 100%`, opacity });
      letters.push({ offset: t, transform: `translateX(${titleX}px)`, opacity });
    }
    const tiptoe = play(icon, poses, { duration, easing: 'linear' }, 'title', 'tiptoe');
    const animation = play(title, letters, { duration, easing: 'linear' }, 'title', 'push-title', () => { root.dataset.polTitle = 'idle'; });
    tiptoe.startTime = animation.startTime = epoch;
    const filter = getComputedStyle(icon).filter;
    const glint = play(icon, [{ filter }, { filter: `${filter === 'none' ? '' : filter} brightness(1.12)`, offset: .45 }, { filter }], { duration: 240, delay: duration * .72 }, 'title', 'brand-glint');
    glint.startTime = epoch;
    root.querySelectorAll('.px-navigation,.px-header>.px-cart-button').forEach(element => {
      const track = play(element, [{ opacity: 0 }, { opacity: 1 }], { duration: 320, delay: 70 }, 'title', 'header-reveal');
      track.startTime = epoch;
    });
    root.dataset.polEpoch = String(epoch);
  }
  function mode(root: HTMLElement, previous: string, current: string, full: boolean, epoch: number) {
    const rail = root.querySelector<HTMLElement>('.px-mode-switch'), indicator = rail?.querySelector<HTMLElement>('.px-mode-indicator');
    if (!rail || !indicator || !rail.getBoundingClientRect().width) return;
    const index = Math.max(0, ['personal', 'stock', 'discovery'].indexOf(current));
    if (!full && (!previous || previous === current) && !modeHandoff) return;
    const from = full ? index : modeHandoff?.position ?? Math.max(0, ['personal', 'stock', 'discovery'].indexOf(previous));
    const destination = full ? index + 3 : index + (modeHandoff?.cruising && index < from - .01 ? 3 : 0);
    animateRail(rail, indicator, from, destination, full ? 880 : 320, full, epoch);
  }
  function captureMode(root: HTMLElement) {
    const rail = root.querySelector<HTMLElement>('.px-mode-switch'), indicator = rail?.querySelector<HTMLElement>('.px-mode-indicator');
    if (!rail || !indicator || !indicator.offsetWidth) { modeHandoff = undefined; return; }
    const style = getComputedStyle(indicator), transform = style.transform;
    const x = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m41;
    modeHandoff = { position: ((x / parseFloat(style.width)) % 3 + 3) % 3, cruising: rail.classList.contains('pol-mode-running') };
  }
  function animateRail(rail: HTMLElement, indicator: HTMLElement, from: number, to: number, duration: number, full: boolean, epoch: number) {
    const width = indicator.getBoundingClientRect().width;
    const track = document.createElement('span'); track.className = 'pol-mode-track'; track.setAttribute('aria-hidden', 'true');
    Object.assign(track.style, { left: `${indicator.offsetLeft}px`, top: `${indicator.offsetTop}px`, width: `${width * 3}px`, height: `${indicator.offsetHeight}px` });
    const echo = indicator.cloneNode() as HTMLElement; echo.classList.add('pol-mode-echo');
    rail.append(track); track.append(indicator, echo);
    rail.classList.add('pol-mode-moving'); rail.classList.toggle('pol-mode-running', full);
    const buttons = [...rail.querySelectorAll<HTMLElement>('button')];
    const main: Keyframe[] = [], wrap: Keyframe[] = [], labels: Keyframe[][] = buttons.map(() => []);
    const times = [...new Set([...Array.from({ length: 121 }, (_, i) => i / 120), .78, .88, .95])].sort((a, b) => a - b);
    const direction = Math.sign(to - from);
    for (const t of times) {
      const travel = smooth(t / .78);
      const seat = t <= .78 ? 2 * travel : t <= .88 ? 2 - 2.6 * smooth((t - .78) / .10)
        : t <= .95 ? -.6 + .8 * smooth((t - .88) / .07) : .2 * (1 - smooth((t - .95) / .05));
      const position = from + (to - from) * travel;
      const x = position * width + direction * seat;
      const stretch = 1 + (t <= .78 ? .035 * Math.sin(Math.PI * travel) : .02 * Math.sin(Math.PI * (t - .78) / .22));
      main.push({ offset: t, transform: `translateX(${x}px) scaleX(${stretch})` });
      wrap.push({ offset: t, transform: `translateX(${x - width * 3}px) scaleX(${stretch})` });
      const center = ((position + .5) % 3 + 3) % 3;
      buttons.forEach((_button, i) => {
        const distance = Math.abs(i + .5 - center), proximity = Math.min(distance, 3 - distance);
        const lit = smooth(1 - proximity / .8);
        labels[i]!.push({ offset: t, opacity: .65 + lit * .35, color: `color-mix(in srgb,var(--primary-color) ${lit * 100}%,var(--text-secondary))` });
      });
    }
    const cleanup = () => { rail.prepend(indicator); track.remove(); rail.classList.remove('pol-mode-moving', 'pol-mode-running'); };
    const a = play(indicator, main, { duration, easing: 'linear' }, 'mode', full ? 'mode-marquee' : 'mode-select', cleanup);
    const b = play(echo, wrap, { duration, easing: 'linear' }, 'mode', 'mode-wrap');
    a.startTime = b.startTime = epoch;
    buttons.forEach((button, i) => {
      const animation = play(button, labels[i]!, { duration, easing: 'linear' }, 'mode', 'mode-label');
      animation.startTime = epoch;
    });
    if (full) {
      const opening = play(rail, [{ transform: 'scaleX(.94)', opacity: .4 }, { transform: 'scaleX(1)', opacity: 1 }], { duration: 240 }, 'mode', 'mode-open');
      opening.startTime = epoch;
    }
  }
  function selectMode(root: HTMLElement, current: string) {
    if (root !== activeRoot || reducedMotion() || !tracks.mode.size) return;
    captureMode(root); clear('mode');
    mode(root, current, current, false, clock()); modeHandoff = undefined;
  }
  function tools(root: HTMLElement, epoch: number) {
    const group = root.querySelector<HTMLElement>('.px-floating-actions'), cart = root.querySelector<HTMLElement>('.px-floating-cart');
    if (!group || !cart) return;
    const buttons = [...group.querySelectorAll<HTMLElement>('button')], boxes = buttons.map(button => button.getBoundingClientRect());
    const anchorIndex = buttons.findIndex(button => button.dataset.action === 'refresh'), anchor = boxes[anchorIndex];
    if (!anchor) return;
    const box = group.getBoundingClientRect(), duration = 800, radius = parseFloat(getComputedStyle(group).borderRadius) || 12;
    group.classList.add('pol-tools-unfolding'); root.dataset.polTools = 'unfolding';
    const shell = document.createElement('span'); shell.className = 'pol-tools-shell'; group.prepend(shell);
    Object.assign(shell.style, { top: `${anchor.top - box.top - group.clientTop + anchor.height / 2}px`, bottom: 'auto', transform: 'translateY(-50%)' });
    const frames: Keyframe[] = [], shellFrames: Keyframe[] = [], cartFrames: Keyframe[] = [], buttonFrames: Keyframe[][] = buttons.map(() => []);
    const stops = [[.70, 0], [.78, -2], [.86, 1.2], [.93, -.4], [1, 0]];
    const times = [...new Set([...Array.from({ length: 121 }, (_, i) => i / 120), .70, .76, .78, .86, .93])].sort((a, b) => a - b);
    for (const t of times) {
      let angle = 0;
      for (let i = 1; i < stops.length; i++) {
        const [start, a] = stops[i - 1]!, [end, b] = stops[i]!;
        if (t >= start! && t <= end!) { angle = a! + (b! - a!) * smooth((t - start!) / (end! - start!)); break; }
      }
      frames.push({ offset: t, opacity: smooth(t / .12), transform: `translateY(${12 * (1 - smooth(t / .16))}px) rotate(${angle}deg)` });
      const unfold = smooth((t - .20) / .50), initialHeight = anchor.height + 8;
      shellFrames.push({ offset: t, width: `${box.width}px`, height: `${initialHeight + (box.height - initialHeight) * unfold}px`, borderRadius: `${box.width / 2 + (radius - box.width / 2) * unfold}px` });
      buttons.forEach((_button, i) => {
        const p = i === anchorIndex ? 1 : smooth((t - .22 - (i > anchorIndex ? .0375 : 0)) / .44);
        const y = (anchor.top - boxes[i]!.top) * (1 - p);
        buttonFrames[i]!.push({ offset: t, transform: `translateY(${y}px)`, opacity: i === anchorIndex ? 1 : smooth(p / .4), borderColor: unfold < .8 ? 'transparent' : 'var(--border)' });
      });
      const pop = smooth((t - .50) / .26), settle = smooth((t - .76) / .24);
      cartFrames.push({ offset: t, opacity: smooth((t - .50) / .12), transform: `translateY(${8 * (1 - pop) - pop + settle}px) scale(${.72 + .34 * pop - .06 * settle})` });
    }
    const animation = play(group, frames, { duration, easing: 'linear' }, 'tools', 'tools-unfold', () => { shell.remove(); group.classList.remove('pol-tools-unfolding'); root.dataset.polTools = 'idle'; });
    const shellMotion = play(shell, shellFrames, { duration, easing: 'linear' }, 'tools', 'tools-shell');
    const dot = play(cart, cartFrames, { duration, easing: 'linear' }, 'tools', 'cart-dot');
    animation.startTime = shellMotion.startTime = dot.startTime = epoch;
    buttons.forEach((button, i) => { play(button, buttonFrames[i]!, { duration, easing: 'linear' }, 'tools', 'tool-button').startTime = epoch; });
  }
  function surface(root: HTMLElement, previous = '', current = 'personal', view = 'recommendations') {
    if (root !== activeRoot) return;
    clear('surface'); clear('mode'); clear('tools');
    const fresh = !!entry && !entry.surface;
    const full = fresh;
    if (entry && root.querySelector('.px-mode-switch, .px-floating-actions')) entry.surface = true;
    const content = root.querySelector<HTMLElement>('#pixiv-content');
    const gallery = root.querySelector('.px-gallery'); gallery?.classList.add('pol-motion-gallery');
    if (gallery && !gallery.children.length) {
      const columns = Math.max(1, getComputedStyle(gallery).gridTemplateColumns.split(' ').length);
      for (let i = 0; i < Math.min(columns * 2, 10); i++) {
        const card = document.createElement('div'); card.className = 'pol-loading-card'; card.setAttribute('aria-hidden', 'true'); gallery.append(card);
      }
      gallery.setAttribute('aria-busy', 'true');
    }
    if (reducedMotion()) { root.dataset.polTools = 'idle'; return; }
    // Start with the first visible frame, rather than consuming time while data loads.
    const epoch = clock();
    if (content) play(content, [{ opacity: .3 }, { opacity: 1 }], { duration: 260 }, 'surface', 'content');
    const panel = root.querySelector('.px-gallery-flow,.px-cart-list');
    if (panel) play(panel, [{ transform: `translate${view === 'cart' ? 'X' : 'Y'}(${view === 'cart' ? 14 : 6}px)` }, { transform: 'none' }], { duration: 260 }, 'surface', 'panel');
    if (fresh) {
      const profile = root.querySelector('.px-account-profile');
      if (profile) {
        const track = play(profile, [{ opacity: .2, transform: 'translateY(4px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 340, delay: 80 }, 'surface', 'account');
        track.startTime = epoch;
      }
    }
    mode(root, previous, current, full, epoch);
    if (full && root.querySelector('.px-floating-actions')) {
      if (entry) entry.toolsEpoch = epoch;
      tools(root, epoch);
    } else if (entry?.toolsEpoch !== undefined && epoch - entry.toolsEpoch < 800 && root.querySelector('.px-floating-actions')) {
      // A mode click rebuilds the controls. Resume their original entrance clock.
      tools(root, entry.toolsEpoch);
    }
    else if (fresh && root.querySelector('.px-floating-tools')) play(root.querySelector('.px-floating-tools')!, [{ opacity: 0 }, { opacity: 1 }], { duration: 180 }, 'surface', 'tools-return');
    modeHandoff = undefined;
  }
  function cards(root: HTMLElement) {
    ready(root);
    if (reducedMotion()) return;
    const gallery = root.querySelector<HTMLElement>('.px-gallery');
    if (!gallery) return;
    const columns = Math.max(1, getComputedStyle(gallery).gridTemplateColumns.split(' ').length);
    const viewport = root.closest('.main-content')?.getBoundingClientRect();
    [...gallery.querySelectorAll<HTMLElement>('.px-card:not([data-pol-seen])')].forEach((card, i) => {
      card.dataset.polSeen = 'true';
      const box = card.getBoundingClientRect();
      if (box.top >= (viewport?.bottom || innerHeight) || box.bottom < (viewport?.top || 0)) return;
      play(card, [{ opacity: 0, transform: 'translateY(10px)' }, { opacity: 1, transform: 'translateY(0)' }], { duration: 350, delay: Math.min(i % columns * 25, 100) }, 'surface', 'card');
    });
    gallery.querySelectorAll<HTMLImageElement>('img').forEach(image => { if (image.complete && image.naturalWidth) imageReady(image); });
  }
  function ready(root: HTMLElement) {
    root.querySelectorAll('.pol-loading-card').forEach(card => card.remove());
    root.querySelector('.px-gallery')?.removeAttribute('aria-busy');
  }
  function imageReady(image: HTMLImageElement) {
    if (image.dataset.polDecoded || !activeRoot?.contains(image) || !image.naturalWidth) return;
    image.dataset.polDecoded = 'true';
    const box = image.getBoundingClientRect();
    if (reducedMotion() || box.bottom < 64 || box.top > innerHeight) return;
    play(image, [{ opacity: .25 }, { opacity: 1 }], { duration: 280 }, 'surface', 'image');
  }
  function leaveContent(root: HTMLElement) {
    if (reducedMotion() || root !== activeRoot) return;
    captureMode(root);
    const gallery = root.querySelector<HTMLElement>('.px-gallery');
    if (!gallery?.children.length) return;
    const box = gallery.getBoundingClientRect();
    if (box.bottom < 0 || box.top > innerHeight) return;
    const overlay = document.createElement('div'); overlay.className = 'pol-gallery-exit'; overlay.setAttribute('aria-hidden', 'true'); overlay.inert = true;
    Object.assign(overlay.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, maxHeight: `${Math.min(innerHeight - Math.max(box.top, 0), 700)}px` });
    // Keep the departing visual outside document selectors and focusable controls.
    const shadow = overlay.attachShadow({ mode: 'closed' }), style = document.createElement('style'), computed = getComputedStyle(gallery);
    const cardHeight = gallery.querySelector('.px-card')?.getBoundingClientRect().height || 300;
    style.textContent = `*{box-sizing:border-box} .px-gallery{display:grid;grid-template-columns:${computed.gridTemplateColumns};gap:${computed.gap}} .px-card{position:relative;height:${cardHeight}px;border-radius:var(--radius);overflow:hidden} .px-image-button{display:block;width:100%;height:100%;border:0;padding:0} img{width:100%;height:100%;object-fit:cover} .px-card-body{position:absolute;inset:auto 0 0;padding:14px 13px;background:linear-gradient(transparent,#162035cc);color:#f3f5fa} h4{margin:0;font-size:13px} p{margin:6px 0 0;font-size:12px} .px-card-actions,.px-page-count,.px-library-status,.px-similarity-status{display:none}`;
    const clone = gallery.cloneNode(true) as HTMLElement;
    clone.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
    shadow.append(style, clone); document.body.append(overlay);
    play(overlay, [{ opacity: .9, transform: 'translateY(0)' }, { opacity: 0, transform: 'translateY(-8px)' }], { duration: 180 }, 'feedback', 'batch-exit', () => overlay.remove());
  }
  function added(root: HTMLElement, origin?: DOMRect) {
    if (root !== activeRoot || reducedMotion()) return;
    const target = root.querySelector<HTMLElement>('.px-floating-cart'), button = target || root.querySelector<HTMLElement>('.px-cart-button');
    if (!button) return;
    const destination = button.getBoundingClientRect();
    if (origin && destination.width && destination.top >= 0 && destination.bottom <= innerHeight) {
      const dot = document.createElement('span'); dot.className = 'pol-cart-flight'; dot.setAttribute('aria-hidden', 'true');
      dot.setAttribute('popover', 'manual');
      const glyph = button.querySelector('svg'); if (glyph) dot.append(glyph.cloneNode(true));
      const x = origin.left + origin.width / 2 - 12, y = origin.top + origin.height / 2 - 12;
      Object.assign(dot.style, { left: `${x}px`, top: `${y}px` }); document.body.append(dot);
      dot.showPopover?.();
      const dx = destination.left + destination.width / 2 - 12 - x, dy = destination.top + destination.height / 2 - 12 - y;
      play(dot, [{ transform: 'translate(0,0) scale(1)', opacity: 1 }, { transform: `translate(${dx * .55}px,${dy * .45 - 50}px) scale(.85)`, opacity: 1, offset: .5 }, { transform: `translate(${dx}px,${dy}px) scale(.3)`, opacity: 0 }], { duration: 420 }, 'feedback', 'cart-flight', () => dot.remove());
    }
    play(button, [{ transform: 'scale(1)' }, { transform: 'scale(.92)', offset: .40 }, { transform: 'scale(1.05)', offset: .65 }, { transform: 'scale(1)' }], { duration: 340, delay: origin ? 230 : 0 }, 'feedback', 'cart-confirm');
  }
  function count(badge: HTMLElement, value: number, previous: number) {
    if (value === previous || reducedMotion() || !badge.isConnected) return;
    const digit = document.createElement('span'); digit.textContent = String(value);
    badge.classList.add('pol-count-window'); badge.replaceChildren(digit);
    const direction = value >= previous ? 1 : -1;
    play(digit, [{ transform: `translateY(${direction * 7}px)`, opacity: .25 }, { transform: `translateY(${-direction}px)`, opacity: 1, offset: .72 }, { transform: 'translateY(0)', opacity: 1 }], { duration: 300 }, 'feedback', 'count');
  }
  function liked(button: HTMLElement, liked: boolean) {
    if (!liked || reducedMotion() || !button.isConnected) return;
    const ring = document.createElement('span'); ring.className = 'pol-like-ring'; ring.setAttribute('aria-hidden', 'true'); button.append(ring);
    play(ring, [{ transform: 'scale(.5)', opacity: .65 }, { transform: 'scale(1.5)', opacity: 0 }], { duration: 360 }, 'feedback', 'like-ring', () => ring.remove());
  }
  function closeReader(dialog: HTMLDialogElement, source: Element | null | undefined, finish: () => void) {
    if (dialog.dataset.polClosing) return;
    dialog.dataset.polClosing = 'true';
    if (reducedMotion()) { finish(); return; }
    dialog.classList.add('pol-reader-closing');
    const cover = dialog.querySelector<HTMLElement>('.px-detail-cover')!, details = dialog.querySelector<HTMLElement>('.px-detail-body')!;
    const currentTransform = getComputedStyle(cover).transform, currentOpacity = getComputedStyle(cover).opacity;
    cover.getAnimations().forEach(animation => animation.cancel()); details.getAnimations().forEach(animation => animation.cancel());
    const from = cover.getBoundingClientRect(), image = source?.closest('.px-card')?.querySelector('.px-image-button') || source;
    const to = image?.isConnected ? image.getBoundingClientRect() : undefined;
    const visible = to && to.width && to.height && to.top < innerHeight && to.bottom > 64;
    const transform = visible ? `translate(${to.left - from.left}px,${to.top - from.top}px) scale(${to.width / from.width},${to.height / from.height})` : 'translateY(6px) scale(.98)';
    play(details, [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(8px)' }], { duration: 180 }, 'feedback', 'reader-details');
    play(cover, [{ transform: currentTransform, opacity: currentOpacity }, { transform, opacity: visible ? .35 : 0 }], { duration: visible ? 280 : 180 }, 'feedback', 'reader-close', finish);
  }
  function top(button?: HTMLElement) {
    const icon = button?.querySelector('svg');
    if (icon && !reducedMotion()) play(icon, [{ transform: 'translateY(0)' }, { transform: 'translateY(-3px)', offset: .4 }, { transform: 'translateY(0)' }], { duration: 260 }, 'feedback', 'top');
  }
  const api = { prepare, depart, cancel, enter, surface, selectMode, cards, ready, imageReady, leaveContent, added, count, liked, closeReader, top, dispose() { cancel(); if (window.PicManagerPolMotion === api) delete window.PicManagerPolMotion; } };
  window.PicManagerPolMotion = api;
  return api;
}
export type PolMotion = ReturnType<typeof createPolMotion>;
