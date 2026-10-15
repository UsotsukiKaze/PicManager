<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import FilmTitle from './FilmTitle.vue';
import SectionWheel from './SectionWheel.vue';
import { activeSection, sectionFamily, sectionsFor, type SectionItem } from '../ui/sectionNavigation';
import { reducedMotion } from '../state/appearance';
import '../styles/section-navigation.css';
const route = useRoute(), router = useRouter();
const emit = defineEmits<{ motion: [duration: number] }>();
const family = computed(() => sectionFamily(route.path) || 'management');
const items = computed(() => sectionsFor(route));
const target = ref(activeSection(route)), revision = ref(0), duration = ref(940);
const active = computed(() => items.value.find(item => item.key === target.value) || items.value[0]!);
let pending = '', navigationToken = 0;
function animate(key: string, milliseconds: number) {
  target.value = key; duration.value = reducedMotion() ? 0 : milliseconds; revision.value++;
  emit('motion', Math.min(duration.value, 680));
}
async function select(item: SectionItem, milliseconds: number) {
  const token = ++navigationToken;
  pending = item.key; animate(item.key, milliseconds);
  try {
    const failure = await router.push(item.to);
    if (token !== navigationToken) return;
    pending = '';
    if (failure || activeSection(route) !== item.key) animate(activeSection(route), 440);
  } catch {
    if (token === navigationToken) { pending = ''; animate(activeSection(route), 440); }
  }
}
watch(() => `${family.value}:${activeSection(route)}`, (value, previous) => {
  const key = activeSection(route);
  if (pending === key && target.value === key) return;
  navigationToken++; pending = '';
  animate(key, value.split(':')[0] !== previous?.split(':')[0] ? 940 : 560);
});
</script>
<template><header class="modern-management-header section-heading" :data-family="family" :data-section="active.key">
  <div class="section-heading-start"><FilmTitle :title="active.title" :titles="items.map(item => item.title)" :revision="revision" :duration="duration"/><span class="section-heading-index" aria-hidden="true">{{ String(items.findIndex(item => item.key === active.key) + 1).padStart(2, '0') }}<i>/</i>{{ String(items.length).padStart(2, '0') }}</span></div>
  <SectionWheel :items="items" :active="active.key" :family="family" :label="family === 'emoji' ? '表情包库分类' : '图片管理分类'" @select="select"/>
</header></template>
