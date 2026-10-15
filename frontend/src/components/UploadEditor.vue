<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue';
import type { Entity } from '../api/types';
import { cloneMetadata, defaultMetadata, formatBytes, type UploadItem, type UploadMetadata, type TagOperation } from '../ui/uploadModel';
import UploadTags from './UploadTags.vue';
import AppIcon from './AppIcon.vue';
import { reducedMotion } from '../state/appearance';
const props = defineProps<{ targets: UploadItem[]; groups: Entity[]; characters: Entity[]; features: Entity[]; emotions: Entity[]; admin: boolean; disabled: boolean }>();
const emit = defineEmits<{ patch: [patch: Partial<UploadMetadata>, operation: TagOperation]; defaults: [value: UploadMetadata]; close: [] }>();
const draft = reactive(defaultMetadata()), touched = ref(new Set<keyof UploadMetadata>()), operation = ref<TagOperation>('append');
const more = ref<HTMLDetailsElement>(), panel = ref<HTMLElement>();
const batch = computed(() => props.targets.length > 1), first = computed(() => props.targets[0]);
const mixed = computed(() => {
  const values = new Set<keyof UploadMetadata>();
  for (const key of Object.keys(draft) as Array<keyof UploadMetadata>) if (props.targets.some(item => JSON.stringify(item.metadata[key]) !== JSON.stringify(first.value?.metadata[key]))) values.add(key);
  return values;
});
watch(() => props.targets.map(item => item.id).join(','), () => {
  Object.assign(draft, first.value ? cloneMetadata(first.value.metadata) : defaultMetadata());
  if (batch.value) Object.assign(draft, defaultMetadata(first.value?.metadata.kind));
  touched.value = new Set(); operation.value = 'append';
  more.value?.removeAttribute('open');
}, { immediate: true });
function write<K extends keyof UploadMetadata>(key: K, value: UploadMetadata[K]) {
  draft[key] = value; touched.value = new Set([...touched.value, key]);
  if (key === 'character_ids') {
    const ids = (value as number[]).map(id => props.characters.find(item => item.id === id)?.group_id).filter((id): id is number => !!id);
    if (ids.length && (!batch.value || operation.value !== 'remove')) { draft.group_ids = [...new Set([...draft.group_ids, ...ids])]; touched.value.add('group_ids'); }
  }
  if (!batch.value) apply();
}
function apply() {
  const patch = Object.fromEntries([...touched.value].map(key => [key, draft[key]])) as Partial<UploadMetadata>;
  emit('patch', patch, batch.value ? operation.value : 'replace');
  touched.value = new Set();
  if (batch.value) void nextTick(() => panel.value?.scrollTo({ top: 0, behavior: reducedMotion() ? 'instant' : 'smooth' }));
}
const emotions = computed(() => props.emotions.filter(item => !item.name.startsWith('#')));
const functions = computed(() => props.emotions.filter(item => item.name.startsWith('#')));
function setEmotion(ids: number[], functional: boolean) {
  const retained = draft.emotion_ids.filter(id => props.emotions.find(item => item.id === id)?.name.startsWith('#') !== functional);
  write('emotion_ids', [...retained, ...ids]);
}
</script>
<template><aside ref="panel" class="intake-editor" aria-label="编辑上传信息">
  <header class="intake-editor-heading"><div><small>{{ batch ? 'BATCH EDIT' : 'RESOURCE DETAILS' }}</small><h2>{{ batch ? `已选 ${targets.length} 张` : '编辑信息' }}</h2></div><button type="button" class="intake-editor-close btn btn-secondary" aria-label="关闭信息面板" @click="emit('close')"><AppIcon name="close"/></button></header>
  <template v-if="first">
    <div v-if="!batch" class="intake-file-spec"><strong :title="first.file.name">{{ first.file.name }}</strong><span>{{ first.width }} × {{ first.height }}<i>·</i>{{ formatBytes(first.file.size) }}</span></div>
    <p v-if="disabled" class="intake-editor-hint">已提交的任务信息已锁定，可继续添加其他图片。</p>
    <template v-else>
      <div v-if="batch" class="intake-batch-mode"><label for="intake-tag-operation">标签操作</label><select id="intake-tag-operation" v-model="operation"><option value="append">追加标签</option><option value="replace">替换标签</option><option value="remove">移除标签</option></select><p>只修改本次调整的字段{{ mixed.size ? '，不同内容保留为多个值。' : '。' }}</p></div>
      <div class="intake-field"><label>入库类型 <small v-if="batch && mixed.has('kind') && !touched.has('kind')">多个值</small></label><div class="intake-segment" role="group" aria-label="入库类型"><button type="button" :aria-pressed="(!batch || touched.has('kind') || !mixed.has('kind')) && draft.kind === 'image'" @click="write('kind', 'image')">图片</button><button type="button" :disabled="!admin" :title="!admin ? '表情包上传需要管理员权限' : undefined" :aria-pressed="(!batch || touched.has('kind') || !mixed.has('kind')) && draft.kind === 'emoji'" @click="write('kind', 'emoji')">表情</button></div></div>
      <div class="intake-field"><UploadTags :required="draft.kind === 'image'" label="分组" :items="groups" :model-value="draft.group_ids" @update:model-value="write('group_ids', $event)"/><small v-if="batch && mixed.has('group_ids')">多个值</small><button v-if="batch" type="button" class="intake-clear-field" @click="operation = 'replace'; write('group_ids', [])">清空所选分组</button></div>
      <div class="intake-field"><UploadTags :required="draft.kind === 'image'" label="角色" :items="characters" :model-value="draft.character_ids" @update:model-value="write('character_ids', $event)"/><small v-if="batch && mixed.has('character_ids')">多个值</small><button v-if="batch" type="button" class="intake-clear-field" @click="operation = 'replace'; write('character_ids', [])">清空所选角色</button></div>
      <template v-if="draft.kind === 'image'">
        <UploadTags label="特征" :items="features" :model-value="draft.feature_tag_ids" @update:model-value="write('feature_tag_ids', $event)"/>
        <div class="intake-field"><label>年龄分级 <small v-if="batch && mixed.has('age_rating') && !touched.has('age_rating')">多个值</small></label><div class="intake-segment intake-rating" role="group" aria-label="年龄分级"><button v-for="rating in (['all', 'r12', 'r16', 'r18'] as const)" :key="rating" type="button" :aria-pressed="(!batch || touched.has('age_rating') || !mixed.has('age_rating')) && draft.age_rating === rating" @click="write('age_rating', rating)">{{ rating === 'all' ? '全年龄' : rating.toUpperCase() }}</button></div><small v-if="!batch">请按图片内容确认分级</small></div>
      </template>
      <template v-else><UploadTags label="情绪" :items="emotions" :model-value="draft.emotion_ids.filter(id => emotions.some(item => item.id === id))" @update:model-value="setEmotion($event, false)"/><UploadTags label="功能" :items="functions" :model-value="draft.emotion_ids.filter(id => functions.some(item => item.id === id))" @update:model-value="setEmotion($event, true)"/></template>
      <details ref="more" class="intake-more"><summary>更多信息 <span v-if="draft.pid || draft.description">已填写</span></summary><label v-if="draft.kind === 'image'" for="intake-pid">PID <small v-if="first.pidInferred && !batch">从文件名提取</small></label><input v-if="draft.kind === 'image'" id="intake-pid" :value="draft.pid" inputmode="numeric" :placeholder="batch && mixed.has('pid') ? '多个值，输入后统一修改' : '可不填'" @input="write('pid', ($event.target as HTMLInputElement).value)"><label for="intake-description">备注</label><textarea id="intake-description" :value="draft.description" :placeholder="batch && mixed.has('description') ? '多个值，输入后统一修改' : '可不填'" rows="3" @input="write('description', ($event.target as HTMLTextAreaElement).value)"></textarea><button v-if="batch" type="button" class="intake-clear-field" @click="write('description', '')">清空所选备注</button></details>
      <button v-if="batch" type="button" class="btn btn-primary intake-apply" :disabled="!touched.size" @click="apply">应用到 {{ targets.length }} 张</button>
      <button v-else type="button" class="intake-default-button" @click="emit('defaults', cloneMetadata(draft))">后续文件沿用这组标签与分级</button>
    </template>
  </template><p v-else class="intake-editor-hint">选择图片后编辑信息</p>
</aside></template>
