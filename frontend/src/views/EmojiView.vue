<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { keepPreviousData, useQuery } from '@tanstack/vue-query';
import { useRoute, useRouter } from 'vue-router';
import { allEntities } from '../api/catalog';
import { editEmoji, emojiFacets, searchEmojis, type EmojiFilters, type EmojiRecord } from '../api/emojis';
import { requestJSON } from '../api/http';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { invalidateDomain, queryClient } from '../state/client';
import { reducedMotion } from '../state/appearance';
import { useFilterMotion } from '../ui/filterMotion';
import AppIcon from '../components/AppIcon.vue';
import EntityPicker from '../components/EntityPicker.vue';
import EntityAvatar from '../components/EntityAvatar.vue';
import SectionTabs from '../components/SectionTabs.vue';
import '../styles/emoji.css';
const EmojiDetail = defineAsyncComponent(() => import('../components/EmojiDetail.vue'));
const session = useSession(), workspace = useWorkspace(), route = useRoute(), router = useRouter();
const filters = ref<EmojiFilters>({});
const page = ref(1);
const draft = ref('');
const filtersOpen = ref(false);
const tab = computed(() => route.query.tab === 'tags' ? 'tags' : 'list');
const tagType = ref('all'), tagQuery = ref('');
const detail = shallowRef<EmojiRecord>();
const sourceRect = shallowRef<DOMRect>();
const loaded = ref(new Set<string>()), broken = ref(new Set<string>());
const closedCard = ref('');
const editing = ref(false);
let origin: HTMLElement | undefined;
let originId = '';
let debounce: ReturnType<typeof setTimeout> | undefined;
const { filterMotion, cancelFilterMotion } = useFilterMotion();
watch(() => route.query, query => {
  const next: EmojiFilters = {};
  for (const key of ['group_id', 'character_id', 'emotion_id', 'function_id'] as const) {
    const value = Number(query[key]); if (Number.isSafeInteger(value) && value > 0) next[key] = value;
  }
  if (typeof query.description === 'string' && query.description.trim()) next.description = query.description;
  filters.value = next; draft.value = next.description || '';
  const number = Number(query.page); page.value = Number.isSafeInteger(number) && number > 0 ? number : 1;
}, { immediate: true });
const groups = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'groups']), queryFn: ({ signal }) => allEntities('groups', signal) });
const characters = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'characters']), queryFn: ({ signal }) => allEntities('characters', signal) });
const emotions = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'emotion-tags']), queryFn: ({ signal }) => allEntities('emotion-tags', signal) });
const facets = useQuery({ queryKey: computed(() => ['emojis', session.identity, 'facets']), queryFn: ({ signal }) => emojiFacets(signal) });
const availableCharacters = computed(() => (characters.data.value || []).filter(item => !filters.value.group_id || item.group_id === filters.value.group_id));
const roleTabs = computed(() => (facets.data.value || []).filter(item => !filters.value.group_id || availableCharacters.value.some(character => character.id === item.id)));
const basicEmotions = computed(() => (emotions.data.value || []).filter(item => !item.name.startsWith('#')));
const functions = computed(() => (emotions.data.value || []).filter(item => item.name.startsWith('#')));
const { data, isPending, isFetching, isPlaceholderData, error, refetch } = useQuery({
  queryKey: computed(() => ['emojis', session.identity, 'list', { ...filters.value, page: page.value }]),
  queryFn: ({ signal, queryKey }) => { const { page, ...values } = queryKey[3] as EmojiFilters & { page: number }; return searchEmojis(values, page, signal); },
  placeholderData: keepPreviousData,
});
const activeFilters = computed(() => {
  const rows: Array<{ key: keyof EmojiFilters; label: string; value: string }> = [];
  for (const [key, label, items] of [['group_id', '分组', groups.data.value], ['character_id', '角色', characters.data.value], ['emotion_id', '情绪', emotions.data.value], ['function_id', '功能', emotions.data.value]] as const) {
    const id = filters.value[key]; if (id) rows.push({ key, label, value: items?.find(item => item.id === id)?.name || `#${id}` });
  }
  if (filters.value.description) rows.push({ key: 'description', label: '备注', value: filters.value.description });
  return rows;
});
const pages = computed(() => Math.max(1, Math.ceil((data.value?.total || 0) / 20)));
const pageButtons = computed(() => { const start = Math.max(1, Math.min(page.value - 2, pages.value - 4)); return Array.from({ length: Math.min(5, pages.value) }, (_, index) => start + index); });
watch([pages, isPlaceholderData], ([count, pending]) => { if (!pending && page.value > count) { page.value = count; syncURL(); } });
function syncURL() {
  const query = Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value !== undefined && value !== '').map(([key, value]) => [key, String(value)]));
  if (page.value > 1) query.page = String(page.value);
  if (tab.value === 'tags') query.tab = 'tags';
  void router.replace({ path: '/emoji', query });
}
function applyFilter(key: keyof EmojiFilters, value: unknown) {
  clearTimeout(debounce);
  const next = { ...filters.value, description: draft.value.trim() || undefined, [key]: value || undefined };
  if (key === 'group_id' && value && !availableCharacters.value.some(item => item.id === next.character_id && item.group_id === value)) next.character_id = undefined;
  filters.value = next; page.value = 1; syncURL();
}
function removeFilter(key: keyof EmojiFilters) { if (key === 'description') draft.value = ''; applyFilter(key, undefined); }
function clearFilters() { clearTimeout(debounce); filters.value = {}; draft.value = ''; page.value = 1; syncURL(); }
watch(draft, value => { clearTimeout(debounce); if (value.trim() !== (filters.value.description || '')) debounce = setTimeout(() => applyFilter('description', value.trim()), 300); });
function closeFilters() { filtersOpen.value = false; document.getElementById('emoji-query-toggle')?.focus({ preventScroll: true }); }
function switchTab(value: string) { detail.value = undefined; void router.replace({ path: '/emoji', query: { ...route.query, tab: value === 'tags' ? 'tags' : undefined } }); }
function go(number: number) { page.value = number; syncURL(); document.getElementById('modern-emoji-results')?.scrollIntoView({ behavior: reducedMotion() ? 'instant' : 'smooth', block: 'start' }); }
function open(emoji: EmojiRecord, node: HTMLElement) { closedCard.value = ''; originId = emoji.emoji_id; origin = node.closest('article')?.querySelector<HTMLElement>('.modern-image-open') || node; sourceRect.value = node.closest('article')?.getBoundingClientRect() || origin.getBoundingClientRect(); detail.value = emoji; node.blur(); }
async function close() { closedCard.value = originId || detail.value?.emoji_id || ''; detail.value = undefined; await nextTick(); origin?.focus({ preventScroll: true }); }
const detailIndex = computed(() => data.value?.emojis.findIndex(item => item.emoji_id === detail.value?.emoji_id) ?? -1);
function move(delta: number) { const next = data.value?.emojis[detailIndex.value + delta]; if (next) detail.value = next; }
async function edit(kind: 'upload' | 'emoji' | 'emotion', id?: string | number) {
  if (editing.value) return; editing.value = true;
  if (kind === 'emoji') await close();
  try { await editEmoji(kind, id); } catch (reason) { workspace.notify((reason as Error).message, 'error'); } finally { editing.value = false; }
}
const filteredTags = computed(() => (emotions.data.value || []).filter(item => (tagType.value === 'all' || item.name.startsWith('#') === (tagType.value === 'function')) && [item.name, ...(item.aliases || [])].join(' ').toLowerCase().includes(tagQuery.value.toLowerCase())));
async function removeTag(id: number, name: string) {
  if (!confirm(`确认删除标签“${name}”？`)) return;
  try { await requestJSON(`/api/emotion-tags/${id}`, { method: 'DELETE' }); invalidateDomain('/emotion-tags'); workspace.notify('标签已删除', 'success'); }
  catch (reason) { workspace.notify((reason as Error).message, 'error'); }
}
onBeforeUnmount(() => { clearTimeout(debounce); void queryClient.cancelQueries({ queryKey: ['emojis', session.identity, 'list'] }); });
</script>

