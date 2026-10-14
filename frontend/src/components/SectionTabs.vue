<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import AppIcon from './AppIcon.vue';
const props = defineProps<{ modelValue: string; tabs: Array<{ value: string; name: string; icon: string }>; label: string }>();
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const navigation = ref<HTMLElement>();
const indicator = ref({ left: 0, width: 0, height: 0 });
let observer: ResizeObserver | undefined;
function measure() {
  const active = navigation.value?.querySelector<HTMLElement>('[aria-selected="true"]');
  if (active) indicator.value = { left: active.offsetLeft, width: active.offsetWidth, height: active.offsetHeight };
}
watch(() => props.modelValue, async () => { await nextTick(); measure(); });
onMounted(() => { observer = new ResizeObserver(measure); if (navigation.value) observer.observe(navigation.value); measure(); });
onBeforeUnmount(() => observer?.disconnect());
function keyboard(event: KeyboardEvent, index: number) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? props.tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + props.tabs.length) % props.tabs.length;
  emit('update:modelValue', props.tabs[next]!.value);
  navigation.value?.querySelectorAll<HTMLButtonElement>('button')[next]?.focus();
}
</script>
<template><nav ref="navigation" class="modern-management-tabs modern-section-tabs" role="tablist" :aria-label="label">
  <span class="modern-tab-indicator" aria-hidden="true" :style="{ transform: `translateX(${indicator.left}px)`, width: `${indicator.width}px`, height: `${indicator.height}px`, opacity: indicator.width ? 1 : 0 }"></span>
  <button v-for="(tab, index) in tabs" :key="tab.value" type="button" role="tab" :aria-selected="modelValue === tab.value" :tabindex="modelValue === tab.value ? 0 : -1" @click="emit('update:modelValue', tab.value)" @keydown="keyboard($event, index)"><AppIcon :name="tab.icon"/>{{ tab.name }}</button>
</nav></template>
