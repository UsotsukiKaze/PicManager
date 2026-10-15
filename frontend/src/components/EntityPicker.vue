<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onDeactivated, ref, shallowRef, watch } from 'vue';
import type { Entity } from '../api/types';
import { loadPinyin } from '../api/phonetics';
import AppIcon from './AppIcon.vue';
const props = withDefaults(defineProps<{ label: string; items: Entity[]; modelValue?: number; disabled?: boolean; allowClear?: boolean }>(), { allowClear: true });
const emit = defineEmits<{ 'update:modelValue': [value: number | undefined] }>();
const root = ref<HTMLElement>();
const field = ref<HTMLElement>();
const options = ref<HTMLElement>();
const input = ref('');
const open = ref(false);
const cursor = ref(0);
const position = ref({ left: '0px', top: '0px', width: '0px', maxHeight: '280px' });
const positioned = ref(false);
const upwards = ref(false);
const phonetics = shallowRef(new Map<number, string>());
let stopped = false;
let indexedItems: Entity[] | undefined;
let frame: number | undefined;
watch([input, () => props.items], async ([term, items]) => {
  if (!/[a-z]/i.test(term) || items === indexedItems) return;
  try {
    const { pinyin } = await loadPinyin();
    if (stopped || items !== props.items || items === indexedItems) return;
    indexedItems = items;
    phonetics.value = new Map(items.map(row => [row.id,
      `${pinyin(row.name, { toneType: 'none' })} ${pinyin(row.name, { pattern: 'first', toneType: 'none' })}`]));
  } catch { /* Names and aliases remain searchable if the optional dictionary is offline. */ }
});
const selected = computed(() => props.items.find(row => row.id === props.modelValue));
const search = computed(() => props.items.map(row => ({ row, text: [row.name, ...(row.aliases || []),
  ...(row.nicknames || []), phonetics.value.get(row.id) || ''].join(' ').toLowerCase().replace(/\s+/g, '') })));
