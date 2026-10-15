<script setup lang="ts" generic="T">
import { nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, shallowRef, watch } from 'vue';
import { reducedMotion } from '../state/appearance';
import { waveDelays } from '../ui/galleryWave';
import '../styles/gallery-wave.css';

const props = withDefaults(defineProps<{
  items: T[];
  requestKey: string;
  scopeKey: string;
  pending: boolean;
  failed: boolean;
  refreshKey?: number;
}>(), { refreshKey: 0 });
const root = ref<HTMLElement>();
const displayed = shallowRef<T[]>(props.pending || props.failed ? [] : props.items);
const phase = ref<'idle' | 'cover' | 'blank' | 'reveal'>('idle');
let active = true;
let operation = 0;
let request = 0;
let animations: Animation[] = [];
let heightAnimation: Animation | undefined;
let preparation: AbortController | undefined;
let media: MediaQueryList | undefined;
let motionObserver: MutationObserver | undefined;

function cancel(cancelHeight = true) {
  operation++;
  preparation?.abort();
  animations.forEach(animation => animation.cancel());
  animations = [];
  if (cancelHeight) heightAnimation?.cancel();
}
function settle() {
  cancel();
  phase.value = 'idle';
  if (!props.pending || props.failed) displayed.value = props.failed ? [] : props.items;
}
function motionChanged() { if (reducedMotion()) settle(); }

async function turn(kind: 'cover' | 'reveal') {
  const node = root.value;
  if (!node || !active) return;
  const turners = Array.from(node.querySelectorAll<HTMLElement>('.wave-turner'));
  // Capture the current visual frame before cancelling an interrupted reveal.
  const from = turners.map(turner => getComputedStyle(turner).transform);
  cancel(kind === 'cover');
  const token = operation;
  phase.value = kind;
  await nextTick();
  if (token !== operation || !active) return;
  const columns = getComputedStyle(node).gridTemplateColumns.split(/\s+/).length;
  const delays = waveDelays(turners.length, columns);
  animations = turners.map((turner, index) => {
    turner.dataset.waveDelay = String(Math.round(delays[index]));
    return turner.animate([
      { transform: kind === 'reveal' ? 'rotateY(-180deg)' : from[index] },
      { transform: `rotateY(${kind === 'cover' ? -180 : -360}deg)` },
    ], { duration: kind === 'cover' ? 360 : 420, delay: delays[index], easing: 'cubic-bezier(.4,0,.2,1)', fill: 'both' });
  });
  await Promise.all(animations.map(animation => animation.finished.catch(() => {})));
  if (token !== operation || !active) return;
  phase.value = kind === 'cover' ? 'blank' : 'idle';
  await nextTick();
  if (token !== operation) return;
  animations.forEach(animation => animation.cancel());
  animations = [];
  if (kind === 'cover') void reveal();
  else if (!props.pending || props.failed) displayed.value = props.failed ? [] : props.items;
}

/** Wait briefly for visible thumbnails; broken or slow images never stall the wave. */
function thumbnails(signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const cleanups: (() => void)[] = [];
    const node = root.value;
    const viewport = document.getElementById('workspace-scroll')?.getBoundingClientRect();
    const images = Array.from(node?.querySelectorAll<HTMLImageElement>('.wave-front img') || []).filter(image => {
      const rect = image.getBoundingClientRect();
      return !image.complete && rect.bottom > (viewport?.top ?? 0) && rect.top < (viewport?.bottom ?? innerHeight);
    });
    let remaining = images.length;
    let held = false, finished = false;
    const finish = () => { if (finished) return; finished = true; cleanups.forEach(cleanup => cleanup()); resolve(); };
    const check = () => { if (held && remaining === 0) finish(); };
    const minimum = setTimeout(() => { held = true; check(); }, 80);
    const timeout = setTimeout(finish, 650);
    cleanups.push(() => { clearTimeout(minimum); clearTimeout(timeout); });
    signal.addEventListener('abort', finish, { once: true });
    cleanups.push(() => signal.removeEventListener('abort', finish));
    images.forEach(image => {
      const loaded = () => { remaining--; check(); };
      image.addEventListener('load', loaded, { once: true });
      image.addEventListener('error', loaded, { once: true });
      cleanups.push(() => { image.removeEventListener('load', loaded); image.removeEventListener('error', loaded); });
    });
    if (signal.aborted) finish();
  });
}
async function reveal() {
  if (phase.value !== 'blank' || (props.pending && !props.failed) || !active) return;
  preparation?.abort();
  const controller = new AbortController();
  preparation = controller;
  const target = request;
  const height = root.value?.offsetHeight || 0;
  displayed.value = props.failed ? [] : props.items;
  await nextTick();
  if (controller.signal.aborted || target !== request || !active) return;
  const node = root.value;
  if (node && node.offsetHeight !== height) {
    heightAnimation?.cancel();
    heightAnimation = node.animate([{ height: `${height}px` }, { height: `${node.offsetHeight}px` }], { duration: 220, easing: 'ease-out' });
  }
  await thumbnails(controller.signal);
  if (controller.signal.aborted || target !== request || !active) return;
  if (props.pending && !props.failed) return;
  if (displayed.value.length) void turn('reveal');
  else phase.value = 'idle';
}
function begin() {
  request++;
  preparation?.abort();
  if (!active || !displayed.value.length || reducedMotion() || !root.value?.animate) { settle(); return; }
  if (phase.value === 'cover') return;
  if (phase.value === 'blank') { void reveal(); return; }
  void turn('cover');
}
watch(() => [props.requestKey, props.refreshKey], begin, { flush: 'post' });
watch(() => [props.items, props.pending, props.failed], () => {
  if (phase.value === 'idle') {
    if (!props.pending || props.failed) displayed.value = props.failed ? [] : props.items;
  } else if (phase.value === 'blank') void reveal();
}, { flush: 'post' });
// Identity changes discard the old account's snapshot immediately.
watch(() => props.scopeKey, () => { settle(); displayed.value = props.pending ? [] : props.items; }, { flush: 'sync' });
onMounted(() => {
  media = matchMedia('(prefers-reduced-motion:reduce)');
  media.addEventListener('change', motionChanged);
  motionObserver = new MutationObserver(motionChanged);
  motionObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
});
onDeactivated(() => { active = false; settle(); });
onActivated(() => { active = true; settle(); });
onBeforeUnmount(() => {
  active = false; cancel();
  media?.removeEventListener('change', motionChanged);
  motionObserver?.disconnect();
});
</script>

<template>
  <div ref="root" class="wave-results" :class="{ 'modern-image-grid': displayed.length }" :data-wave-phase="phase" :aria-busy="pending || phase !== 'idle'">
    <template v-if="displayed.length">
      <div v-for="(item, index) in displayed" :key="index" class="wave-cell">
        <div class="wave-turner">
          <div class="wave-face wave-front" :inert="phase !== 'idle'" :aria-hidden="phase !== 'idle'"><slot :item="item" :index="index"/></div>
          <div class="wave-face wave-back" aria-hidden="true"></div>
        </div>
      </div>
    </template>
    <div v-else class="wave-empty"><slot name="empty"/></div>
  </div>
</template>
