<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue';
import { useAppearance, type Theme } from '../state/appearance';
import AppIcon from './AppIcon.vue';
const appearance = useAppearance();
const menu = ref<HTMLDetailsElement>();
const themes: Array<{ value: Theme; label: string }> = [{ value: 'light', label: '浅色' }, { value: 'dark', label: '深色' }, { value: 'system', label: '跟随系统' }];
function outside(event: PointerEvent) {
  if (menu.value?.open && !menu.value.contains(event.target as Node)) menu.value.open = false;
}
function close(event: KeyboardEvent) {
  if (event.key === 'Escape' && menu.value?.open) {
    menu.value.open = false;
    menu.value.querySelector('summary')?.focus();
    event.stopPropagation();
  }
}
onMounted(() => document.addEventListener('pointerdown', outside));
onBeforeUnmount(() => document.removeEventListener('pointerdown', outside));
</script>
<template><details ref="menu" class="modern-appearance" @keydown="close">
  <summary class="header-link" aria-label="界面外观" title="界面外观"><AppIcon name="palette"/><span>外观</span></summary>
  <div class="modern-appearance-panel">
    <span class="modern-eyebrow">APPEARANCE</span><strong>界面外观</strong>
    <div class="modern-theme-options" role="group" aria-label="配色模式"><button v-for="item in themes" :key="item.value" type="button" :aria-pressed="appearance.theme === item.value" @click="appearance.theme = item.value">{{ item.label }}</button></div>
    <label><input type="checkbox" v-model="appearance.reduced">减少动态效果</label>
  </div>
</details></template>
