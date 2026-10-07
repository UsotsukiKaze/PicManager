<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onActivated, onDeactivated, ref, shallowRef, watch } from 'vue';
import { keepPreviousData, useQuery } from '@tanstack/vue-query';
import { useRoute, useRouter } from 'vue-router';
import { allEntities, searchImages } from '../api/catalog';
import type { AgeRating, ImageCardRecord, ImageFilters } from '../api/types';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { queryClient } from '../state/client';
import EntityPicker from '../components/EntityPicker.vue';
import ImageCard from '../components/ImageCard.vue';
const ImageDetail = defineAsyncComponent(() => import('../components/ImageDetail.vue'));
const session = useSession();
const workspace = useWorkspace();
const route = useRoute();
const router = useRouter();
const active = ref(true);
const detail = ref<ImageCardRecord | null>(null);
const closedCard = ref('');
let origin: HTMLElement | null = null;
const sourceRect = shallowRef<DOMRect>();
let originImageId = '';
let debounce: ReturnType<typeof setTimeout> | undefined;
const draft = ref({ pid: workspace.filters.pid || '', artist: workspace.filters.artist || '', description: workspace.filters.description || '' });
const groups = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'groups']), queryFn: ({ signal }) => allEntities('groups', signal), enabled: active, staleTime: 60_000 });
const characters = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'characters']), queryFn: ({ signal }) => allEntities('characters', signal), enabled: active, staleTime: 60_000 });
const features = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'feature-tags']), queryFn: ({ signal }) => allEntities('feature-tags', signal), enabled: active, staleTime: 60_000 });
const availableCharacters = computed(() => (characters.data.value || []).filter(row => !workspace.filters.group_id || row.group_id === workspace.filters.group_id));
const key = computed(() => ['images', session.identity, 'list', { ...workspace.filters, page: workspace.page }]);
const { data, isPending, isFetching, isPlaceholderData, error, refetch } = useQuery({
  queryKey: key, queryFn: ({ signal, queryKey }) => {
    const { page, ...filters } = queryKey[3] as ImageFilters & { page: number };
    return searchImages(filters, page, signal);
  },
  enabled: active, placeholderData: keepPreviousData,
});
const pages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / 20)));
const pageButtons = computed(() => {
  const start = Math.max(1, Math.min(workspace.page - 2, pages.value - 4));
  return Array.from({ length: Math.min(5, pages.value) }, (_, index) => start + index);
});
function applyFilter(name: keyof ImageFilters, value: unknown) {
  workspace.filters = { ...workspace.filters, [name]: value || undefined };
  if (name === 'group_id') workspace.filters.character_id = undefined;
  workspace.page = 1;
  syncURL();
}
function syncURL() {
  const query = Object.fromEntries(Object.entries(workspace.filters).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]));
  if (workspace.page > 1) query.page = String(workspace.page);
  void router.replace({ path: '/gallery', query });
}
function submitSearch() {
  clearTimeout(debounce);
  workspace.filters = { ...workspace.filters, ...draft.value };
  workspace.page = 1; syncURL();
}
watch(draft, () => {
  clearTimeout(debounce);
  if (Object.entries(draft.value).every(([name, value]) => (workspace.filters[name as keyof ImageFilters] || '') === value)) return;
  debounce = setTimeout(() => {
    workspace.filters = { ...workspace.filters, ...draft.value };
    workspace.page = 1; syncURL();
  }, 250);
}, { deep: true });
watch(() => route.query, query => {
  if (route.path !== '/gallery') return;
  const filters: ImageFilters = {};
  for (const field of ['group_id', 'character_id', 'feature_tag_id'] as const) {
    const value = Number(query[field]); if (Number.isInteger(value) && value > 0) filters[field] = value;
  }
  for (const field of ['pid', 'description', 'artist'] as const) if (typeof query[field] === 'string') filters[field] = query[field];
  if (['all', 'r12', 'r16', 'r18'].includes(String(query.age_rating))) filters.age_rating = query.age_rating as AgeRating;
  if (JSON.stringify(filters) !== JSON.stringify(workspace.filters)) workspace.filters = filters;
  clearTimeout(debounce);
  draft.value = { pid: filters.pid || '', artist: filters.artist || '', description: filters.description || '' };
  workspace.page = Math.max(1, Number.parseInt(String(query.page || 1), 10) || 1);
}, { immediate: true });
async function go(page: number) {
  if (page < 1 || page > pages.value || isPlaceholderData.value) return;
  workspace.page = page; syncURL();
  await nextTick(); document.getElementById('workspace-scroll')?.scrollTo({ top: 0, behavior: 'smooth' });
}
function open(image: ImageCardRecord, from: HTMLElement) {
  closedCard.value = ''; origin = from;
  originImageId = image.image_id;
  sourceRect.value = from.closest('.modern-image-card')?.getBoundingClientRect();
  detail.value = image;
}
function close() {
  if (!detail.value) return;
  closedCard.value = originImageId || detail.value.image_id;
  detail.value = null;
  const target = origin?.closest('.modern-image-card')?.querySelector<HTMLButtonElement>('.modern-image-open');
  void nextTick().then(() => target?.focus({ preventScroll: true }));
}
const detailIndex = computed(() => data.value?.images.findIndex(row => row.image_id === detail.value?.image_id) ?? -1);
function move(delta: number) {
  const item = data.value?.images[detailIndex.value + delta];
  if (item) detail.value = item;
}
async function edit(id: string) {
  close(); await nextTick();
  try { const bridge = await import('../compat/bridge'); await bridge.editImage(id); }
  catch (reason) { workspace.notify((reason as Error).message, 'error'); }
}
watch(data, result => {
  if (!result || isPlaceholderData.value || !active.value) return;
  if (workspace.page > pages.value) { workspace.page = pages.value; syncURL(); }
});
onActivated(() => { active.value = true; });
watch(() => session.identity, close);
onDeactivated(() => { active.value = false; close(); clearTimeout(debounce); void queryClient.cancelQueries({ queryKey: ['images', session.identity, 'list'] }); });
</script>
<template><section class="modern-gallery" aria-label="图库">
  <header class="modern-page-heading"><div><h1>图片</h1><span>{{ data?.total ?? '—' }} 张图片</span></div><button class="btn btn-secondary" :disabled="isFetching" @click="refetch()">{{ isFetching ? '更新中…' : '刷新' }}</button></header>
  <div class="modern-age-tabs" role="group" aria-label="年龄分级"><button v-for="rating in ['', 'all', 'r12', 'r16', 'r18']" :key="rating" type="button" :aria-pressed="(workspace.filters.age_rating || '') === rating" @click="applyFilter('age_rating', rating)">{{ rating === '' ? '全部' : rating === 'all' ? '全年龄' : rating.toUpperCase() }}</button></div>
  <form class="modern-gallery-filters" @submit.prevent="submitSearch">
    <EntityPicker label="分组" :items="groups.data.value || []" :model-value="workspace.filters.group_id" @update:model-value="applyFilter('group_id', $event)"/>
    <EntityPicker label="角色" :items="availableCharacters" :model-value="workspace.filters.character_id" @update:model-value="applyFilter('character_id', $event)"/>
    <EntityPicker label="特征" :items="features.data.value || []" :model-value="workspace.filters.feature_tag_id" @update:model-value="applyFilter('feature_tag_id', $event)"/>
    <label class="modern-input">PID<input v-model="draft.pid" placeholder="作品 ID 或车牌号" aria-label="搜索 PID"></label>
    <label class="modern-input">画师<input v-model="draft.artist" placeholder="画师名" aria-label="搜索画师"></label>
    <label class="modern-input">描述<input v-model="draft.description" placeholder="图片描述" aria-label="搜索描述"></label>
    <button type="submit" class="modern-sr-only">搜索</button>
  </form>
  <p v-if="groups.error.value || characters.error.value || features.error.value" class="modern-inline-error" role="alert">筛选标签加载失败。<button @click="groups.refetch(); characters.refetch(); features.refetch()">重试</button></p>
  <div class="modern-gallery-status" aria-live="polite">{{ isFetching && !isPending ? '正在更新结果…' : '' }}</div>
  <div v-if="error" class="modern-feature-status" role="alert"><p>图片加载失败，请重试</p><button class="btn btn-secondary" @click="refetch()">重试</button></div>
  <div v-else-if="isPending" class="modern-image-grid" aria-busy="true"><div v-for="n in 10" :key="n" class="modern-card-skeleton"></div></div>
  <div v-else-if="!data?.images.length" class="empty-state">没有匹配的图片</div>
  <div v-else class="modern-image-grid" :aria-busy="isFetching"><ImageCard v-for="image in data.images" :key="image.image_id" :image="image" :suppress-actions="closedCard === image.image_id" @resume="closedCard = ''" @open="open" @edit="edit"/></div>
  <nav v-if="data?.images.length" class="modern-pagination" aria-label="图库页码"><button :disabled="workspace.page === 1 || isPlaceholderData" @click="go(workspace.page - 1)">‹</button><button v-for="page in pageButtons" :key="page" :aria-current="page === workspace.page ? 'page' : undefined" :disabled="isPlaceholderData" @click="go(page)">{{ page }}</button><button :disabled="workspace.page >= pages || isPlaceholderData" @click="go(workspace.page + 1)">›</button><span>{{ workspace.page }} / {{ pages }}</span></nav>
  <ImageDetail v-if="detail" :image="detail" :source-rect="sourceRect" :previous="detailIndex > 0" :next="detailIndex < (data?.images.length || 0) - 1" @close="close" @move="move" @edit="edit" @deleted="refetch()"/>
</section></template>
