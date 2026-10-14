<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuery } from '@tanstack/vue-query';
import { requestJSON, safeAvatar } from '../api/http';
import type { Entity, GroupCover, Ranking, Rankings, SystemStatus } from '../api/types';
import { useSession } from '../state/session';
import EntityAvatar from '../components/EntityAvatar.vue';
import '../styles/home.css';

type FeaturedGroup = Entity & { cover?: GroupCover | null; cover_refreshing?: boolean };
const failedCovers = ref(new Set<string>());
function coverFailed(imageId: string) { failedCovers.value = new Set([...failedCovers.value, imageId]); }
const session = useSession();
const { data: status, error: statusError, refetch: retryStatus } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'status']), queryFn: ({ signal }) => requestJSON<SystemStatus>('/api/system/status', { signal }) });
const { data: rankings, error: rankingError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'rankings']), queryFn: ({ signal }) => requestJSON<Rankings>('/api/rankings?limit=5', { signal }) });
const { data: popular, error: popularError } = useQuery({ queryKey: computed(() => ['dashboard', session.identity, 'popular']), queryFn: ({ signal }) => requestJSON<FeaturedGroup[]>('/api/groups/popular?limit=5&include_covers=true', { signal }), refetchInterval: query => query.state.data?.some(group => group.cover_refreshing) ? 15_000 : 300_000 });
const numbers = new Intl.NumberFormat('zh-CN');
const count = (value?: number) => value == null ? '—' : numbers.format(value);
const rankCount = (item: Ranking) => item.score ?? item.contribution_count ?? item.upload_count ?? item.count ?? 0;
const selectedId = ref<number>();
const groups = computed(() => (popular.value || []).slice(0, 5));
const selectedGroup = computed(() => groups.value.find(group => group.id === selectedId.value) || groups.value[0]);
watch(groups, value => {
  // Warm the small set of local previews so switching cards does not flash.
  for (const group of value) if (group.cover?.preview_url) {
    const preview = new Image();
    preview.src = group.cover.preview_url;
  }
});
const selectedIndex = computed(() => Math.max(0, groups.value.findIndex(group => group.id === selectedGroup.value?.id)));
const boards = computed(() => [
  { title: '总贡献度排行', label: 'CONTRIBUTORS', rows: rankings.value?.contribution || [], unit: '贡献', empty: '还没有贡献记录' },
  { title: '近期上传分组排行', label: `LAST ${rankings.value?.recent_days || 30} DAYS`, rows: rankings.value?.recent_groups || [], unit: '张', empty: `近 ${rankings.value?.recent_days || 30} 天还没有新上传图片` },
]);
const avatarFallback = (event: Event) => { (event.target as HTMLImageElement).src = '/static/icon/Pic.png'; };
</script>

