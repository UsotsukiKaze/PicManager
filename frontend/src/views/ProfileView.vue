<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue';
const frame = ref<HTMLIFrameElement>();
let observer: ResizeObserver | undefined;
function loaded() {
  observer?.disconnect();
  const document = frame.value?.contentDocument;
  if (!document?.body) return;
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
