<script setup lang="ts">
import { computed } from 'vue';
import EntityPicker from './EntityPicker.vue';
import type { Entity } from '../api/types';
const props = defineProps<{ label: string; items: Entity[]; modelValue: number[]; disabled?: boolean; required?: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [value: number[]] }>();
const available = computed(() => props.items.filter(item => !props.modelValue.includes(item.id)));
function add(value?: number) { if (value !== undefined) emit('update:modelValue', [...props.modelValue, value]); }
</script>
<template><div class="intake-tags" :data-required="required">
  <EntityPicker :label="label" :items="available" :disabled="disabled" :allow-clear="false" @update:model-value="add"/>
  <div v-if="modelValue.length" class="intake-chips"><button v-for="id in modelValue" :key="id" type="button" :disabled="disabled" :aria-label="`移除${label} ${items.find(item => item.id === id)?.name || id}`" @click="emit('update:modelValue', modelValue.filter(value => value !== id))">{{ items.find(item => item.id === id)?.name || `#${id}` }}<span aria-hidden="true">×</span></button></div>
</div></template>
