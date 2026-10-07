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
<template><div class="modern-feature-status" :hidden="!loading && !error"><span v-if="loading" role="status">正在加载…</span><div v-else-if="error" role="alert"><p>{{ error }}</p><button class="btn btn-secondary" @click="activate">重试</button></div></div></template>
