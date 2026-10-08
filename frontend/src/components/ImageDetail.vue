<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useQuery } from '@tanstack/vue-query';
import { imageDetail } from '../api/catalog';
import { safeAvatar, requestJSON } from '../api/http';
import type { ImageCardRecord } from '../api/types';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { invalidateDomain } from '../state/client';
import AppIcon from './AppIcon.vue';
const props = defineProps<{ image: ImageCardRecord | null; previous?: boolean; next?: boolean; sourceRect?: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'> }>();
const emit = defineEmits<{ close: []; move: [delta: number]; edit: [id: string]; deleted: [id: string] }>();
const session = useSession();
const workspace = useWorkspace();
const dialog = ref<HTMLDialogElement>();
const media = ref<HTMLElement>();
let closing = false;
let exiting = false;
const ready = ref(false);
const broken = ref(false);
const revealed = ref(false);
const original = ref(false);
const previewSource = ref('');
const decodedRatio = ref<number>();
const deleting = ref(false);
const { data, isPending, error, refetch } = useQuery({
  queryKey: computed(() => ['images', session.identity, 'detail', props.image?.image_id]),
  queryFn: ({ signal, queryKey }) => imageDetail(String(queryKey[3]), signal),
  enabled: computed(() => !!props.image), staleTime: 30_000,
});
const current = computed(() => data.value || props.image);
const restricted = computed(() => ['r16', 'r18'].includes(current.value?.age_rating || ''));
const visible = computed(() => !restricted.value || revealed.value);
const ratio = computed(() => decodedRatio.value || (current.value?.width || 4) / (current.value?.height || 5));
watch([() => props.image?.image_id, visible, original], async ([id, shown, full], _previous, cleanup) => {
  ready.value = false; broken.value = false; previewSource.value = '';
  if (!id || !shown) return;
  if (full) { previewSource.value = `/resource/originals/${id}`; return; }
  const controller = new AbortController();
  let url: string | undefined;
  cleanup(() => { controller.abort(); if (url) URL.revokeObjectURL(url); });
  try {
    const response = await fetch(`/resource/previews/${id}.webp`, { credentials: 'same-origin', signal: controller.signal, priority: 'high' });
    // The server returns a 200 PNG placeholder when a derivative is missing.
    if (!response.ok || response.headers.get('X-PicManager-Preview') === 'missing') {
      if (!controller.signal.aborted) original.value = true;
      return;
    }
    const blob = await response.blob();
    if (controller.signal.aborted) return;
    url = URL.createObjectURL(blob);
    previewSource.value = url;
  } catch {
    if (!controller.signal.aborted) original.value = true;
  }
}, { immediate: true, flush: 'post' });
const pidURL = computed(() => {
  const pid = current.value?.pid?.match(/^\s*(\d+)/)?.[1];
  return pid ? `https://www.pixiv.net/artworks/${pid}` : undefined;
});
watch(() => props.image?.image_id, async value => {
  ready.value = false; broken.value = false; revealed.value = false; original.value = false; decodedRatio.value = undefined;
  await nextTick();
  if (value && !dialog.value?.open) {
    dialog.value?.showModal();
    if (media.value && props.sourceRect && !matchMedia('(prefers-reduced-motion:reduce)').matches) {
      const source = props.sourceRect;
      const target = media.value.getBoundingClientRect();
      media.value.animate?.([
        { transform: `translate(${source.left - target.left}px,${source.top - target.top}px) scale(${source.width / target.width},${source.height / target.height})`, opacity: .6 },
        { transform: 'none', opacity: 1 },
      ], { duration: 240, easing: 'cubic-bezier(.2,.7,.2,1)' });
    }
  }
  if (!value && dialog.value?.open) dialog.value?.close();
}, { immediate: true, flush: 'sync' });
function fallback() {
  if (!original.value) { original.value = true; return; }
  broken.value = true;
}
function loaded(event: Event) {
  const image = event.target as HTMLImageElement;
  if (image.naturalWidth && image.naturalHeight) decodedRatio.value = image.naturalWidth / image.naturalHeight;
  ready.value = true;
}
async function reveal() {
  revealed.value = true;
  await nextTick();
  dialog.value?.querySelector<HTMLButtonElement>('.modern-reader-close')?.focus({ preventScroll: true });
}
async function showOriginal() {
  if (original.value || !visible.value) return;
  original.value = true; ready.value = false;
  await nextTick();
  dialog.value?.querySelector<HTMLButtonElement>('.modern-reader-close')?.focus({ preventScroll: true });
}
function keyboard(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft' && props.previous) { event.preventDefault(); emit('move', -1); }
  if (event.key === 'ArrowRight' && props.next) { event.preventDefault(); emit('move', 1); }
}
async function dismiss() {
  if (exiting) return;
  exiting = true;
  if (!matchMedia('(prefers-reduced-motion:reduce)').matches) {
    const animations = [media.value, dialog.value?.querySelector('.modern-reader-info')].map(node => node?.animate?.(
      [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(8px) scale(.985)' }],
      { duration: 150, easing: 'ease-in', fill: 'forwards' }));
    await Promise.allSettled(animations.map(animation => animation?.finished));
  }
  emit('close');
}
async function remove() {
  if (!data.value || deleting.value) return;
  const id = data.value.image_id;
  if (!window.confirm(session.isAdmin
    ? `确认删除图片“${data.value.pid || id}”及其标签关联？\n原图和预览文件也会删除，此操作无法恢复。`
    : `确认提交图片“${data.value.pid || id}”的删除申请？\n图片将在管理员审核后处理。`)) return;
  deleting.value = true;
  try {
    const result = await requestJSON<{ status: string; message: string }>(`/api/images/${id}`, { method: 'DELETE' });
    invalidateDomain('/images');
    workspace.notify(result.message, 'success');
    if (result.status === 'success') emit('deleted', id);
    emit('close');
  } catch (reason) { workspace.notify((reason as Error).message, 'error'); }
  finally { deleting.value = false; }
}
onBeforeUnmount(() => { closing = true; dialog.value?.close(); });
</script>
<template><Teleport to="body"><dialog ref="dialog" class="modern-reader" aria-label="图片详情" @cancel.prevent="dismiss" @close="!closing && emit('close')" @click="event => { if (event.target === dialog) void dismiss(); }" @keydown="keyboard">
  <div v-if="current" class="modern-reader-layout" :style="{ '--media-ratio': ratio }" @click="event => { if (event.target === event.currentTarget) void dismiss(); }">
    <section ref="media" class="modern-reader-media" :data-rating="current.age_rating" :class="{ blurred: !ready || !visible, restricted: !visible }">
      <img class="modern-reader-thumb" :src="`/resource/thumbs/${current.image_id}.webp`" alt="" decoding="async">
      <img v-if="visible && !broken && previewSource" :key="previewSource" class="modern-reader-preview" :class="{ loaded: ready }" :src="previewSource" :alt="current.pid || current.image_id" decoding="async" fetchpriority="high" @load="loaded" @error="fallback">
      <button type="button" class="modern-reader-close" aria-label="关闭详情" @click="dismiss"><AppIcon name="close"/></button>
      <button v-if="previous" type="button" class="modern-reader-arrow previous" aria-label="上一张" @click="emit('move', -1)"><AppIcon name="left"/></button>
      <button v-if="next" type="button" class="modern-reader-arrow next" aria-label="下一张" @click="emit('move', 1)"><AppIcon name="right"/></button>
      <button v-if="!visible" type="button" class="modern-reader-center modern-age-reveal" @click="reveal">显示 {{ current.age_rating.toUpperCase() }} 图片</button>
      <span v-else-if="!ready && !broken" class="modern-reader-center modern-spinner" role="status" aria-label="正在加载清晰预览"></span>
      <div v-else-if="broken" class="modern-reader-center"><p>图片加载失败</p><button class="btn btn-secondary" @click="broken = false; ready = false">重试</button></div>
      <button v-if="visible && !broken" type="button" class="modern-original-island" :class="{ 'is-original': original && ready, 'is-loading': original && !ready }" :disabled="original" :aria-label="original ? (ready ? '已显示原图' : '正在加载原图') : '查看原图'" :aria-busy="original && !ready" @click="showOriginal"><AppIcon :name="original ? (ready ? 'check' : 'refresh') : 'eye'" :class="{ 'is-spinning': original && !ready }"/><Transition name="island-label" mode="out-in"><span :key="original ? (ready ? 'ready' : 'loading') : 'preview'">{{ original ? (ready ? '原图' : '加载原图') : '查看原图' }}</span></Transition></button>
    </section>
    <aside class="modern-reader-info">
      <small class="modern-eyebrow">ARTWORK DETAILS</small>
      <h2><a v-if="pidURL" :href="pidURL" target="_blank" rel="noopener noreferrer">{{ current.pid }}</a><span v-else>{{ current.image_id }}</span></h2>
      <a v-if="current.artist" class="modern-artist" :href="`https://www.pixiv.net/users/${encodeURIComponent(current.artist.id)}`" target="_blank" rel="noopener noreferrer"><img :src="safeAvatar(current.artist.avatar_url)" alt="" width="36" height="36" @error="($event.target as HTMLImageElement).src = '/static/icon/Pic.png'"><span>{{ current.artist.name }}</span></a>
      <p v-if="isPending" role="status">正在加载详情…</p><div v-if="error" role="alert"><p>详情加载失败</p><button class="btn btn-secondary" @click="refetch()">重试</button></div>
      <template v-if="data"><p v-if="data.description" class="modern-description">{{ data.description }}</p>
        <section class="modern-tag-section"><h3>图库标签</h3><div class="modern-detail-tags pm-tag-box"><RouterLink v-for="item in data.groups" :key="`g${item.id}`" class="pm-tag" :to="{ path: '/gallery', query: { group_id: item.id } }" @click="emit('close')">{{ item.name }}<small>分组</small></RouterLink><RouterLink v-for="item in data.characters" :key="`c${item.id}`" class="pm-tag pm-tag-character" :to="{ path: '/gallery', query: { character_id: item.id } }" @click="emit('close')">{{ item.name }}<small v-if="item.group_name">{{ item.group_name }}</small></RouterLink><RouterLink v-for="item in data.feature_tags" :key="`f${item.id}`" class="pm-tag pm-tag-feature_tag" :to="{ path: '/gallery', query: { feature_tag_id: item.id } }" @click="emit('close')">{{ item.name }}</RouterLink></div></section>
        <section v-if="data.pixiv_tags.length" class="modern-tag-section"><h3>Pixiv 标签</h3><div class="modern-pixiv-tags"><span v-for="item in data.pixiv_tags" :key="item.name" class="pm-tag">{{ item.translated_name || item.name }}</span></div></section>
        <details class="modern-file-info"><summary>文件信息</summary><dl class="modern-detail-facts"><div><dt>尺寸</dt><dd>{{ data.width }} × {{ data.height }}</dd></div><div><dt>分级</dt><dd>{{ data.age_rating.toUpperCase() }}</dd></div><div v-if="(data.pixiv_page_count || 0) > 1"><dt>作品页码</dt><dd>{{ (data.pixiv_page || 0) + 1 }} / {{ data.pixiv_page_count }}</dd></div></dl></details>
        <div class="modern-validation"><span :class="{ checked: data.local_verified }">{{ data.local_verified ? '本地已校验' : '本地未校验' }}</span><span :class="{ checked: data.pixiv_verified }">{{ data.pixiv_verified ? 'Pixiv 已校验' : 'Pixiv 未校验' }}</span></div>
        <div class="modern-detail-actions"><button class="btn btn-primary" @click="emit('edit', data.image_id)"><AppIcon name="edit"/>编辑标签</button><a v-if="visible" class="modern-detail-icon" :href="`/api/images/${data.image_id}/download`" aria-label="下载原图" title="下载原图"><AppIcon name="download"/></a><button v-else class="modern-detail-icon" disabled aria-label="下载原图" title="请先揭示受限内容"><AppIcon name="download"/></button><button class="modern-detail-icon modern-detail-delete" :aria-label="session.isAdmin ? '删除图片' : '请求删除图片'" :title="session.isAdmin ? '删除图片' : '请求删除图片'" :disabled="deleting" @click="remove"><AppIcon name="trash"/></button></div>
      </template>
    </aside>
  </div>
</dialog></Teleport></template>
