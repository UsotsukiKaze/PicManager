<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue';
import { reducedMotion } from '../state/appearance';

const props = withDefaults(defineProps<{
  text: string;
  mode?: 'text' | 'number';
  ready?: boolean;
  duration?: number;
  delay?: number;
}>(), { mode: 'text', ready: true, duration: 720, delay: 0 });

const root = ref<HTMLElement>();
const characters = computed(() => Array.from(props.text));
const display = ref<string[]>([]);
const running = ref(false);
let played = false;
let active = true;
let visible = false;
let frame = 0;
let observer: IntersectionObserver | undefined;
let motionObserver: MutationObserver | undefined;
let motionMedia: MediaQueryList | undefined;

const mutable = (character: string) => (props.mode === 'number' ? /[0-9]/ : /[A-Z0-9]/).test(character);
function settle() {
  cancelAnimationFrame(frame);
  frame = 0;
  running.value = false;
  display.value = characters.value;
}
function play() {
  if (!active || !visible || !props.ready || played) return;
  played = true;
  if (reducedMotion() || (props.mode === 'number' && props.text === '0')) { settle(); return; }
  const target = characters.value;
  const slots = target.reduce<number[]>((result, character, index) => {
    if (mutable(character)) result.push(index);
    return result;
  }, []);
  if (!slots.length) { settle(); return; }
  const alphabet = props.mode === 'number' ? '0123456789' : 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/+_';
  display.value = target.map(character => mutable(character) ? (props.mode === 'number' ? '·' : '_') : character);
  running.value = true;
  const start = performance.now() + props.delay;
  let lastUpdate = -Infinity;
  function tick(now: number) {
    if (now >= start + props.duration || reducedMotion()) { settle(); return; }
    if (now >= start && now - lastUpdate >= 70) {
      lastUpdate = now;
      const progress = Math.max(0, Math.min(1, ((now - start) / props.duration - .2) / .65));
      const locked = Math.floor(progress * slots.length);
      const next = [...target];
      slots.forEach((position, index) => {
        if (index >= locked) next[position] = alphabet[Math.floor(Math.random() * alphabet.length)];
      });
      display.value = next;
    }
    frame = requestAnimationFrame(tick);
  }
  frame = requestAnimationFrame(tick);
}
function motionChanged() {
  if (reducedMotion()) { played = true; settle(); }
}
watch(() => [props.text, props.ready], () => {
  settle();
  play();
});
onMounted(() => {
  motionMedia = matchMedia('(prefers-reduced-motion:reduce)');
  motionMedia.addEventListener('change', motionChanged);
  motionObserver = new MutationObserver(motionChanged);
  motionObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
  if (typeof IntersectionObserver === 'undefined') { visible = true; play(); return; }
  observer = new IntersectionObserver(entries => {
    visible = entries.some(entry => entry.isIntersecting);
    if (visible) play();
    else if (running.value) settle();
  }, { threshold: .15 });
  if (root.value) observer.observe(root.value);
});
onDeactivated(() => {
  active = false;
  played = true;
  settle();
  observer?.disconnect();
});
onActivated(() => { active = true; });
onBeforeUnmount(() => {
  settle();
  observer?.disconnect();
  motionObserver?.disconnect();
  motionMedia?.removeEventListener('change', motionChanged);
});
</script>

<template>
  <span ref="root" class="decode-text" :data-decoding="running || undefined">
    <span class="decode-text-readable" :class="{ 'decode-text-masked': running }">{{ text }}</span>
    <span v-if="running" class="decode-text-overlay" aria-hidden="true"><span v-for="(character, index) in characters" :key="index" class="decode-text-cell"><span class="decode-text-reserve">{{ character }}</span><span class="decode-text-glyph">{{ display[index] }}</span></span></span>
  </span>
</template>

<style scoped>
.decode-text { display:inline-block; position:relative; white-space:pre; }
.decode-text-masked { opacity:0; }
.decode-text-overlay { position:absolute; inset:0; width:max-content; pointer-events:none; user-select:none; }
.decode-text-cell { display:inline-block; position:relative; }
.decode-text-reserve { visibility:hidden; }
.decode-text-glyph { position:absolute; inset:0; }
</style>
