<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef } from 'vue';
import { useRoute, useRouter, type RouteLocationNormalizedLoaded } from 'vue-router';
import FilmTitle from './FilmTitle.vue';
import SectionWheel from './SectionWheel.vue';
import { activeSection, sectionFamily, sectionsFor, workspaceTitles, type SectionItem } from '../ui/sectionNavigation';
import { reducedMotion } from '../state/appearance';
import '../styles/section-navigation.css';
import { useSession } from '../state/session';
const route = useRoute(), router = useRouter();
const emit = defineEmits<{ motion: [duration: number] }>();
const session = useSession();
type HeadingRoute = Pick<RouteLocationNormalizedLoaded, 'path' | 'query'>;
const snapshot = (value: HeadingRoute): HeadingRoute => ({ path: value.path, query: { ...value.query } });
const heading = shallowRef(snapshot(route));
const family = computed(() => sectionFamily(heading.value.path) || 'management');
const utility = computed(() => family.value === 'settings' || family.value === 'profile');
const items = computed(() => sectionsFor(heading.value).filter(item => family.value !== 'upload' || session.isAdmin || item.key !== 'temp'));
const revision = ref(0), duration = ref(940), epoch = ref<number>();
const active = computed(() => items.value.find(item => item.key === activeSection(heading.value)) || items.value[0]!);
const initialTitles = active.value.title === workspaceTitles.find(item => item.family === family.value)?.title
  ? workspaceTitles.map(item => item.title) : items.value.map(item => item.title);
const titles = shallowRef(initialTitles);
const index = ref(items.value.indexOf(active.value) + 1), count = ref(items.value.length), indexPending = ref(false);
const keyFor = (value: HeadingRoute) => `${sectionFamily(value.path)}:${activeSection(value)}`;
function seatIndex() {
  index.value = items.value.indexOf(active.value) + 1; count.value = items.value.length; indexPending.value = false;
}
function animate(to: HeadingRoute, milliseconds = 940) {
  if (!sectionFamily(to.path) || keyFor(to) === keyFor(heading.value)) return;
  const previousFamily = family.value, previousTitle = active.value.title;
  heading.value = snapshot(to);
  titles.value = previousFamily === family.value ? items.value.map(item => item.title)
    : workspaceTitles.map(item => item.family === family.value ? active.value.title : item.family === previousFamily ? previousTitle : item.title);
  duration.value = reducedMotion() ? 0 : milliseconds;
  epoch.value = Number(document.timeline.currentTime ?? performance.now());
  indexPending.value = !!duration.value; revision.value++;
  if (!duration.value) seatIndex();
  emit('motion', Math.min(duration.value, 680));
}
async function select(item: SectionItem, milliseconds: number) {
  const destination = router.resolve(item.to);
  animate(destination, milliseconds);
  try {
    await router.push(item.to);
  } catch {
    if (keyFor(heading.value) === keyFor(destination)) animate(router.currentRoute.value, 440);
  }
}
// Start at navigation intent, before the new page renders; query-only filters do not turn the reel.
const stopBefore = router.beforeEach(to => { animate(to); });
const stopAfter = router.afterEach((to, _from, failure) => {
  if (failure && keyFor(to) === keyFor(heading.value)) animate(router.currentRoute.value, 440);
  else if (!failure && sectionFamily(to.path)) heading.value = snapshot(to);
});
const stopError = router.onError((_error, to) => {
  if (keyFor(to) === keyFor(heading.value)) animate(router.currentRoute.value, 440);
});
onBeforeUnmount(() => { stopBefore(); stopAfter(); stopError(); });
</script>
<template><header class="modern-management-header section-heading" :data-family="family" :data-section="active.key">
  <div class="section-heading-start"><FilmTitle :title="active.title" :titles="titles" :revision="revision" :duration="duration" :epoch="epoch" @seat="seatIndex"/><span v-if="utility" class="section-heading-caption" aria-hidden="true" :key="family">{{ family === 'settings' ? 'PREFERENCES' : 'MY ARCHIVE' }}</span><span v-else class="section-heading-index" :class="{ 'is-pending': indexPending }" aria-hidden="true">{{ String(index).padStart(2, '0') }}<i>/</i>{{ String(count).padStart(2, '0') }}</span></div>
  <SectionWheel v-if="!utility" :items="items" :active="active.key" :family="family" :epoch="epoch" :label="family === 'emoji' ? '表情包库分类' : family === 'upload' ? '上传工作区' : '图片管理分类'" @select="select"/>
</header></template>
