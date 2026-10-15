<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import { useAppearance } from '../state/appearance';
import { createAccountMotion, type AccountMotionApi } from '../ui/accountMotion';
const appearance = useAppearance();
const frame = ref<HTMLIFrameElement>();
let observer: ResizeObserver | undefined;
let motion: AccountMotionApi | undefined;
const ready = ref(false);
function syncAppearance() {
  const root = frame.value?.contentDocument?.documentElement;
  if (root) { root.dataset.theme = appearance.resolvedTheme; root.dataset.motion = appearance.reduced ? 'reduced' : 'full'; }
}
watch(() => [appearance.resolvedTheme, appearance.reduced], syncAppearance);
function loaded() {
  observer?.disconnect();
  motion?.dispose(); ready.value = false;
  const document = frame.value?.contentDocument;
  if (!document?.body) return;
  syncAppearance();
  const fit = () => {
    const height = Math.ceil(document.querySelector('.profile-container')?.getBoundingClientRect().height || 600);
    if (frame.value && Math.abs(frame.value.clientHeight - height) > 2) frame.value.style.height = `${height}px`;
  };
  observer = new ResizeObserver(fit);
  observer.observe(document.body);
  motion = createAccountMotion(document.querySelector<HTMLElement>('.profile-container') || document.body, 'profile', () => { ready.value = true; requestAnimationFrame(fit); });
  fit();
}
onBeforeUnmount(() => { observer?.disconnect(); motion?.dispose(); });
onBeforeRouteLeave(() => { observer?.disconnect(); motion?.dispose(); });
</script>
<template><section id="page-profile" class="modern-profile" :class="{ 'is-loading': !ready }" :aria-busy="!ready"><div v-if="!ready" class="profile-loading" role="status" aria-label="正在加载个人资料"><div></div><div></div><div></div></div><iframe ref="frame" id="profile-frame" class="profile-frame" title="个人资料与用户控制台" src="/profile?embedded=1&amp;v=20261015-account-motion" @load="loaded"></iframe></section></template>
