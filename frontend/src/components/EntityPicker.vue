<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import type { Entity } from '../api/types';
import { loadPinyin } from '../api/phonetics';
const props = defineProps<{ label: string; items: Entity[]; modelValue?: number; disabled?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: number | undefined] }>();
const input = ref('');
const open = ref(false);
const cursor = ref(0);
const phonetics = shallowRef(new Map<number, string>());
let stopped = false;
let indexedItems: Entity[] | undefined;
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
onBeforeUnmount(() => { stopped = true; });
const selected = computed(() => props.items.find(row => row.id === props.modelValue));
const search = computed(() => props.items.map(row => ({ row, text: [row.name, ...(row.aliases || []),
  ...(row.nicknames || []), phonetics.value.get(row.id) || ''].join(' ').toLowerCase().replace(/\s+/g, '') })));
const matches = computed(() => {
  const term = input.value.toLowerCase().replace(/\s+/g, '');
  return search.value.filter(item => !term || item.text.includes(term)).slice(0, 60).map(item => item.row);
});
watch(input, () => { cursor.value = 0; });
function choose(id?: number) { emit('update:modelValue', id); input.value = ''; open.value = false; }
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { open.value = false; return; }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault(); open.value = true;
    cursor.value = Math.max(0, Math.min(matches.value.length - 1, cursor.value + (event.key === 'ArrowDown' ? 1 : -1)));
  }
  if (event.key === 'Enter' && open.value && matches.value[cursor.value]) { event.preventDefault(); choose(matches.value[cursor.value].id); }
}
</script>
<template><div class="modern-picker" @focusout="(event: FocusEvent) => { if (!(event.currentTarget as HTMLElement).contains(event.relatedTarget as Node)) open = false; }">
  <label :for="`picker-${label}`">{{ label }}</label>
  <div class="modern-picker-field"><input :id="`picker-${label}`" v-model="input" :placeholder="selected?.name || `选择${label}`" :aria-label="`搜索${label}`" :disabled="disabled" role="combobox" :aria-expanded="open" :aria-controls="`options-${label}`" :aria-activedescendant="open && matches[cursor] ? `option-${label}-${matches[cursor].id}` : undefined" autocomplete="off" @focus="open = true" @keydown="keydown"><button v-if="modelValue !== undefined" type="button" :aria-label="`清除${label}`" @click="choose()">×</button></div>
  <div v-if="open" :id="`options-${label}`" class="modern-picker-options" role="listbox" :aria-label="label">
    <button type="button" role="option" :aria-selected="modelValue === undefined" @mousedown.prevent @click="choose()">全部{{ label }}</button>
    <button v-for="(item, index) in matches" :id="`option-${label}-${item.id}`" :key="item.id" type="button" role="option" :aria-selected="item.id === modelValue" :class="{ highlighted: cursor === index }" @mousedown.prevent @click="choose(item.id)">{{ item.name }}<small v-if="item.group_name">{{ item.group_name }}</small></button>
    <p v-if="!matches.length">没有匹配项</p><small v-if="matches.length === 60">继续输入以缩小范围</small>
  </div>
</div></template>