const matches = computed(() => {
  const term = input.value.toLowerCase().replace(/\s+/g, '');
  return search.value.filter(item => !term || item.text.includes(term)).slice(0, 60).map(item => item.row);
});
const activeOption = computed(() => cursor.value === -1 ? `option-${props.label}-all` : matches.value[cursor.value] ? `option-${props.label}-${matches.value[cursor.value].id}` : undefined);
function placeOptions() {
  frame = undefined;
  if (!open.value || !field.value || !options.value) return;
  const rect = field.value.getBoundingClientRect();
  const viewport = window.visualViewport;
  const top = viewport?.offsetTop || 0;
  const bottom = top + (viewport?.height || innerHeight);
  const below = Math.max(0, bottom - rect.bottom - 18);
  const above = Math.max(0, rect.top - top - 18);
  const desired = Math.min(280, options.value.scrollHeight || 280);
  upwards.value = below < Math.min(desired, 180) && above > below;
  const maxHeight = Math.min(280, upwards.value ? above : below);
  const width = Math.min(rect.width, innerWidth - 24);
  position.value = {
    left: `${Math.max(12, Math.min(rect.left, innerWidth - width - 12))}px`, width: `${width}px`,
    top: `${upwards.value ? rect.top - 6 - Math.min(desired, maxHeight) : rect.bottom + 6}px`, maxHeight: `${maxHeight}px`,
  };
  positioned.value = true;
}
function schedulePosition() {
  if (frame === undefined) frame = requestAnimationFrame(placeOptions);
}
function closeOptions() { open.value = false; input.value = ''; }
function outside(event: PointerEvent) {
  const target = event.target as Node;
  if (!root.value?.contains(target) && !options.value?.contains(target)) closeOptions();
}
watch(open, async (shown, _old, cleanup) => {
  positioned.value = false;
  if (!shown) return;
  window.addEventListener('resize', schedulePosition);
  window.addEventListener('scroll', schedulePosition, true);
  window.visualViewport?.addEventListener('resize', schedulePosition);
  window.visualViewport?.addEventListener('scroll', schedulePosition);
  document.addEventListener('pointerdown', outside);
  const observer = typeof ResizeObserver === 'undefined' ? undefined : new ResizeObserver(schedulePosition);
  if (field.value) observer?.observe(field.value);
  cleanup(() => {
    observer?.disconnect();
    window.removeEventListener('resize', schedulePosition);
    window.removeEventListener('scroll', schedulePosition, true);
    window.visualViewport?.removeEventListener('resize', schedulePosition);
    window.visualViewport?.removeEventListener('scroll', schedulePosition);
    document.removeEventListener('pointerdown', outside);
    if (frame !== undefined) cancelAnimationFrame(frame);
    frame = undefined;
  });
  await nextTick(); placeOptions();
});
watch(matches, () => { cursor.value = 0; if (open.value) void nextTick().then(schedulePosition); });
watch(cursor, async () => {
  await nextTick();
  if (open.value && activeOption.value) document.getElementById(activeOption.value)?.scrollIntoView({ block: 'nearest' });
});
onDeactivated(closeOptions);
onBeforeUnmount(() => { stopped = true; });
function choose(id?: number) { emit('update:modelValue', id); closeOptions(); }
function keydown(event: KeyboardEvent) {
  if (event.isComposing) return;
  if (event.key === 'Escape' && open.value) { event.preventDefault(); event.stopPropagation(); closeOptions(); return; }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    if (!open.value) {
      open.value = true;
      cursor.value = event.key === 'ArrowDown' ? 0 : Math.max(props.allowClear === false ? 0 : -1, matches.value.length - 1);
    } else cursor.value = Math.max(props.allowClear === false ? 0 : -1, Math.min(matches.value.length - 1, cursor.value + (event.key === 'ArrowDown' ? 1 : -1)));
  }
  if (event.key === 'Enter' && open.value) {
    if (cursor.value === -1 || matches.value[cursor.value]) { event.preventDefault(); choose(matches.value[cursor.value]?.id); }
  }
}
function focusout(event: FocusEvent) {
  const target = event.relatedTarget as Node | null;
  if (!root.value?.contains(target) && !options.value?.contains(target)) closeOptions();
}
</script>
<template><div ref="root" class="modern-picker" @focusout="focusout">
  <label :for="`picker-${label}`">{{ label }}</label>
  <div ref="field" class="modern-picker-field">
    <input :id="`picker-${label}`" :value="open ? input : selected?.name || ''" :placeholder="open ? `搜索${label}` : `选择${label}`" :aria-label="`搜索${label}`" :disabled="disabled" role="combobox" :aria-expanded="open" :aria-controls="`options-${label}`" :aria-activedescendant="open ? activeOption : undefined" autocomplete="off" @input="input = ($event.target as HTMLInputElement).value" @focus="open = true" @keydown="keydown">
    <button v-if="modelValue !== undefined" type="button" :aria-label="`清除${label}`" @click="choose()"><AppIcon name="close"/></button>
    <svg v-else class="modern-picker-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>
  </div>
  <Teleport to="body"><div v-if="open" :id="`options-${label}`" ref="options" class="modern-picker-options" :class="{ 'opens-upwards': upwards }" :style="{ ...position, visibility: positioned ? 'visible' : 'hidden' }" role="listbox" :aria-label="label" @keydown="keydown">
    <button v-if="allowClear !== false" :id="`option-${label}-all`" type="button" role="option" tabindex="-1" :aria-selected="modelValue === undefined" :class="{ highlighted: cursor === -1 }" @mousedown.prevent @click="choose()"><span class="modern-picker-option-copy">全部{{ label }}</span><AppIcon v-if="modelValue === undefined" name="check"/></button>
    <button v-for="(item, index) in matches" :id="`option-${label}-${item.id}`" :key="item.id" type="button" role="option" tabindex="-1" :aria-selected="item.id === modelValue" :class="{ highlighted: cursor === index }" @mousedown.prevent @click="choose(item.id)"><span class="modern-picker-option-copy">{{ item.name }}<small v-if="item.group_name">{{ item.group_name }}</small></span><AppIcon v-if="item.id === modelValue" name="check"/></button>
    <p v-if="!matches.length">没有匹配项</p><small v-if="matches.length === 60">继续输入以缩小范围</small>
  </div></Teleport>
</div></template>
