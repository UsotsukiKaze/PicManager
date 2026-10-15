<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
import { reducedMotion } from '../state/appearance';
import { motionEasing } from '../ui/motion';
import type { SectionItem } from '../ui/sectionNavigation';
const props = defineProps<{ items: SectionItem[]; active: string; label: string; family: string; epoch?: number }>();
const emit = defineEmits<{ select: [item: SectionItem, duration: number] }>();
const root = ref<HTMLElement>(), trigger = ref<HTMLButtonElement>(), dialog = ref<HTMLDialogElement>(), hub = ref<HTMLElement>(), intro = ref<HTMLElement>(), indicator = ref<HTMLElement>(), indicatorEcho = ref<HTMLElement>(), introBackdrop = ref<HTMLElement>();
const mode = ref<'intro' | 'idle' | 'hover'>('intro');
const modalMode = ref<'opening' | 'open' | 'closing'>('opening');
const modalOpen = ref(false), returning = ref(false), selected = ref(''), pointed = ref(''), introActive = ref(props.active);
const center = ref({ x: 0, y: 0 }), radius = ref(142), peekShift = ref(0);
const current = computed(() => props.items.find(item => item.key === props.active) || props.items[0]!);
const hubItem = computed(() => props.items.find(item => item.key === selected.value) || current.value);
const others = computed(() => props.items.filter(item => item.key !== current.value.key));
const pointedItem = computed(() => props.items.find(item => item.key === pointed.value) || hubItem.value);
const id = computed(() => `section-wheel-${props.family}`);
let leaveTimer: ReturnType<typeof setTimeout> | undefined;
let flight: Animation | undefined, serial = 0, introSerial = 0, disposed = false;
let childrenMotion: Animation[] = [], introMotion: Animation[] = [];
function point(index: number, count: number, size: number, peek = false) {
  const angle = (peek ? count === 1 ? 35 : index * 65 / Math.max(1, count - 1) : count === 1 ? 90 : 160 - index * 140 / Math.max(1, count - 1)) * Math.PI / 180;
  return { '--x': `${Math.cos(angle) * size}px`, '--y': `${Math.sin(angle) * size}px`, '--i': index };
}
function anchorRect() {
  const bounds = root.value!.getBoundingClientRect();
  return new DOMRect(bounds.left, bounds.top, trigger.value!.offsetWidth, trigger.value!.offsetHeight);
}
function stopIntro() {
  introSerial++; introMotion.forEach(animation => animation.cancel()); introMotion = [];
}
async function sequence(target: string, from = props.items[0]!.key, startAt?: number) {
  stopIntro(); const token = introSerial;
  if (reducedMotion() || innerWidth <= 640) { mode.value = 'idle'; return; }
  mode.value = 'intro'; introActive.value = target;
  await nextTick();
  if (disposed || token !== introSerial || !intro.value || !indicator.value || !indicatorEcho.value || !introBackdrop.value) return;
  const buttons = Array.from(intro.value.querySelectorAll<HTMLButtonElement>('button'));
  const bounds = intro.value.getBoundingClientRect(), anchor = anchorRect();
  const startIndex = Math.max(0, props.items.findIndex(item => item.key === from));
  const targetIndex = Math.max(0, props.items.findIndex(item => item.key === target));
  const starting = buttons[startIndex]!, ending = buttons[targetIndex]!;
  const first = buttons[0]!, last = buttons[buttons.length - 1]!;
  const period = last.offsetLeft + last.offsetWidth + 3 - first.offsetLeft;
  const distance = period + ending.offsetLeft - starting.offsetLeft;
  const anchorCenter = anchor.left - bounds.left + anchor.width / 2;
  const clamp = (value: number) => Math.max(0, Math.min(1, value));
  const smooth = (value: number) => { const p = clamp(value); return p * p * (3 - 2 * p); };
  const mix = (a: number, b: number, p: number) => a + (b - a) * p;
  const buttonFrames: Keyframe[][] = buttons.map(() => []);
  const maskFrames: Keyframe[] = [], backdropFrames: Keyframe[] = [], markerFrames: Keyframe[] = [], echoFrames: Keyframe[] = [];
  const primary = getComputedStyle(trigger.value!).color;
  const secondary = getComputedStyle(root.value!).getPropertyValue('--text-secondary').trim();
  // A single continuous clock: the travelling selection starts during unfolding,
  // crosses the rail edge, then docks while the rail is already retracting.
  for (let frame = 0; frame <= 60; frame++) {
    const t = frame / 60;
    const opening = 1 - Math.pow(1 - clamp(t / .36), 3);
    const closing = smooth((t - .56) / .44);
    const reveal = opening * (1 - closing);
    const visibleWidth = mix(anchor.width, bounds.width, reveal);
    const travel = 1 - Math.pow(1 - clamp(t / .64), 2);
    const unwrapped = starting.offsetLeft - first.offsetLeft + distance * travel;
    const position = first.offsetLeft + unwrapped;
    const stretch = Math.sin(Math.PI * clamp(t / .64)) * 10;
    const markerWidth = mix(starting.offsetWidth, ending.offsetWidth, travel) + stretch;
    const markerCenter = position + markerWidth / 2;
    const markerX = mix(anchorCenter, markerCenter, reveal) - markerWidth / 2;
    const opacity = smooth(t / .11) * (1 - smooth((t - .74) / .26));
    const marker = { offset: t, transform: `translateX(${markerX}px)`, width: `${markerWidth}px`, opacity };
    // The second copy crosses the left edge while the first exits on the right.
    // Keeping both tracks unwrapped avoids interpolating a jump across the rail.
    markerFrames.push({ ...marker, opacity: unwrapped >= period ? 0 : opacity });
    echoFrames.push({ ...marker, transform: `translateX(${markerX - period * reveal}px)`, opacity: unwrapped + markerWidth > period ? opacity : 0 });
    maskFrames.push({ offset: t, clipPath: `inset(0 0 0 ${bounds.width - visibleWidth}px round 8px)` });
    backdropFrames.push({ offset: t, width: `${visibleWidth}px` });
    buttons.forEach((button, index) => {
      const buttonCenter = button.offsetLeft + button.offsetWidth / 2;
      const selected = index === targetIndex;
      buttonFrames[index]!.push({
        offset: t, transform: `translateX(${(anchorCenter - buttonCenter) * (1 - reveal)}px)`,
        opacity: selected ? 1 : smooth(reveal / .78),
        color: (t > .64 ? selected : Math.min(Math.abs(buttonCenter - markerCenter), Math.abs(buttonCenter - markerCenter + period)) < button.offsetWidth / 2) ? primary : secondary,
      });
    });
  }
  const tracks: Array<[HTMLElement, Keyframe[]]> = [[intro.value, maskFrames], [introBackdrop.value, backdropFrames], [indicator.value, markerFrames], [indicatorEcho.value, echoFrames], ...buttons.map((button, index): [HTMLElement, Keyframe[]] => [button, buttonFrames[index]!])];
  introMotion = tracks.map(([element, frames]) => element.animate(frames, { duration: 940, easing: 'linear', fill: 'forwards' }));
  const epoch = startAt ?? props.epoch ?? document.timeline.currentTime;
  if (typeof epoch === 'number') introMotion.forEach(animation => { animation.startTime = epoch; });
  try { await Promise.all(introMotion.map(animation => animation.finished)); } catch { return; }
  if (token !== introSerial) return;
  mode.value = 'idle'; stopIntro();
  // Keep a stationary pointer effective when the intro or return finishes beneath it.
  void nextTick(() => { if (!disposed && matchMedia('(hover:hover) and (pointer:fine)').matches && root.value?.matches(':hover')) peek(); });
}
function peek(event?: PointerEvent) {
  if (innerWidth <= 640 || event?.pointerType === 'touch' || modalOpen.value || returning.value || mode.value === 'intro') return;
  const rect = anchorRect();
  const room = innerWidth - rect.left - rect.width / 2 - 28;
  peekShift.value = -Math.max(0, 142 - room);
  clearTimeout(leaveTimer); mode.value = 'hover';
}
function leave() {
  clearTimeout(leaveTimer);
  leaveTimer = setTimeout(() => { if (!root.value?.contains(document.activeElement) && mode.value !== 'intro') mode.value = 'idle'; }, 180);
}
function locate() {
  const rect = document.getElementById('workspace-scroll')?.getBoundingClientRect();
  center.value = { x: rect ? rect.left + rect.width / 2 : innerWidth / 2, y: rect ? (Math.max(0, rect.top) + Math.min(innerHeight, rect.bottom)) / 2 : innerHeight / 2 };
  radius.value = Math.min(142, Math.max(94, (innerWidth - 92) / 2));
}
function clearFlight() {
  flight?.cancel(); flight = undefined; childrenMotion.forEach(animation => animation.cancel()); childrenMotion = [];
  for (const child of Array.from(hub.value?.children || [])) (child as HTMLElement).removeAttribute('style');
}
function morph(from: DOMRect, to: DOMRect, toAnchor: boolean, milliseconds: number, startRadius: string) {
  const element = hub.value!;
  const base = element.getBoundingClientRect(), style = getComputedStyle(trigger.value!);
  const icon = element.querySelector<HTMLElement>('.app-icon')!, text = element.querySelector<HTMLElement>('span')!;
  const destinations = toAnchor ? [trigger.value!.querySelector<HTMLElement>('.app-icon')!, trigger.value!.querySelector<HTMLElement>('span')!] : [icon, text];
  const targetRects = destinations.map(child => child.getBoundingClientRect());
  const initialRects = toAnchor ? [icon.getBoundingClientRect(), text.getBoundingClientRect()] : [trigger.value!.querySelector<HTMLElement>('.app-icon')!.getBoundingClientRect(), trigger.value!.querySelector<HTMLElement>('span')!.getBoundingClientRect()];
  const finalBase = toAnchor ? trigger.value!.getBoundingClientRect() : base;
  const initialBase = toAnchor ? base : trigger.value!.getBoundingClientRect();
  for (const [index, child] of [icon, text].entries()) {
    const initial = initialRects[index]!, destination = targetRects[index]!;
    const left = initial.left - initialBase.left, top = initial.top - initialBase.top;
    Object.assign(child.style, { position: 'absolute', left: `${left}px`, top: `${top}px`, margin: '0', width: `${initial.width}px`, height: `${initial.height}px`, lineHeight: `${initial.height}px` });
    childrenMotion.push(child.animate([
      { left: `${left}px`, top: `${top}px`, width: `${initial.width}px`, height: `${initial.height}px`, fontSize: index ? (toAnchor ? '9px' : '12px') : undefined },
      { left: `${destination.left - finalBase.left}px`, top: `${destination.top - finalBase.top}px`, width: `${destination.width}px`, height: `${destination.height}px`, fontSize: index ? (toAnchor ? '12px' : '9px') : undefined, fontWeight: index && toAnchor ? getComputedStyle(destinations[index]!).fontWeight : undefined },
    ], { duration: milliseconds, easing: motionEasing(), fill: 'forwards' }));
  }
  flight = element.animate([
    { transform: `translate(${from.left - base.left}px,${from.top - base.top}px)`, width: `${from.width}px`, height: `${from.height}px`, borderRadius: startRadius },
    { transform: `translate(${to.left - base.left}px,${to.top - base.top}px)`, width: `${to.width}px`, height: `${to.height}px`, borderRadius: toAnchor ? style.borderRadius : '36px', boxShadow: toAnchor ? style.boxShadow : undefined, borderColor: toAnchor ? style.borderColor : undefined },
  ], { duration: milliseconds, easing: motionEasing(), fill: 'forwards' });
  return flight;
}
async function open() {
  const interrupted = returning.value ? hub.value?.getBoundingClientRect() : undefined;
  const origin = interrupted || trigger.value!.getBoundingClientRect();
  if (returning.value) { serial++; clearFlight(); dialog.value?.close(); if (dialog.value) dialog.value.style.pointerEvents = ''; modalOpen.value = false; returning.value = false; }
  if (modalOpen.value) { void close(); return; }
  stopIntro(); clearTimeout(leaveTimer); mode.value = 'idle'; selected.value = ''; pointed.value = current.value.key;
  locate(); modalMode.value = 'opening'; modalOpen.value = true; returning.value = false;
  const token = ++serial;
  await nextTick();
  if (disposed || !dialog.value || token !== serial) return;
  dialog.value.showModal();
  const destination = hub.value!.getBoundingClientRect();
  const animation = morph(origin, destination, false, reducedMotion() ? 0 : 340, getComputedStyle(trigger.value!).borderRadius);
  requestAnimationFrame(() => requestAnimationFrame(() => { if (token === serial) modalMode.value = 'open'; }));
  try { await animation.finished; } catch { return; }
  if (token === serial) clearFlight();
}
async function close(chosen?: SectionItem, previous = props.active) {
  if (!modalOpen.value || !dialog.value) return;
  const token = ++serial;
  const origin = hub.value!.getBoundingClientRect(), oldRadius = getComputedStyle(hub.value!).borderRadius;
  selected.value = chosen?.key || ''; modalMode.value = 'closing'; returning.value = true;
  // The non-modal return layer allows another click to reverse an unfinished flight.
  dialog.value.close(); dialog.value.show(); dialog.value.style.pointerEvents = 'none';
  clearFlight();
  await nextTick();
  if (disposed || token !== serial) return;
  const animation = morph(origin, anchorRect(), true, reducedMotion() ? 0 : chosen ? 460 : 320, oldRadius);
  const epoch = chosen ? props.epoch : undefined;
  if (epoch !== undefined) animation.startTime = epoch;
  try { await animation.finished; } catch { return; }
  if (token !== serial) return;
  dialog.value.close(); dialog.value.style.pointerEvents = ''; clearFlight();
  modalOpen.value = false; returning.value = false; selected.value = ''; mode.value = 'idle';
  await nextTick();
  trigger.value?.focus({ preventScroll: true });
  if (chosen) void sequence(chosen.key, previous, epoch === undefined ? undefined : epoch + 460);
}
function choose(item: SectionItem) {
  if (item.key === props.active) { if (modalOpen.value) void close(); return; }
  const previous = props.active, central = modalOpen.value;
  if (central) void close(item, previous);
  emit('select', item, reducedMotion() ? 0 : innerWidth <= 640 ? (central ? 680 : 680) : central ? 1400 : 940);
  if (!central) { mode.value = 'idle'; void sequence(item.key, previous); }
}
function keyboard(event: KeyboardEvent) {
  if (event.key === 'Escape') { event.preventDefault(); if (modalOpen.value) void close(); else { mode.value = 'idle'; trigger.value?.focus(); } return; }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  if (!modalOpen.value) { if (mode.value === 'intro') { stopIntro(); mode.value = 'idle'; } peek(); }
  const scope = modalOpen.value ? dialog.value : root.value;
  const buttons = Array.from(scope?.querySelectorAll<HTMLButtonElement>('[data-section-choice]') || []);
  const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + buttons.length) % buttons.length;
  void nextTick(() => requestAnimationFrame(() => { const button = buttons[next]; if (button) { void getComputedStyle(button).visibility; button.focus(); } }));
}
watch(() => props.active, () => { pointed.value = props.active; if (modalOpen.value && !returning.value) void close(); });
watch(() => props.family, () => { void sequence(props.active); });
function resize() { if (modalOpen.value) void close(); }
function scrolled() { if (mode.value === 'hover') mode.value = 'idle'; }
let scrollArea: HTMLElement | null;
onMounted(() => { void sequence(props.active); window.addEventListener('resize', resize); scrollArea = document.getElementById('workspace-scroll'); scrollArea?.addEventListener('scroll', scrolled, { passive: true }); });
onBeforeUnmount(() => { disposed = true; serial++; stopIntro(); clearTimeout(leaveTimer); clearFlight(); dialog.value?.close(); window.removeEventListener('resize', resize); scrollArea?.removeEventListener('scroll', scrolled); });
</script>
<template>
  <nav ref="root" class="section-wheel" :class="[`is-${mode}`, { 'is-away': modalOpen, 'is-returning': returning }]" :style="{ '--peek-shift': `${peekShift}px` }" :aria-label="label" @pointerenter="peek" @pointerleave="leave" @focusout="leave" @keydown="keyboard">
    <div ref="intro" class="section-wheel-intro" :inert="mode !== 'intro'" :aria-hidden="mode !== 'intro'">
      <span ref="introBackdrop" class="section-wheel-intro-backdrop" aria-hidden="true"></span><span ref="indicator" class="section-wheel-intro-indicator" aria-hidden="true"></span><span ref="indicatorEcho" class="section-wheel-intro-indicator" aria-hidden="true"></span>
      <button v-for="item in items" :key="item.key" type="button" :class="{ 'is-current': item.key === introActive }" :aria-label="`切换到${item.name}`" @click="choose(item)"><AppIcon :name="item.icon"/><span>{{ item.name }}</span></button>
    </div>
    <button ref="trigger" type="button" class="section-wheel-trigger" :aria-label="`切换${label}，当前${current.name}`" aria-haspopup="dialog" :aria-expanded="modalOpen || mode === 'hover'" :aria-controls="id" @click="open"><AppIcon :name="current.icon"/><span>{{ current.name }}</span></button>
    <div class="section-wheel-peek" :inert="mode !== 'hover'" :aria-hidden="mode !== 'hover'">
      <svg class="section-wheel-peek-arc" viewBox="-35 -30 205 198" aria-hidden="true"><path d="M124 0 A124 124 0 0 1 52 112"/><path d="M139 0h-8M118 72l-7-4M59 128l-3-7"/></svg>
      <button v-for="(item, index) in others" :key="item.key" type="button" class="section-wheel-peek-item" data-section-choice :style="point(index, others.length, 116, true)" :aria-label="`切换到${item.name}`" @click="choose(item)"><AppIcon :name="item.icon"/><span>{{ item.name }}</span></button>
    </div>
  </nav>
  <Teleport to="body"><dialog :id="id" ref="dialog" class="section-wheel-dialog" :data-mode="modalMode" :aria-label="label + '轮盘'" @cancel.prevent="close()" @click="($event.target === dialog) && close()" @keydown="keyboard">
    <div class="section-wheel-curtain" aria-hidden="true"></div><div class="section-wheel-stage" :style="{ left: `${center.x}px`, top: `${center.y}px`, '--wheel-radius': `${radius}px` }">
      <div class="section-wheel-caption"><small>{{ family === 'emoji' ? 'EMOTE INDEX' : family === 'upload' ? 'RESOURCE INTAKE' : family === 'rankings' ? 'HONOR INDEX' : 'COLLECTION INDEX' }}</small><strong>{{ pointedItem.name }}</strong><span>{{ String(items.findIndex(item => item.key === pointedItem.key) + 1).padStart(2, '0') }} / {{ String(items.length).padStart(2, '0') }}</span></div>
      <svg class="section-wheel-arc" viewBox="-180 -180 360 360" aria-hidden="true"><path d="M-160 12 A160 160 0 0 0 160 12"/><path d="M-174 12h8M174 12h-8M0 172v-8"/></svg>
      <button ref="hub" type="button" class="section-wheel-hub" :aria-label="`返回${hubItem.name}`" @click="close()"><AppIcon :name="hubItem.icon"/><span>{{ hubItem.name }}</span></button>
      <button v-for="(item, index) in others" :key="item.key" type="button" class="section-wheel-choice" data-section-choice :style="point(index, others.length, radius)" :aria-label="`切换到${item.name}`" @pointerenter="pointed = item.key" @focus="pointed = item.key" @click="choose(item)"><span class="section-wheel-choice-icon"><AppIcon :name="item.icon"/></span><span>{{ item.name }}</span></button>
    </div>
  </dialog></Teleport>
</template>