<template><section class="modern-gallery modern-emoji" aria-label="表情包库">
  <header class="modern-management-header"><h1>表情包库</h1><SectionTabs :model-value="tab" :tabs="[{ value: 'list', name: '全部表情', icon: 'emoji' }, { value: 'tags', name: '情绪 / 功能', icon: 'tags' }]" label="表情包库分类" @update:model-value="switchTab"/></header>
  <template v-if="tab === 'list'">
    <header class="modern-gallery-toolbar">
      <div class="modern-age-controls"><span class="modern-age-label" aria-hidden="true">角色</span><div class="modern-age-tabs modern-emoji-role-tabs" role="group" aria-label="按角色筛选表情包"><button type="button" :aria-pressed="!filters.character_id" @click="applyFilter('character_id', undefined)">不限</button><button v-for="character in roleTabs" :key="character.id" type="button" :aria-pressed="filters.character_id === character.id" :title="`${character.emoji_count} 个表情包`" @click="applyFilter('character_id', character.id)">{{ character.name }}</button></div></div>
      <div class="modern-gallery-tools"><button class="modern-query-toggle modern-emoji-upload" :disabled="editing" @click="edit('upload')"><AppIcon name="upload"/><span>上传表情包</span></button><button id="emoji-query-toggle" class="modern-query-toggle" :aria-expanded="filtersOpen" aria-controls="emoji-search-panel" aria-label="搜索与筛选表情包" @click="filtersOpen = !filtersOpen"><AppIcon name="search"/><span>搜索与筛选</span><b v-if="activeFilters.length">{{ activeFilters.length }}</b><svg class="modern-query-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg></button><button class="modern-icon-action" :disabled="isFetching" aria-label="刷新表情包" @click="refetch()"><AppIcon name="refresh" :class="{ 'is-spinning': isFetching }"/></button></div>
    </header>
    <Transition :css="false" @enter="(element, done) => filterMotion(element, done, true)" @leave="(element, done) => filterMotion(element, done, false)" @enter-cancelled="cancelFilterMotion" @leave-cancelled="cancelFilterMotion"><div v-show="filtersOpen" id="emoji-search-panel" class="modern-filter-panel" :aria-hidden="!filtersOpen" :inert="!filtersOpen" @keydown.esc="closeFilters"><form class="modern-gallery-filters modern-emoji-filters" role="search" aria-label="表情搜索条件" @submit.prevent="applyFilter('description', draft.trim())"><EntityPicker label="分组" :items="groups.data.value || []" :model-value="filters.group_id" @update:model-value="applyFilter('group_id', $event)"/><EntityPicker label="角色" :items="availableCharacters" :model-value="filters.character_id" @update:model-value="applyFilter('character_id', $event)"/><EntityPicker label="基础情绪" :items="basicEmotions" :model-value="filters.emotion_id" @update:model-value="applyFilter('emotion_id', $event)"/><EntityPicker label="功能标签" :items="functions" :model-value="filters.function_id" @update:model-value="applyFilter('function_id', $event)"/><label class="modern-input modern-emoji-description">搜索备注<input v-model="draft" placeholder="备注关键词" aria-label="搜索备注"></label><button type="submit" class="modern-sr-only">搜索</button></form></div></Transition>
    <div id="modern-emoji-results" class="modern-gallery-results"><div class="modern-result-count" role="status" aria-live="polite"><span>{{ activeFilters.length ? '找到 ' : '' }}<b>{{ data?.total ?? '—' }}</b> 个表情包</span><span v-if="isFetching" class="modern-result-loading"><i class="modern-status-dot"></i><span class="modern-sr-only">正在更新结果</span></span></div><div v-if="activeFilters.length" class="modern-filter-chips" aria-label="当前搜索条件"><button v-for="filter in activeFilters" :key="filter.key" type="button" class="modern-filter-chip" :aria-label="`移除${filter.label}：${filter.value}`" @click="removeFilter(filter.key)"><small>{{ filter.label }}</small><span>{{ filter.value }}</span><AppIcon name="close"/></button></div><button v-if="activeFilters.length" type="button" class="modern-clear-filters" @click="clearFilters">清除条件</button></div>
    <div v-if="error" class="modern-feature-status" role="alert"><p>表情包加载失败</p><button class="btn btn-secondary" @click="refetch()">重试</button></div><div v-else-if="isPending" class="modern-image-grid" aria-busy="true"><div v-for="n in 10" :key="n" class="modern-card-skeleton"></div></div><div v-else-if="!data?.emojis.length" class="modern-gallery-empty" role="status"><AppIcon name="search"/><p>{{ activeFilters.length ? '没有匹配的表情包' : '还没有表情包' }}</p><button v-if="activeFilters.length" type="button" @click="clearFilters">清除搜索条件</button></div>
    <div v-else id="modern-emoji-grid" class="modern-image-grid" :aria-busy="isFetching"><article v-for="(emoji, index) in data.emojis" :key="emoji.emoji_id" class="modern-image-card modern-emoji-card" :class="{ 'suppress-actions': closedCard === emoji.emoji_id }" :style="{ '--card-order': index % 5 }" @pointerleave="closedCard = ''" @keydown="closedCard = ''"><button class="modern-image-open" type="button" :aria-label="`查看表情包 ${emoji.emoji_id} 的详情`" @click="open(emoji, $event.currentTarget as HTMLElement)"><img v-if="!broken.has(emoji.emoji_id)" :src="`/${emoji.file_path.replace(/^\//, '')}`" :class="{ 'is-loaded': loaded.has(emoji.emoji_id) }" alt="" loading="lazy" decoding="async" @load="loaded.add(emoji.emoji_id)" @error="broken.add(emoji.emoji_id)"><span v-else class="modern-image-placeholder">图片加载失败</span></button><span v-if="emoji.file_extension.toLowerCase() === 'gif'" class="modern-rating">GIF</span><div class="modern-card-footer"><div class="modern-card-identity"><span class="modern-card-avatars"><EntityAvatar :name="emoji.characters[0]?.name || emoji.groups[0]?.name" :src="emoji.characters[0]?.avatar_url || emoji.groups[0]?.avatar_url"/></span><div><strong>{{ emoji.characters.map(item => item.name).join('、') || emoji.groups[0]?.name || '未分类' }}</strong><small>{{ [...emoji.groups.map(item => item.name), ...emoji.emotions.map(item => item.name)].join(' · ') || '未设置标签' }}</small></div></div><div class="modern-card-actions"><button type="button" @click="open(emoji, $event.currentTarget as HTMLElement)"><AppIcon name="eye"/>查看详情</button><a :href="`/api/emojis/${emoji.emoji_id}/download`" download><AppIcon name="download"/>下载</a></div></div></article></div>
    <nav v-if="data?.emojis.length" class="modern-pagination" aria-label="表情库页码"><button aria-label="上一页" :disabled="page === 1 || isPlaceholderData" @click="go(page - 1)"><AppIcon name="left"/></button><button v-for="number in pageButtons" :key="number" :aria-current="number === page ? 'page' : undefined" :disabled="isPlaceholderData" @click="go(number)">{{ number }}</button><button aria-label="下一页" :disabled="page >= pages || isPlaceholderData" @click="go(page + 1)"><AppIcon name="right"/></button><span>{{ page }} / {{ pages }}</span></nav>
  </template>
  <template v-else><header class="modern-gallery-toolbar"><div class="modern-age-controls"><span class="modern-age-label">类型</span><div class="modern-age-tabs" role="group" aria-label="标签类型"><button v-for="item in [{ value: 'all', name: '不限' }, { value: 'emotion', name: '基础情绪' }, { value: 'function', name: '功能标签' }]" :key="item.value" :aria-pressed="tagType === item.value" @click="tagType = item.value">{{ item.name }}</button></div></div><div class="modern-gallery-tools modern-emoji-tag-tools"><input v-model="tagQuery" class="modern-emoji-tag-search" type="search" placeholder="搜索标签名称或别称" aria-label="搜索标签"><button v-if="session.isAdmin" class="modern-query-toggle" :disabled="editing" @click="edit('emotion')"><AppIcon name="tags"/>添加标签</button></div></header><div v-if="!filteredTags.length" class="modern-gallery-empty"><AppIcon name="search"/><p>没有匹配的标签</p></div><div v-else class="modern-emoji-tags"><article v-for="item in filteredTags" :key="item.id" class="modern-emoji-tag-card"><div><strong>{{ item.name }}</strong><small>{{ item.name.startsWith('#') ? '功能标签' : '基础情绪' }}</small><p v-if="item.aliases?.length">{{ item.aliases.join(' / ') }}</p></div><div v-if="session.isAdmin" class="modern-emoji-tag-actions"><button class="modern-icon-action" :aria-label="`编辑${item.name}`" @click="edit('emotion', item.id)"><AppIcon name="edit"/></button><button class="modern-icon-action" :aria-label="`删除${item.name}`" @click="removeTag(item.id, item.name)"><AppIcon name="trash"/></button></div></article></div></template>
  <EmojiDetail v-if="detail" :emoji="detail" :source-rect="sourceRect" :previous="detailIndex > 0" :next="detailIndex < (data?.emojis.length || 0) - 1" @close="close" @move="move" @edit="id => edit('emoji', id)" @deleted="refetch()"/>
</section></template>
