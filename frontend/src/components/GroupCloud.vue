<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import type { Entity } from '../api/types';
import { layoutWordCloud } from '../ui/wordCloud';

const props = defineProps<{ groups?: Entity[]; failed?: boolean }>();
const canvas = ref<HTMLElement>();
const bounds = ref({ width: 0, height: 0 });
let observer: ResizeObserver | undefined;
let frame = 0;
let measure: CanvasRenderingContext2D | null = null;
const words = computed(() => {
  if (!bounds.value.width || !measure) return [];
  return layoutWordCloud(props.groups || [], bounds.value, (name, size) => {
    measure!.font = `600 ${size}px "Segoe UI", "Microsoft YaHei", sans-serif`;
    return measure!.measureText(name).width;
  });
});
onMounted(() => {
  measure = document.createElement('canvas').getContext('2d');
  observer = new ResizeObserver(entries => {
    const { width, height } = entries[0]!.contentRect;
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => { bounds.value = { width, height }; });
  });
  if (canvas.value) observer.observe(canvas.value);
});
onBeforeUnmount(() => { observer?.disconnect(); cancelAnimationFrame(frame); });
</script>

<template>
  <aside class="home-group-cloud" aria-label="分组云图">
    <header><span>分组词云</span><RouterLink to="/manage/groups">全部分组 ↗</RouterLink></header>
    <div ref="canvas" class="group-cloud-canvas">
      <RouterLink v-for="(word, index) in words" :key="word.id" class="group-cloud-word"
        :to="{ path: '/gallery', query: { group_id: word.id } }"
        :title="`${word.name} · ${word.image_count || 0} 张`"
        :aria-label="`${word.name} · ${word.image_count || 0} 张`"
        :style="{ left: `${word.x}px`, top: `${word.y}px`, width: `${word.width}px`, height: `${word.height}px`, fontSize: `${word.size}px`, '--word-order': index, '--word-color': ['#3275b9', '#52939a', '#6775b5', '#4c7e88', '#7297b6', '#70878d', '#8197b5', '#68968d'][index % 8] }">
        <span class="group-cloud-label">{{ word.name }}</span>
      </RouterLink>
      <span v-if="!groups" class="group-cloud-status">{{ failed ? '分组暂时无法加载' : '正在加载分组…' }}</span>
      <RouterLink v-else-if="!groups.length" class="group-cloud-status" to="/manage/groups">添加第一个分组</RouterLink>
    </div>
  </aside>
</template>
