<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { useQuery } from '@tanstack/vue-query';
import { emojiDetail, type EmojiRecord } from '../api/emojis';
import { requestJSON } from '../api/http';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { invalidateDomain } from '../state/client';
import { reducedMotion } from '../state/appearance';
import { motionEasing } from '../ui/motion';
import AppIcon from './AppIcon.vue';
const props = defineProps<{ emoji: EmojiRecord; previous?: boolean; next?: boolean; sourceRect?: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'> }>();
const emit = defineEmits<{ close: []; move: [delta: number]; edit: [id: string]; deleted: [] }>();
const session = useSession();
const workspace = useWorkspace();
const dialog = ref<HTMLDialogElement>();
const media = ref<HTMLElement>();
const ready = ref(false);
const broken = ref(false);
const deleting = ref(false);
let closing = false;
let exiting = false;
let entryId = '';
const { data, isPending, error, refetch } = useQuery({ queryKey: computed(() => ['emojis', session.identity, 'detail', props.emoji.emoji_id]), queryFn: ({ signal, queryKey }) => emojiDetail(String(queryKey[3]), signal), staleTime: 30_000 });
const current = computed(() => data.value || props.emoji);
const ratio = computed(() => (current.value.width || 1) / (current.value.height || 1));
const tags = computed(() => [
  ...current.value.groups.map(item => ({ ...item, kind: '分组', key: `g${item.id}`, style: '' })),
  ...current.value.characters.map(item => ({ ...item, kind: '角色', key: `c${item.id}`, style: 'pm-tag-character' })),
  ...current.value.emotions.map(item => ({ ...item, kind: item.name.startsWith('#') ? '功能' : '情绪', key: `e${item.id}`, style: item.name.startsWith('#') ? 'pm-tag-function' : 'pm-tag-emotion' })),
]);
const title = computed(() => current.value.characters.map(item => item.name).join('、') || current.value.groups[0]?.name || '表情包');
const bytes = computed(() => current.value.file_size ? `${(current.value.file_size / 1024).toFixed(1)} KB` : '未知');
watch(() => props.emoji.emoji_id, async id => {
  ready.value = false; broken.value = false;
  await nextTick();
  if (!dialog.value?.open) {
    entryId = id; dialog.value?.showModal();
    if (media.value && props.sourceRect && !reducedMotion()) {
      const source = props.sourceRect, target = media.value.getBoundingClientRect();
      media.value.animate([{ transform: `translate(${source.left - target.left}px,${source.top - target.top}px) scale(${source.width / target.width},${source.height / target.height})`, opacity: .6 }, { transform: 'none', opacity: 1 }], { duration: 420, easing: motionEasing() });
    }
  }
}, { immediate: true });
async function dismiss() {
  if (exiting) return;
  exiting = true;
  if (!reducedMotion()) {
    const nodes = [media.value, dialog.value?.querySelector<HTMLElement>('.modern-reader-info')];
    const starts = nodes.map(node => node ? { opacity: getComputedStyle(node).opacity, transform: getComputedStyle(node).transform } : undefined);
    nodes.forEach(node => node?.getAnimations().forEach(animation => animation.cancel()));
    const target = media.value?.getBoundingClientRect(), source = props.sourceRect;
    const returns = props.emoji.emoji_id === entryId && source && target && source.top < innerHeight && source.top + source.height > 0;
    const end = returns ? `translate(${source.left - target.left}px,${source.top - target.top}px) scale(${source.width / target.width},${source.height / target.height})` : 'translateY(8px) scale(.985)';
    await Promise.allSettled(nodes.map((node, index) => node?.animate([starts[index] || { opacity: 1, transform: 'none' }, { opacity: index === 0 && returns ? .35 : 0, transform: index === 0 ? end : 'translateY(6px)' }], { duration: 260, easing: motionEasing(), fill: 'forwards' }).finished));
  }
  emit('close');
}
async function remove() {
  if (deleting.value || !confirm(`确认删除表情包“${title.value}”？\n文件和标签关联也会删除，此操作无法恢复。`)) return;
  deleting.value = true;
  try { await requestJSON(`/api/emojis/${encodeURIComponent(current.value.emoji_id)}`, { method: 'DELETE' }); invalidateDomain('/emojis'); workspace.notify('表情包已删除', 'success'); emit('deleted'); emit('close'); }
  catch (reason) { workspace.notify((reason as Error).message, 'error'); }
  finally { deleting.value = false; }
}
function keyboard(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft' && props.previous) { event.preventDefault(); emit('move', -1); }
  if (event.key === 'ArrowRight' && props.next) { event.preventDefault(); emit('move', 1); }
}
onBeforeUnmount(() => { closing = true; dialog.value?.close(); });
</script>
<template><Teleport to="body"><dialog ref="dialog" class="modern-reader modern-emoji-reader" aria-label="表情包详情" @cancel.prevent="dismiss" @close="!closing && emit('close')" @keydown="keyboard">
  <div class="modern-reader-layout" :style="{ '--media-ratio': ratio }" @click="event => { if (event.target === event.currentTarget) void dismiss(); }">
    <section ref="media" class="modern-reader-media">
      <img v-if="!broken" class="modern-reader-preview" :class="{ loaded: ready }" :src="`/${current.file_path.replace(/^\//, '')}`" :alt="title" decoding="async" @load="ready = true" @error="broken = true">
      <button type="button" class="modern-reader-close" aria-label="关闭详情" @click="dismiss"><AppIcon name="close"/></button>
      <button v-if="previous" type="button" class="modern-reader-arrow previous" aria-label="上一张" @click="emit('move', -1)"><AppIcon name="left"/></button>
      <button v-if="next" type="button" class="modern-reader-arrow next" aria-label="下一张" @click="emit('move', 1)"><AppIcon name="right"/></button>
      <span v-if="!ready && !broken" class="modern-reader-center modern-spinner" role="status" aria-label="正在加载表情包"></span>
      <div v-if="broken" class="modern-reader-center"><p>图片加载失败</p><button class="btn btn-secondary" @click="broken = false">重试</button></div>
    </section>
    <aside class="modern-reader-info">
      <small class="modern-eyebrow">EMOTE DETAILS</small><h2>{{ title }}</h2>
      <p v-if="isPending" role="status">正在加载详情…</p><div v-if="error" role="alert"><p>详情加载失败</p><button class="btn btn-secondary" @click="refetch()">重试</button></div>
      <p v-if="current.description" class="modern-description">{{ current.description }}</p>
      <section class="modern-tag-section"><h3>表情标签</h3><div class="modern-detail-tags pm-tag-box"><span v-for="tag in tags" :key="tag.key" class="pm-tag" :class="tag.style">{{ tag.name }}<small>{{ tag.kind }}</small></span></div></section>
      <details class="modern-file-info"><summary>文件信息</summary><dl class="modern-detail-facts"><div><dt>编号</dt><dd>{{ current.emoji_id }}</dd></div><div><dt>格式</dt><dd>{{ current.file_extension.toUpperCase() }}</dd></div><div><dt>尺寸</dt><dd>{{ current.width || '—' }} × {{ current.height || '—' }}</dd></div><div><dt>大小</dt><dd>{{ bytes }}</dd></div><div v-if="current.original_filename"><dt>原文件名</dt><dd>{{ current.original_filename }}</dd></div></dl></details>
      <div class="modern-detail-actions"><a class="btn btn-primary" :href="`/api/emojis/${current.emoji_id}/download`" download><AppIcon name="download"/>下载表情包</a><button v-if="session.isAdmin" class="modern-detail-icon" aria-label="编辑表情包" title="编辑表情包" @click="emit('edit', current.emoji_id)"><AppIcon name="edit"/></button><button v-if="session.isAdmin" class="modern-detail-icon modern-detail-delete" aria-label="删除表情包" title="删除表情包" :disabled="deleting" @click="remove"><AppIcon name="trash"/></button></div>
    </aside>
  </div>
</dialog></Teleport></template>
