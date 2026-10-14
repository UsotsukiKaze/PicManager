<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { useAppearance } from '../state/appearance';
const appearance = useAppearance();
const frame = ref<HTMLIFrameElement>();
let observer: ResizeObserver | undefined;
function syncAppearance() {
  const root = frame.value?.contentDocument?.documentElement;
  if (root) { root.dataset.theme = appearance.resolvedTheme; root.dataset.motion = appearance.reduced ? 'reduced' : 'full'; }
}
watch(() => [appearance.resolvedTheme, appearance.reduced], syncAppearance);
function loaded() {
  observer?.disconnect();
  const document = frame.value?.contentDocument;
  if (!document?.body) return;
  syncAppearance();
  const fit = () => {
    const height = Math.ceil(document.querySelector('.profile-container')?.getBoundingClientRect().height || 600);
    if (frame.value && Math.abs(frame.value.clientHeight - height) > 2) frame.value.style.height = `${height}px`;
  };
  observer = new ResizeObserver(fit);
  observer.observe(document.body);
  fit();
}
onBeforeUnmount(() => observer?.disconnect());
</script>
<template><section id="page-profile" class="modern-profile"><header class="modern-page-heading"><h1>我的</h1></header><iframe ref="frame" id="profile-frame" class="profile-frame" title="个人资料与用户控制台" src="/profile?embedded=1&amp;v=20261007c" @load="loaded"></iframe></section></template>
