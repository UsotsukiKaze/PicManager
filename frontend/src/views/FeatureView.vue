<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRoute } from 'vue-router';
import { activateFeature, suspendFeatures } from '../compat/bridge';
import { createAccountMotion, type AccountMotionApi } from '../ui/accountMotion';
const route = useRoute();
const loading = ref(true);
const error = ref('');
let generation = 0;
let motion: AccountMotionApi | undefined;
async function activate() {
  if (!route.meta.legacy) return;
  const token = ++generation;
  motion?.dispose(); motion = undefined;
  loading.value = true;
  error.value = '';
  suspendFeatures();
  await nextTick();
  try {
    await activateFeature(String(route.meta.page), String(route.meta.tab || ''), () => generation === token);
    if (token === generation && route.meta.page === 'settings') {
      const root = document.getElementById('page-settings');
      if (root) motion = createAccountMotion(root, 'settings');
    }
  }
  catch (reason) { if (token === generation) error.value = (reason as Error).message; }
  finally { if (token === generation) loading.value = false; }
}
watch(() => route.fullPath, activate, { immediate: true });
onBeforeRouteLeave(() => { generation++; motion?.dispose(); motion = undefined; });
onUnmounted(() => { generation++; motion?.dispose(); suspendFeatures(); });
</script>
<template><div class="modern-feature-status" :class="{ 'is-pol': route.meta.page === 'pixiv-ol' }" :hidden="!loading && !error"><span v-if="loading" role="status">正在加载…</span><div v-else-if="error" role="alert"><p>{{ error }}</p><button class="btn btn-secondary" @click="activate">重试</button></div></div></template>
