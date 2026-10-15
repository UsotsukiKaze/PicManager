<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { reducedMotion } from '../state/appearance';
const props = defineProps<{ title: string; titles: string[]; revision: number; duration: number; epoch?: number }>();
const emit = defineEmits<{ seat: [] }>();
const windowEl = ref<HTMLElement>(), strip = ref<HTMLElement>();
const frames = ref([props.title]);
const running = ref(false);
let animation: Animation | undefined, generation = 0;
let velocityAt: ((time: number) => number) | undefined;
let seatTimer: ReturnType<typeof setTimeout> | undefined;
async function roll() {
  const token = ++generation;
  const element = strip.value;
  const height = windowEl.value?.getBoundingClientRect().height || 40;
  let first = frames.value[0] || props.title, second: string | undefined, offset = 0, velocity = 0;
  if (animation && element) {
    const transform = getComputedStyle(element).transform;
    const y = transform === 'none' ? 0 : new DOMMatrixReadOnly(transform).m42;
    // Retain the partly visible pair, sub-row position and velocity on interruption.
    const index = Math.max(0, Math.min(frames.value.length - 2, Math.floor(-y / height)));
    first = frames.value[index]!; second = frames.value[index + 1]; offset = y + index * height;
    velocity = velocityAt?.(Number(animation.currentTime) || 0) || 0;
  }
  animation?.cancel(); animation = undefined; velocityAt = undefined; clearTimeout(seatTimer);
  const target = props.title;
  if (reducedMotion() || !props.duration) {
    frames.value = [target]; running.value = false;
    if (element) element.style.transform = '';
    emit('seat'); return;
  }
  const names = [...new Set(props.titles.length ? props.titles : [target])];
  if (!names.includes(target)) names.push(target);
  const start = Math.max(0, names.indexOf(second || first)), destination = names.indexOf(target);
  // Land closest to one revolution without appending the destination twice.
  let steps = (destination - start + names.length) % names.length;
  if (!steps || steps < names.length / 2) steps += names.length;
  const duration = props.duration;
  const seatTime = duration * .70, ramp = seatTime * .17, coast = seatTime - ramp;
  // Fast interrupted turns get enough travel to retain their current momentum.
  while (velocity < 0 && (steps + (second ? 1 : 0)) * height + offset < -velocity * ramp) steps += names.length;
  frames.value = [first, ...(second ? [second] : []), ...Array.from({ length: steps }, (_, index) => names[(start + index + 1) % names.length]!)];
  if (frames.value.at(-1) !== target) frames.value.push(target);
  const end = -(frames.value.length - 1) * height;
  const amplitude = innerWidth <= 640 ? .75 : 1;
  const seat = end - 4 * amplitude;
  const distance = offset - seat, initialSpeed = -velocity;
  const peak = (2 * distance - initialSpeed * ramp) / seatTime;
  const rampDistance = (initialSpeed + peak) * ramp / 2;
  const stops: Array<[number, number]> = [[.70, seat], [.80, end + 2 * amplitude], [.88, end - .9 * amplitude], [.95, end + .35 * amplitude], [1, end]];
  function sample(time: number) {
    const t = Math.max(0, Math.min(duration, time));
    if (t <= ramp) {
      const angle = Math.PI * t / ramp;
      const travel = initialSpeed * t + (peak - initialSpeed) * (t / 2 - ramp * Math.sin(angle) / (2 * Math.PI));
      return { y: offset - travel, velocity: -(initialSpeed + (peak - initialSpeed) * (1 - Math.cos(angle)) / 2) };
    }
    if (t <= seatTime) {
      const elapsed = t - ramp, angle = Math.PI * elapsed / coast;
      return { y: offset - rampDistance - peak * (elapsed / 2 + coast * Math.sin(angle) / (2 * Math.PI)), velocity: -peak * (1 + Math.cos(angle)) / 2 };
    }
    for (let i = 1; i < stops.length; i++) {
      const [from, a] = stops[i - 1]!, [to, b] = stops[i]!;
      if (t <= to * duration) {
        const span = (to - from) * duration, u = (t - from * duration) / span;
        return { y: a + (b - a) * (1 - Math.cos(Math.PI * u)) / 2, velocity: (b - a) * Math.PI * Math.sin(Math.PI * u) / (2 * span) };
      }
    }
    return { y: end, velocity: 0 };
  }
  running.value = true;
  await nextTick();
  if (token !== generation || !strip.value) return;
  const times = [...new Set([...Array.from({ length: 121 }, (_, i) => i / 120), ...stops.map(stop => stop[0])])].sort((a, b) => a - b);
  animation = strip.value.animate(times.map(progress => {
    const frame = sample(progress * duration);
    return { offset: progress, transform: `translateY(${frame.y}px)`, filter: `blur(${progress < .70 ? Math.min(.65, Math.abs(frame.velocity) * .9) : 0}px)` };
  }), { duration, fill: 'forwards', easing: 'linear' });
  if (props.epoch !== undefined) animation.startTime = props.epoch;
  velocityAt = time => sample(time).velocity;
  seatTimer = setTimeout(() => { if (token === generation) emit('seat'); }, Math.max(0, seatTime - Number(animation.currentTime || 0)));
  const current = animation;
  current.onfinish = async () => {
    if (token !== generation) return;
    clearTimeout(seatTimer); emit('seat'); frames.value = [target];
    await nextTick();
    if (token !== generation) return;
    current.cancel(); animation = undefined; velocityAt = undefined; running.value = false;
  };
}
onMounted(() => { void roll(); });
watch(() => props.revision, () => { void roll(); });
onBeforeUnmount(() => { generation++; clearTimeout(seatTimer); animation?.cancel(); });
</script>
<template><h1 class="section-film-title" :data-rolling="running"><span class="modern-sr-only">{{ title }}</span><span ref="windowEl" class="section-film-window" aria-hidden="true"><span ref="strip" class="section-film-strip"><span v-for="(frame, index) in frames" :key="index" class="section-film-frame">{{ frame }}</span></span></span></h1></template>
