<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { safeAvatar } from '../api/http';
const props = defineProps<{ name?: string; src?: string }>();
const failed = ref(false);
const loaded = ref(false);
const source = computed(() => {
  const url = safeAvatar(props.src);
  return new URL(url, window.location.origin).pathname === '/static/icon/Pic.png' ? '' : url;
});
const initial = computed(() => Array.from(props.name?.trim() || '?')[0]);
watch(source, () => { failed.value = false; loaded.value = false; });
</script>

<template><span class="entity-avatar" :title="name" aria-hidden="true">
  <span v-if="!loaded || failed" class="entity-avatar-initial">{{ initial }}</span>
  <img v-if="source && !failed" :src="source" alt="" loading="lazy" decoding="async" :class="{ loaded }" @load="loaded = true" @error="failed = true">
</span></template>

<style scoped>
.entity-avatar { position:relative; display:inline-grid; place-items:center; flex:none; width:34px; height:34px; overflow:hidden; border-radius:50%; background:var(--primary-soft); color:var(--primary-color); vertical-align:middle; }
.entity-avatar-initial { font-size:14px; line-height:1; font-weight:650; }
.entity-avatar img { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; opacity:0; }
.entity-avatar img.loaded { opacity:1; }
[data-theme="dark"] .entity-avatar { background:var(--primary-soft); color:var(--primary-color); }
</style>
