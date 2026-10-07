<script setup lang="ts">
import { computed } from 'vue';
import { useQuery } from '@tanstack/vue-query';
import { requestJSON, safeAvatar } from '../api/http';
import type { Entity, Rankings, SystemStatus } from '../api/types';
import { useSession } from '../state/session';
const session = useSession();
const { data: status, error: statusError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'status']), queryFn: ({ signal }) => requestJSON<SystemStatus>('/api/system/status', { signal }) });
const { data: rankings, error: rankingError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'rankings']), queryFn: ({ signal }) => requestJSON<Rankings>('/api/rankings?limit=5', { signal }) });
const { data: popular } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'popular']), queryFn: ({ signal }) => requestJSON<Entity[]>('/api/groups/popular?limit=5', { signal }) });
</script>
<template><section class="modern-home">
  <div class="home-hero"><div class="home-hero-copy"><div class="home-kicker">PicManager</div><h2>欢迎来到~ <span class="home-title-name">小 · 爱 · 图 · 库</span></h2>
    <div class="home-metrics" aria-label="图库统计"><article class="home-metric-card"><span class="home-metric-label">全部图片</span><strong>{{ status?.total_images ?? '—' }}</strong><span class="home-metric-caption">数据库总量</span></article><article class="home-metric-card"><span class="home-metric-label">表情包库</span><strong>{{ status?.total_emojis ?? '—' }}</strong><span class="home-metric-caption">独立收藏数量</span></article><article class="home-metric-card"><span class="home-metric-label">分组和角色</span><strong class="home-metric-pair">{{ status?.total_groups ?? '—' }} / {{ status?.total_characters ?? '—' }}</strong><span class="home-metric-caption">检索维度</span></article></div>
    <p v-if="statusError" role="alert">统计暂时无法加载</p>
  </div><div class="modern-popular"><img src="/favicon.ico" width="64" height="64" alt=""><RouterLink v-for="group in popular" :key="group.id" :to="{ path: '/gallery', query: { group_id: group.id } }">{{ group.name }}</RouterLink></div></div>
  <section class="home-rankings" aria-label="图库排行榜"><article class="home-ranking-card"><div class="home-ranking-head"><div><span>ALL TIME</span><h3>总贡献度排行</h3></div><span class="home-ranking-badge">TOP 5</span></div><div class="modern-ranking-list"><div v-for="(item, index) in rankings?.contribution" :key="index" class="modern-ranking-row"><span>{{ index + 1 }}</span><img :src="safeAvatar(item.avatar_url)" width="32" height="32" alt="" loading="lazy"><strong>{{ item.nickname || item.qq_number }}</strong><small>{{ item.count ?? item.contribution_count ?? item.score ?? 0 }}</small></div><p v-if="!rankings?.contribution.length">{{ rankingError ? '排行暂时无法加载' : rankings ? '暂无贡献记录' : '正在加载…' }}</p></div></article>
  <article class="home-ranking-card"><div class="home-ranking-head"><div><span>LAST {{ rankings?.recent_days || 30 }} DAYS</span><h3>近期上传分组排行</h3></div><span class="home-ranking-badge">新增图片</span></div><div class="modern-ranking-list"><div v-for="(item, index) in rankings?.recent_groups" :key="index" class="modern-ranking-row"><span>{{ index + 1 }}</span><img :src="safeAvatar(item.avatar_url)" width="32" height="32" alt="" loading="lazy"><strong>{{ item.name || item.group_name }}</strong><small>{{ item.count ?? 0 }}</small></div><p v-if="!rankings?.recent_groups.length">{{ rankingError ? '排行暂时无法加载' : rankings ? '暂无上传记录' : '正在加载…' }}</p></div></article></section>
  <a class="home-personal-portal" href="https://usotsuki-kaze.com/" target="_blank" rel="noopener noreferrer"><span class="home-portal-mark"><img src="https://usotsuki-kaze.com/favicon.ico" alt="" loading="lazy"></span><span class="home-portal-copy"><small>PERSONAL SPACE · 时刻保持质疑</small><strong>前往 UsotsukiKaze 的个人主页</strong><span>拈风的个人中转站，集中放置正在维护的项目与公开资料。</span></span><span class="home-portal-arrow">↗</span></a>
</section></template>