<template>
  <section class="modern-home archive-home">
    <div class="archive-masthead"><span><i aria-hidden="true"></i> PICMANAGER / VISUAL ARCHIVE</span><span>小 · 爱 · 图 · 库</span></div>
    <section class="archive-hero" aria-labelledby="archive-heading">
      <div class="archive-intro">
        <span class="archive-eyebrow" aria-hidden="true">YOUR COLLECTION. YOUR UNIVERSE.</span>
        <h1 id="archive-heading">小爱图库</h1>
        <div class="archive-actions">
          <RouterLink class="archive-launch" to="/gallery"><span>进入图库<small aria-hidden="true">EXPLORE ARCHIVE</small></span><b aria-hidden="true">↗</b></RouterLink>
          <RouterLink class="archive-upload" to="/upload"><span>上传资源<small aria-hidden="true">UPLOAD RESOURCE</small></span><b aria-hidden="true">＋</b></RouterLink>
        </div>
        <div class="archive-coordinate" aria-hidden="true"><span>01 / COLLECTION TERMINAL</span><span>＋ ──── ＋</span></div>
      </div>
      <aside class="archive-deck" aria-label="分组档案">
        <div class="archive-deck-top"><span>精选分组 / COLLECTIONS</span><span>{{ String(groups.length ? selectedIndex + 1 : 0).padStart(2, '0') }} / {{ String(groups.length).padStart(2, '0') }}</span></div>
        <div class="archive-stage">
          <span class="archive-stage-word" aria-hidden="true">ARCHIVE</span>
          <div class="archive-sheet archive-sheet-back" aria-hidden="true"></div>
          <div class="archive-sheet archive-sheet-middle" aria-hidden="true"></div>
          <Transition name="archive-swap" mode="out-in">
            <RouterLink v-if="selectedGroup" :key="selectedGroup.id" class="archive-sheet archive-sheet-front" :to="{ path: '/gallery', query: { group_id: selectedGroup.id } }" :aria-label="`浏览${selectedGroup.name}分组`">
              <span class="archive-file-code">COLLECTION / {{ String(selectedGroup.id).padStart(3, '0') }} <b>↗</b></span>
              <div class="archive-file-art"><img v-if="selectedGroup.cover && !failedCovers.has(selectedGroup.cover.image_id)" class="archive-cover" :src="selectedGroup.cover.preview_url" :alt="`${selectedGroup.name}分组封面`" decoding="async" @error="coverFailed(selectedGroup.cover.image_id)">
                <EntityAvatar v-else :name="selectedGroup.name" :src="selectedGroup.avatar_url"/><span aria-hidden="true">＋</span></div>
              <div class="archive-file-caption"><strong>{{ selectedGroup.name }}</strong><span>{{ count(selectedGroup.image_count) }} 张收藏</span></div>
              <span class="archive-barcode" aria-hidden="true"></span>
            </RouterLink>
            <div v-else key="empty" class="archive-sheet archive-sheet-front archive-file-empty" role="status"><img src="/static/icon/Pic.png" alt=""><strong>{{ popularError ? '分组暂时无法加载' : !popular ? '正在读取档案…' : '收藏，从这里开始' }}</strong><RouterLink v-if="popular && !popular.length" to="/manage/groups">添加第一个分组 ↗</RouterLink></div>
          </Transition>
        </div>
        <div v-if="groups.length" class="archive-group-selector" aria-label="选择精选分组">
          <button v-for="(group, index) in groups" :key="group.id" :aria-pressed="selectedGroup?.id === group.id" :aria-label="`预览${group.name}`" :title="group.name" @click="selectedId = group.id"><span>{{ String(index + 1).padStart(2, '0') }}</span><span>{{ group.name }}</span></button>
        </div>
      </aside>
    </section>

    <section class="archive-metrics" aria-label="图库统计">
      <RouterLink v-for="(metric, index) in [
        { label: '全部图片', english: 'IMAGES', value: status?.total_images, to: '/gallery' },
        { label: '表情包库', english: 'EMOJIS', value: status?.total_emojis, to: '/emoji' },
        { label: '作品分组', english: 'COLLECTIONS', value: status?.total_groups, to: '/manage/groups' },
        { label: '收录角色', english: 'CHARACTERS', value: status?.total_characters, to: '/manage/characters' },
      ]" :key="metric.to" :to="metric.to" class="archive-metric home-metric-card"><span class="archive-metric-label">{{ metric.label }} <small>{{ metric.english }}</small></span><strong>{{ count(metric.value) }}</strong><span class="archive-metric-foot">0{{ index + 1 }} <span aria-hidden="true">↗</span></span></RouterLink>
    </section>
    <div v-if="statusError" class="archive-status" role="status">统计暂时无法加载 <button @click="retryStatus()">重新加载</button></div>

    <div class="archive-section-heading"><h2><span>02 /</span> 共建记录</h2><RouterLink to="/rankings">查看完整榜单 <span aria-hidden="true">↗</span></RouterLink></div>
    <section class="archive-boards" aria-label="图库排行榜">
      <article v-for="board in boards" :key="board.label" class="archive-board">
        <header><div><span>{{ board.label }}</span><h3>{{ board.title }}</h3></div><span class="archive-board-tag">TOP 05</span></header>
        <div v-for="(item, index) in board.rows" :key="index" class="archive-ranking-row">
          <span class="archive-rank-number">{{ String(index + 1).padStart(2, '0') }}</span>
          <img :src="safeAvatar(item.avatar_url)" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @error="avatarFallback">
          <span class="archive-rank-name" :title="item.nickname || item.qq_number || item.name || item.group_name">{{ item.nickname || item.qq_number || item.name || item.group_name || '—' }}</span>
          <strong>{{ count(rankCount(item)) }} <small>{{ board.unit }}</small></strong>
        </div>
        <div v-if="!board.rows.length" class="archive-board-empty" role="status"><span aria-hidden="true">＋</span><p>{{ rankingError ? '排行暂时无法加载' : !rankings ? '正在读取记录…' : board.empty }}</p><RouterLink v-if="rankings && !rankingError" to="/upload">上传一份热爱，留下你的足迹 ↗</RouterLink></div>
      </article>
    </section>
    <a class="archive-personal" href="https://usotsuki-kaze.com/" target="_blank" rel="noopener noreferrer"><span class="archive-personal-icon" aria-hidden="true"><img src="https://usotsuki-kaze.com/favicon.ico" alt="" loading="lazy" @error="avatarFallback"></span><span><small>BEYOND THE ARCHIVE / 时刻保持质疑</small><strong>UsotsukiKaze 的个人空间</strong><span>项目、想法，以及图库之外的探索。</span></span><b aria-hidden="true">↗</b></a>
    <footer class="archive-footer"><span>PICMANAGER · KEEP WHAT YOU LOVE.</span><span>END OF INDEX / 下一张，值得收藏。</span></footer>
  </section>
</template>
