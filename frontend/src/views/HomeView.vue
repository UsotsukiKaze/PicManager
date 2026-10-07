<script setup lang="ts">
import { computed } from 'vue';
import { useQuery } from '@tanstack/vue-query';
import { requestJSON, safeAvatar } from '../api/http';
import type { Entity, Ranking, Rankings, SystemStatus } from '../api/types';
import { useSession } from '../state/session';
import '../styles/home.css';

const session = useSession();
const { data: status } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'status']), queryFn: ({ signal }) => requestJSON<SystemStatus>('/api/system/status', { signal }) });
const { data: rankings, error: rankingError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'rankings']), queryFn: ({ signal }) => requestJSON<Rankings>('/api/rankings?limit=5', { signal }) });
const { data: popular, error: popularError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'popular']), queryFn: ({ signal }) => requestJSON<Entity[]>('/api/groups/popular?limit=5', { signal }) });
const numbers = new Intl.NumberFormat('zh-CN');
const count = (value?: number) => value == null ? '—' : numbers.format(value);
const rankCount = (item: Ranking) => item.score ?? item.contribution_count ?? item.count ?? 0;
const chipClasses = ['chip-one', 'chip-two', 'chip-three', 'chip-four', 'chip-five'];
const avatarFallback = (event: Event) => { (event.target as HTMLImageElement).src = '/static/icon/Pic.png'; };
</script>

<template>
  <section class="modern-home">
    <section class="home-hero">
      <div class="home-hero-copy">
        <div class="home-kicker">PicManager</div>
        <h2>欢迎来到~ <span class="home-title-name">小 · 爱 · 图 · 库</span></h2>
        <div class="home-metrics" aria-label="图库统计">
          <article class="home-metric-card home-metric-images">
            <div class="home-metric-top">
              <span class="home-metric-index">01</span>
              <span class="home-metric-label">全部图片</span>
            </div>
            <strong>{{ count(status?.total_images) }}</strong>
            <span class="home-metric-caption">数据库总量</span>
          </article>
          <article class="home-metric-card home-metric-emojis">
            <div class="home-metric-top">
              <span class="home-metric-index">02</span>
              <span class="home-metric-label">表情包库</span>
            </div>
            <strong>{{ count(status?.total_emojis) }}</strong>
            <span class="home-metric-caption">独立收藏数量</span>
          </article>
          <article class="home-metric-card home-metric-dimensions">
            <div class="home-metric-top">
              <span class="home-metric-index">03</span>
              <span class="home-metric-label">分组和角色</span>
            </div>
            <strong class="home-metric-pair"><span>{{ count(status?.total_groups) }}</span><span class="home-metric-separator">/</span><span>{{ count(status?.total_characters) }}</span></strong>
            <span class="home-metric-caption">检索维度</span>
          </article>
        </div>
      </div>
      <aside class="home-orbit" aria-label="分组云图">
        <div class="home-orbit-core">
          <img src="/static/icon/Pic.png" alt="">
        </div>
        <RouterLink v-for="(group, index) in (popular || []).slice(0, 5)" :key="group.id" class="orbit-chip" :class="chipClasses[index]" :to="{ path: '/gallery', query: { group_id: group.id } }" :title="`${group.name} · ${count(group.image_count)} 张`">
          <img class="orbit-chip-avatar" :src="safeAvatar(group.avatar_url)" alt="" decoding="async" @error="avatarFallback">
          <span class="orbit-chip-label">{{ group.name }} · {{ count(group.image_count) }}张</span>
        </RouterLink>
        <span v-if="!popular" class="orbit-chip chip-one" role="status">{{ popularError ? '分组暂时无法加载' : '加载分组...' }}</span>
        <RouterLink v-else-if="!popular.length" class="orbit-chip chip-one" to="/manage/groups">添加第一个分组</RouterLink>
      </aside>
    </section>

    <section class="home-rankings" aria-label="图库排行榜">
      <article class="home-ranking-card">
        <div class="home-ranking-head">
          <div>
            <span>ALL TIME</span>
            <h3>总贡献度排行</h3>
          </div>
          <span class="home-ranking-badge">TOP 5</span>
        </div>
        <div class="home-ranking-list">
          <div v-for="(item, index) in rankings?.contribution || []" :key="index" class="home-ranking-row">
            <span class="home-ranking-position">{{ index + 1 }}</span>
            <img class="home-ranking-avatar" :src="safeAvatar(item.avatar_url)" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @error="avatarFallback">
            <span class="home-ranking-name" :title="item.nickname || item.qq_number">{{ item.nickname || item.qq_number || '—' }}</span>
            <strong>{{ count(rankCount(item)) }}<small>贡献</small></strong>
          </div>
          <div v-if="!rankings?.contribution.length" class="home-ranking-empty" role="status">{{ rankingError ? '排行暂时无法加载' : !rankings ? '正在载入贡献记录…' : '还没有贡献记录' }}</div>
        </div>
      </article>
      <article class="home-ranking-card">
        <div class="home-ranking-head">
          <div>
            <span>LAST 30 DAYS</span>
            <h3>近期上传分组排行</h3>
          </div>
          <span class="home-ranking-badge">新增图片</span>
        </div>
        <div class="home-ranking-list">
          <div v-for="(item, index) in rankings?.recent_groups || []" :key="index" class="home-ranking-row">
            <span class="home-ranking-position">{{ index + 1 }}</span>
            <img class="home-ranking-avatar" :src="safeAvatar(item.avatar_url)" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @error="avatarFallback">
            <span class="home-ranking-name" :title="item.name || item.group_name">{{ item.name || item.group_name || '—' }}</span>
            <strong>{{ count(rankCount(item)) }}<small>张</small></strong>
          </div>
          <div v-if="!rankings?.recent_groups.length" class="home-ranking-empty" role="status">{{ rankingError ? '排行暂时无法加载' : !rankings ? '正在统计近期上传…' : `近 ${rankings?.recent_days || 30} 天还没有新上传图片` }}</div>
        </div>
      </article>
    </section>

    <a class="home-personal-portal" href="https://usotsuki-kaze.com/" target="_blank" rel="noopener noreferrer">
      <span class="home-portal-mark" aria-hidden="true">
        <img src="https://usotsuki-kaze.com/favicon.ico" @error="avatarFallback" alt="">
      </span>
      <span class="home-portal-copy">
        <small>PERSONAL SPACE · 时刻保持质疑</small>
        <strong>前往 UsotsukiKaze 的个人主页</strong>
        <span>拈风的个人中转站，集中放置正在维护的项目与公开资料。</span>
      </span>
      <span class="home-portal-arrow" aria-hidden="true">↗</span>
    </a>
  </section>
</template>
