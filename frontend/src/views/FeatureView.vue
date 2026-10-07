<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { activateFeature, suspendFeatures } from '../compat/bridge';
const route = useRoute();
const loading = ref(true);
const error = ref('');
let generation = 0;
async function activate() {
  const token = ++generation;
  loading.value = true;
  error.value = '';
  suspendFeatures();
  await nextTick();
  try { await activateFeature(String(route.meta.page), String(route.meta.tab || ''), () => generation === token); }
  catch (reason) { if (token === generation) error.value = (reason as Error).message; }
  finally { if (token === generation) loading.value = false; }
}
watch(() => route.fullPath, activate, { immediate: true });
onUnmounted(() => { generation++; suspendFeatures(); });
</script>
<template><div v-if="loading" class="modern-feature-status" role="status">正在加载…</div><div v-else-if="error" class="modern-feature-status" role="alert"><p>{{ error }}</p><button class="btn btn-secondary" @click="activate">重试</button></div></template>
