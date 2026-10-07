<script setup lang="ts">
import { computed, ref } from 'vue';
import type { ImageCardRecord } from '../api/types';
import { safeAvatar } from '../api/http';
const props = defineProps<{ image: ImageCardRecord; suppressActions?: boolean }>();
const emit = defineEmits<{ open: [image: ImageCardRecord, origin: HTMLElement]; edit: [id: string]; resume: [] }>();
const revealed = ref(false);
const broken = ref(false);
const restricted = computed(() => ['r16', 'r18'].includes(props.image.age_rating));
const character = computed(() => props.image.characters[0]);
function open(event: MouseEvent) { emit('open', props.image, event.currentTarget as HTMLElement); (event.currentTarget as HTMLElement).blur(); }
</script>
<template><article class="modern-image-card" :class="{ restricted: restricted && !revealed, 'suppress-actions': suppressActions }" @pointerleave="emit('resume')" @keydown="emit('resume')">
  <button class="modern-image-open" type="button" :aria-label="`查看图片 ${image.pid || image.image_id}`" @click="open">
    <img v-if="!broken" :src="!restricted || revealed ? `/resource/thumbs/${image.image_id}.webp` : undefined" alt="" loading="lazy" decoding="async" width="320" height="400" @error="broken = true">
    <span v-else class="modern-image-placeholder">预览暂未生成</span>
  </button>
  <button v-if="restricted && !revealed" class="modern-reveal" type="button" @click="revealed = true">{{ image.age_rating.toUpperCase() }} · 点击显示</button>
  <span v-else-if="restricted" class="modern-rating">{{ image.age_rating.toUpperCase() }}</span>
  <div class="modern-card-footer">
    <div class="modern-card-identity"><img :src="safeAvatar(character?.avatar_url || image.artist?.avatar_url)" width="28" height="28" alt="" loading="lazy" decoding="async" @error="($event.target as HTMLImageElement).src = '/favicon.ico'"><div><strong>{{ image.characters.map(row => row.name).join('、') || image.artist?.name || '未设置角色' }}</strong><small>{{ image.groups.map(row => row.name).join(' · ') || character?.group_name || '未分组' }}</small></div></div>
    <div class="modern-card-actions"><button type="button" @click="emit('open', image, $event.currentTarget as HTMLElement); ($event.currentTarget as HTMLElement).blur()">查看详情</button><button type="button" @click="emit('edit', image.image_id); ($event.currentTarget as HTMLElement).blur()">编辑</button></div>
  </div>
</article></template>
