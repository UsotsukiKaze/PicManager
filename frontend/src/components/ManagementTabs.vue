<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import AppIcon from './AppIcon.vue';
const route = useRoute();
const navigation = ref<HTMLElement>();
const indicator = ref({ left: 0, width: 0, height: 0 });
let observer: ResizeObserver | undefined;
function measure() {
  const node = navigation.value;
  const active = node?.querySelector<HTMLElement>('.router-link-active');
  if (!node || !active) return;
  indicator.value = { left: active.offsetLeft, width: active.offsetWidth, height: active.offsetHeight };
}
watch(() => route.path, async () => { await nextTick(); measure(); });
onMounted(() => {
  observer = new ResizeObserver(measure);
  if (navigation.value) {
    observer.observe(navigation.value);
    navigation.value.querySelectorAll('a').forEach(node => observer!.observe(node));
  }
  measure();
});
onBeforeUnmount(() => observer?.disconnect());
const tabs = [{ to: '/gallery', name: '图片', icon: 'gallery' }, { to: '/manage/groups', name: '分组', icon: 'groups' }, { to: '/manage/characters', name: '角色', icon: 'character' }, { to: '/manage/features', name: '特征标签', icon: 'tags' }];
</script>
<template><header class="modern-management-header"><h1>图片管理</h1><nav ref="navigation" class="modern-management-tabs" aria-label="图片管理分类">
  <span class="modern-tab-indicator" aria-hidden="true" :style="{ transform: `translateX(${indicator.left}px)`, width: `${indicator.width}px`, height: `${indicator.height}px`, opacity: indicator.width ? 1 : 0 }"></span>
  <RouterLink v-for="tab in tabs" :key="tab.to" :to="tab.to"><AppIcon :name="tab.icon"/>{{ tab.name }}</RouterLink>
</nav></header></template>
