<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { reducedMotion } from '../state/appearance';
const props = defineProps<{ title: string; titles: string[]; revision: number; duration: number }>();
const windowEl = ref<HTMLElement>(), strip = ref<HTMLElement>();
const frames = ref([props.title]);
const running = ref(false);
let animation: Animation | undefined, generation = 0;
async function roll(initial = false) {
  const token = ++generation;
  const element = strip.value;
  const height = windowEl.value?.getBoundingClientRect().height || 36;
  let first = frames.value[0] || props.title, second: string | undefined, offset = 0;
  if (animation && element) {
    const transform = getComputedStyle(element).transform;
    const y = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
    const index = Math.max(0, Math.min(frames.value.length - 1, Math.floor(-y / height)));
    first = frames.value[index]!; second = frames.value[index + 1]; offset = y + index * height;
  }
  animation?.cancel(); animation = undefined;
  if (reducedMotion()) { frames.value = [props.title]; running.value = false; if (element) element.style.transform = ''; return; }
  const names = props.titles;
  const start = Math.max(0, names.indexOf(second || first));
  const cycle = Array.from({ length: names.length * (initial ? 2 : 1) }, (_, index) => names[(start + index + 1) % names.length]!);
  frames.value = [first, ...(second ? [second] : []), ...cycle, props.title];
  running.value = true;
  await nextTick();
  if (token !== generation || !strip.value) return;
  const end = -(frames.value.length - 1) * height;
  const distance = end - offset;
  animation = strip.value.animate([
    { transform: `translateY(${offset}px)`, offset: 0 },
    { transform: `translateY(${offset + distance * .66}px)`, offset: .32 },
    { transform: `translateY(${end + height * .85}px)`, offset: .66, easing: 'cubic-bezier(.16,1,.3,1)' },
    { transform: `translateY(${end - 1.5}px)`, offset: .94 },
    { transform: `translateY(${end}px)`, offset: 1 },
  ], { duration: props.duration, fill: 'forwards', easing: 'linear' });
  animation.onfinish = () => {
    if (token !== generation) return;
    frames.value = [props.title]; animation?.cancel(); animation = undefined; running.value = false;
  };
}
onMounted(() => { void roll(true); });
watch(() => props.revision, () => { void roll(); });
onBeforeUnmount(() => { generation++; animation?.cancel(); });
</script>
<template><h1 class="section-film-title" :data-rolling="running"><span class="modern-sr-only">{{ title }}</span><span ref="windowEl" class="section-film-window" aria-hidden="true"><span ref="strip" class="section-film-strip"><span v-for="(frame, index) in frames" :key="index" class="section-film-frame">{{ frame }}</span></span></span></h1></template>
