<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useQuery } from '@tanstack/vue-query';
import { allEntities } from '../api/catalog';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { useUploads } from '../state/uploads';
import { cloneMetadata, editable, formatBytes, mergeTagIds, missingMetadata, statusLabels, type UploadItem, type UploadMetadata, type TagOperation } from '../ui/uploadModel';
import UploadEditor from '../components/UploadEditor.vue';
import AppIcon from '../components/AppIcon.vue';
import { reducedMotion } from '../state/appearance';
import '../styles/upload.css';
const route = useRoute(), session = useSession(), workspace = useWorkspace(), uploads = useUploads();
const input = ref<HTMLInputElement>(), cardArea = ref<HTMLElement>(), filter = ref('all'), search = ref(''), focused = ref(''), selected = ref<string[]>([]), editorOpen = ref(false), dragging = ref(false), tempLoading = ref(false), tempError = ref('');
const temp = computed(() => route.query.tab === 'temp' && session.isAdmin);
const groups = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'groups']), queryFn: ({ signal }) => allEntities('groups', signal) });
const characters = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'characters']), queryFn: ({ signal }) => allEntities('characters', signal) });
const features = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'feature-tags']), queryFn: ({ signal }) => allEntities('feature-tags', signal) });
const emotions = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'emotion-tags']), queryFn: ({ signal }) => allEntities('emotion-tags', signal), enabled: computed(() => session.isAdmin) });
const catalogError = computed(() => groups.isError.value || characters.isError.value || features.isError.value || (session.isAdmin && emotions.isError.value));
const targets = computed(() => selected.value.length ? uploads.items.filter(item => selected.value.includes(item.id) && editable(item)) : uploads.items.filter(item => item.id === focused.value).slice(0, 1));
const editorDisabled = computed(() => targets.value.every(item => !editable(item)));
const single = computed(() => uploads.items.length === 1);
const totalSize = computed(() => uploads.items.reduce((sum, item) => sum + item.file.size, 0));
const attention = computed(() => uploads.items.filter(item => ['attention', 'reviewing', 'uncertain'].includes(item.status)));
const missing = computed(() => uploads.items.filter(item => editable(item) && missingMetadata(item.metadata, session.isAdmin).length));
const completed = computed(() => uploads.items.filter(item => ['success', 'pending'].includes(item.status)));
const shown = computed(() => uploads.items.filter(item => (!search.value || item.file.name.toLowerCase().includes(search.value.toLowerCase())) && (filter.value === 'all' || filter.value === 'ready' && uploads.ready.includes(item) || filter.value === 'missing' && missing.value.includes(item) || filter.value === 'attention' && attention.value.includes(item) || filter.value === 'finished' && completed.value.includes(item) || filter.value === 'failed' && item.status === 'failed')));
const submitIds = computed(() => selected.value.length ? uploads.ready.filter(item => selected.value.includes(item.id)).map(item => item.id) : uploads.ready.map(item => item.id));
const filterOptions = computed(() => [{ key: 'all', name: '全部', count: uploads.items.length }, { key: 'ready', name: '就绪', count: uploads.ready.length }, { key: 'missing', name: '待补充', count: missing.value.length }, { key: 'attention', name: '待确认', count: attention.value.length }, { key: 'finished', name: '已完成', count: completed.value.length }, { key: 'failed', name: '失败', count: uploads.items.filter(item => item.status === 'failed').length }]);
let previousRects = new Map<string, DOMRect>(), knownIds = new Set<string>(), animations: Animation[] = [], tempGeneration = 0, dragDepth = 0;
const undo = ref<Array<{ id: string; metadata: UploadMetadata }>>([]);
function rememberRects() { previousRects = new Map(Array.from(cardArea.value?.querySelectorAll<HTMLElement>('[data-upload-id]') || []).map(node => [node.dataset.uploadId!, node.getBoundingClientRect()])); }
async function animateCards() {
  await nextTick(); animations.forEach(animation => animation.cancel()); animations = [];
  if (reducedMotion()) return;
  for (const node of cardArea.value?.querySelectorAll<HTMLElement>('[data-upload-id]') || []) {
    const before = previousRects.get(node.dataset.uploadId!), after = node.getBoundingClientRect();
    if (!before && knownIds.has(node.dataset.uploadId!)) continue;
    const frames = before ? [{ transform: `translate(${before.x - after.x}px,${before.y - after.y}px) scale(${before.width / after.width},${before.height / after.height})` }, { transform: 'none' }] : [{ opacity: 0, transform: 'translateY(12px) scale(.97)' }, { opacity: 1, transform: 'none' }];
    animations.push(node.animate(frames, { duration: 420, easing: 'cubic-bezier(.16,1,.3,1)' }));
  }
  previousRects.clear();
  knownIds = new Set(uploads.items.map(item => item.id));
}
watch(() => uploads.items.map(item => item.id).join(','), () => {
  const ids = new Set(uploads.items.map(item => item.id)); selected.value = selected.value.filter(id => ids.has(id));
  if (!ids.has(focused.value)) focused.value = uploads.items[0]?.id || '';
  void animateCards();
});
watch(() => uploads.items.map(item => `${item.id}:${item.status}`).join(','), () => { selected.value = selected.value.filter(id => uploads.items.some(item => item.id === id && editable(item))); });
watch(() => route.query.kind, value => { if (value === 'emoji' && session.isAdmin) uploads.defaults.kind = 'emoji'; else if (value === 'image') uploads.defaults.kind = 'image'; }, { immediate: true });
watch(() => route.query.state, value => { if (value === 'attention') filter.value = 'attention'; }, { immediate: true });
for (const key of ['group_id', 'character_id'] as const) {
  const id = Number(route.query[key]); if (Number.isSafeInteger(id) && id > 0) uploads.defaults[key === 'group_id' ? 'group_ids' : 'character_ids'] = [id];
}
for (const [key, field] of [['feature_tag_id', 'feature_tag_ids'], ['emotion_id', 'emotion_ids'], ['function_id', 'emotion_ids']] as const) {
  const id = Number(route.query[key]); if (Number.isSafeInteger(id) && id > 0) uploads.defaults[field] = [...new Set([...uploads.defaults[field], id])];
}
async function add(files: File[]) { const before = uploads.items.length; rememberRects(); await uploads.addFiles(files); if (uploads.items.length > before && single.value) editorOpen.value = true; }
function fileChange(event: Event) { const element = event.target as HTMLInputElement; void add(Array.from(element.files || [])); element.value = ''; }
function dragEnter(event: DragEvent) { if (event.dataTransfer?.types.includes('Files')) { event.preventDefault(); dragDepth++; dragging.value = true; } }
function dragLeave() { if (--dragDepth <= 0) { dragging.value = false; dragDepth = 0; } }
function drop(event: DragEvent) { event.preventDefault(); dragging.value = false; dragDepth = 0; void add(Array.from(event.dataTransfer?.files || [])); }
function paste(event: ClipboardEvent) {
  if (temp.value || (event.target as HTMLElement)?.closest('input,textarea,[contenteditable=true]')) return;
  const files = Array.from(event.clipboardData?.files || []); if (files.length) { event.preventDefault(); void add(files); }
}
function select(item: UploadItem) { rememberRects(); focused.value = item.id; selected.value = []; editorOpen.value = true; void animateCards(); }
function toggle(item: UploadItem) { rememberRects(); selected.value = selected.value.includes(item.id) ? selected.value.filter(id => id !== item.id) : [...selected.value, item.id]; if (selected.value.length) { focused.value = item.id; editorOpen.value = true; } void animateCards(); }
function closeEditor() {
  editorOpen.value = false;
  if (innerWidth <= 800) void nextTick(() => cardArea.value?.querySelector<HTMLElement>(`[data-upload-id="${focused.value}"] .intake-card-image`)?.focus({ preventScroll: true }));
}
function all() { const ids = shown.value.filter(editable).map(item => item.id); selected.value = ids.every(id => selected.value.includes(id)) ? [] : ids; if (selected.value.length) editorOpen.value = true; }
function patch(patch: Partial<UploadMetadata>, operation: TagOperation) {
  const items = targets.value.filter(editable); undo.value = items.map(item => ({ id: item.id, metadata: cloneMetadata(item.metadata) }));
  for (const item of items) {
    for (const [key, value] of Object.entries(patch)) {
      if (Array.isArray(value)) { const field = key as 'group_ids' | 'character_ids' | 'feature_tag_ids' | 'emotion_ids'; item.metadata[field] = mergeTagIds(item.metadata[field], value, operation); }
      else Object.assign(item.metadata, { [key]: value });
    }
    if (patch.pid !== undefined) item.pidInferred = false;
  }
  if (items.length > 1) workspace.notify(`已更新 ${items.length} 张`, 'success');
}
function undoPatch() { for (const before of undo.value) { const item = uploads.items.find(item => item.id === before.id); if (item && editable(item)) item.metadata = cloneMetadata(before.metadata); } undo.value = []; selected.value = []; focused.value = ''; void nextTick(() => { focused.value = uploads.items[0]?.id || ''; }); }
function defaults(value: UploadMetadata) { uploads.defaults = { ...cloneMetadata(value), pid: '', description: '' }; workspace.notify('后续文件将沿用标签、类型与分级', 'success'); }
function remove(ids: string[]) { rememberRects(); uploads.remove(ids); }
function label(item: UploadItem) { return item.status === 'draft' && !missingMetadata(item.metadata, session.isAdmin).length ? '就绪' : statusLabels[item.status]; }
function resultLink(item: UploadItem) { return item.metadata.kind === 'emoji' ? '/emoji' : `/gallery${item.metadata.pid ? `?pid=${item.metadata.pid}` : ''}`; }
async function activateTemp() {
  const token = ++tempGeneration; tempLoading.value = temp.value; tempError.value = '';
  const { activateFeature, suspendFeatures } = await import('../compat/bridge');
  if (token !== tempGeneration) return;
  suspendFeatures();
  if (!temp.value) return;
  try {
    await nextTick(); await activateFeature('upload', '', () => token === tempGeneration && temp.value);
    if (token !== tempGeneration || !temp.value) return;
    await window.auth.loadFeature('upload');
    if (token !== tempGeneration || !temp.value) return;
    document.getElementById('page-upload')?.classList.add('intake-temp-host');
    window.ui.switchTab('temp-upload');
  } catch (error) { if (token === tempGeneration) tempError.value = (error as Error).message; }
  finally { if (token === tempGeneration) tempLoading.value = false; }
}
watch(temp, () => { void activateTemp(); }, { immediate: true });
onMounted(() => { void uploads.configure(); window.addEventListener('paste', paste); });
onBeforeUnmount(() => { tempGeneration++; window.removeEventListener('paste', paste); window.upload?.suspendTemp(); document.getElementById('page-upload')?.classList.remove('intake-temp-host'); animations.forEach(animation => animation.cancel()); });
</script>
<template><section class="intake" :class="{ 'is-dragging': dragging, 'is-single': single, 'has-editor': editorOpen, 'is-temp': temp }" aria-label="上传工作台" @dragenter="dragEnter" @dragover.prevent @dragleave="dragLeave" @drop="drop" @keydown.esc="closeEditor">
  <template v-if="temp"><div v-if="tempLoading || tempError" class="intake-empty-message" role="status">{{ tempError || '正在读取待整理图片…' }}<button v-if="tempError" type="button" class="btn btn-secondary" @click="activateTemp">重试</button></div></template>
  <template v-else>
    <input ref="input" class="intake-file-input" type="file" multiple :accept="uploads.capabilities?.extensions.map(ext => `.${ext}`).join(',') || '.jpg,.jpeg,.png,.webp,.gif,.bmp'" aria-label="选择上传文件" @change="fileChange">
    <div class="intake-toolbar"><div class="intake-source"><div class="intake-segment" role="group" aria-label="新文件入库目标"><button type="button" :aria-pressed="uploads.defaults.kind === 'image'" @click="uploads.defaults.kind = 'image'"><AppIcon name="gallery"/>图片</button><button v-if="session.isAdmin" type="button" :aria-pressed="uploads.defaults.kind === 'emoji'" @click="uploads.defaults.kind = 'emoji'"><AppIcon name="emoji"/>表情</button></div><span v-if="uploads.items.length" class="intake-total">{{ uploads.items.length }} 张 <i>·</i> {{ formatBytes(totalSize) }}</span><small v-else class="intake-decoration" aria-hidden="true">RESOURCE INTAKE</small></div><div class="intake-toolbar-actions"><button v-if="undo.length" type="button" class="btn btn-secondary" @click="undoPatch">撤销编辑</button><button v-if="uploads.items.length" type="button" class="btn btn-secondary" @click="input?.click()"><AppIcon name="upload"/>继续添加</button></div></div>
    <div v-if="uploads.capabilityError" class="intake-warning" role="alert">{{ uploads.capabilityError }}<button type="button" @click="uploads.configure">重试</button></div>
    <div v-if="catalogError" class="intake-warning" role="alert">标签暂时无法加载<button type="button" @click="groups.refetch(); characters.refetch(); features.refetch(); emotions.refetch()">重试</button></div>
    <div v-if="uploads.restored.length" class="intake-restore" role="status">有 {{ uploads.restored.length }} 份信息草稿，重新选择原文件即可恢复。<button type="button" @click="uploads.discardDrafts">忽略草稿</button></div>
    <button v-if="!uploads.items.length" type="button" class="intake-dropzone" @click="input?.click()"><span class="intake-drop-orbit" aria-hidden="true"><AppIcon name="upload"/></span><strong>{{ uploads.adding ? '正在读取图片…' : '拖入图片，或选择文件' }}</strong><span>支持单张、多张，也可粘贴图片</span><small v-if="uploads.capabilities">{{ uploads.capabilities.extensions.map(ext => ext.toUpperCase()).join(' / ') }}<i>·</i>单张不超过 {{ formatBytes(uploads.capabilities.max_file_size) }}</small><span class="intake-drop-coordinate" aria-hidden="true">01 / ADD TO YOUR COLLECTION <b>＋</b></span></button>
    <template v-else>
      <div class="intake-list-toolbar"><div class="intake-status-tabs" role="group" aria-label="上传状态筛选"><button v-for="option in filterOptions.filter(option => option.key === 'all' || option.count)" :key="option.key" type="button" :aria-pressed="filter === option.key" @click="filter = option.key">{{ option.name }}<span>{{ option.count }}</span></button></div><label class="intake-search"><AppIcon name="search"/><input v-model="search" type="search" aria-label="查找上传文件" placeholder="查找文件名"></label></div>
      <div v-if="!single" class="intake-selection-bar"><button type="button" @click="all">{{ shown.filter(editable).length && shown.filter(editable).every(item => selected.includes(item.id)) ? '取消全选' : '选择可编辑项' }}</button><span v-if="selected.length">已选 {{ selected.length }} 张<button type="button" @click="selected = []">取消</button></span><button v-if="selected.length" type="button" @click="remove(selected)">移除所选</button><button v-if="completed.length" type="button" @click="remove(completed.map(item => item.id))">清理已完成</button></div>
      <div class="intake-workspace"><div class="intake-gallery-side"><div ref="cardArea" class="intake-cards" :class="{ 'is-single': single }">
        <article v-for="item in shown" :key="item.id" :data-upload-id="item.id" class="intake-card" :class="[{ 'is-current': focused === item.id, 'is-selected': selected.includes(item.id) }, `is-${item.status}`]">
          <button type="button" class="intake-card-image" :aria-label="`编辑 ${item.file.name}`" @click="select(item)"><img :src="item.url" :alt="item.file.name" :width="item.width" :height="item.height" decoding="async" loading="lazy"><span v-if="item.metadata.kind === 'emoji'" class="intake-kind-badge">表情</span></button>
          <label v-if="!single && editable(item)" class="intake-card-check"><input type="checkbox" :checked="selected.includes(item.id)" :aria-label="`选择 ${item.file.name}`" @change="toggle(item)"></label>
          <button v-if="!['queued','uploading','processing','attention','reviewing'].includes(item.status)" type="button" class="intake-card-remove" :aria-label="`移除 ${item.file.name}`" @click="remove([item.id])"><AppIcon name="close"/></button>
          <div class="intake-card-info"><div><strong :title="item.file.name">{{ item.file.name }}</strong><span class="intake-state" :data-state="item.status">{{ label(item) }}</span></div><span v-if="item.status === 'draft' && missingMetadata(item.metadata, session.isAdmin).length" class="intake-missing">补充{{ missingMetadata(item.metadata, session.isAdmin).join('、') }}</span><small v-else-if="item.message">{{ item.message }}</small><small v-else>{{ item.width }} × {{ item.height }}<i>·</i>{{ formatBytes(item.file.size) }}</small><progress v-if="['uploading','processing'].includes(item.status)" max="100" :value="item.progress" :aria-label="`${item.file.name} 上传进度`"></progress><div v-if="['attention','uncertain','success','failed'].includes(item.status)" class="intake-card-actions"><button v-if="item.status === 'attention'" type="button" :disabled="uploads.reviewing" @click="uploads.compare(item)">比对图片</button><button v-if="item.status === 'attention'" type="button" :disabled="uploads.reviewing" @click="uploads.cancelAttention(item)">放弃提交</button><RouterLink v-if="['success','uncertain'].includes(item.status)" :to="resultLink(item)">{{ item.status === 'uncertain' ? '前往核对' : '查看图库' }}</RouterLink><button v-if="item.status === 'uncertain'" type="button" @click="uploads.resumeUnknown(item)">已核对，重新准备</button><button v-if="item.status === 'failed'" type="button" @click="uploads.submit([item.id])">重试</button></div></div>
        </article>
      </div><div v-if="!shown.length" class="intake-empty-message">没有符合条件的文件<button type="button" @click="filter = 'all'; search = ''">显示全部</button></div><button type="button" class="intake-add-more" :disabled="uploads.adding" @click="input?.click()"><span aria-hidden="true">＋</span>{{ uploads.adding ? '正在读取图片…' : '继续添加图片' }}</button></div>
        <UploadEditor v-if="targets.length" v-show="editorOpen || single" :targets="targets" :groups="groups.data.value || []" :characters="characters.data.value || []" :features="features.data.value || []" :emotions="emotions.data.value || []" :admin="session.isAdmin" :disabled="editorDisabled" @patch="patch" @defaults="defaults" @close="closeEditor"/>
      </div>
      <footer class="intake-submit-bar"><div class="intake-submit-summary" aria-live="polite"><strong>{{ uploads.busy ? '正在处理上传任务' : `已就绪 ${uploads.ready.length} 张` }}</strong><button v-if="missing.length" type="button" @click="filter = 'missing'; select(missing[0]!)">{{ missing.length }} 张待补充</button><button v-if="attention.length" type="button" @click="filter = 'attention'">{{ attention.length }} 张待确认</button><span v-if="completed.length">{{ completed.length }} 张已完成</span></div><div class="intake-submit-actions"><button v-if="uploads.items.some(item => item.status === 'queued')" type="button" class="btn btn-secondary" @click="uploads.cancelQueued">取消排队</button><button type="button" class="btn btn-primary" :disabled="!submitIds.length || uploads.preparing || catalogError" @click="uploads.submit(submitIds)">{{ uploads.preparing ? '准备上传…' : `${session.isAdmin ? '提交' : '提交审核'} ${submitIds.length} 张` }}<AppIcon name="right"/></button></div></footer>
    </template>
    <div v-if="dragging" class="intake-drag-cover" aria-hidden="true"><AppIcon name="upload"/><strong>松开以添加图片</strong></div>
  </template>
</section></template>
