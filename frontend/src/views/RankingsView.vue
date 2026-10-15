<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter, type RouteLocationRaw } from 'vue-router';
import { useQuery } from '@tanstack/vue-query';
import { queryString, requestJSON } from '../api/http';
import { allEntities } from '../api/catalog';
import type { Rankings } from '../api/types';
import { useSession } from '../state/session';
import { reducedMotion } from '../state/appearance';
import AppIcon from '../components/AppIcon.vue';
import EntityAvatar from '../components/EntityAvatar.vue';
import EntityPicker from '../components/EntityPicker.vue';
import '../styles/rankings.css';

type Board = 'contribution' | 'characters' | 'groups';
const boards = [
  { value: 'contribution', name: '贡献榜', icon: 'character', heading: '图库共建者', description: '按审核通过的提交累计贡献分', unit: '贡献分', subject: '贡献者', empty: '还没有贡献记录' },
  { value: 'characters', name: '角色榜', icon: 'gallery', heading: '角色图片数', description: '按图库内可用图片数量排序', unit: '张图片', subject: '角色', empty: '还没有角色记录' },
  { value: 'groups', name: '分组榜', icon: 'groups', heading: '分组图片数', description: '按图库内可用图片数量排序', unit: '张图片', subject: '分组', empty: '还没有分组记录' },
] as const;
const route = useRoute(), router = useRouter(), session = useSession();
const board = computed<Board>(() => route.query.board === 'characters' || route.query.board === 'groups' ? route.query.board : 'contribution');
const groupId = computed(() => {
  const value = route.query.group_id;
  return typeof value === 'string' && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : undefined;
});
const scopedGroup = computed(() => board.value === 'characters' ? groupId.value : undefined);
const groups = useQuery({ queryKey: computed(() => ['catalog', session.identity, 'groups']), queryFn: ({ signal }) => allEntities('groups', signal), enabled: computed(() => board.value === 'characters') });
const groupName = computed(() => groups.data.value?.find(group => group.id === groupId.value)?.name || (groupId.value ? `分组 ${groupId.value}` : ''));
function filterGroup(id?: number) { void router.push({ query: { ...route.query, group_id: id === undefined ? undefined : String(id) } }); }
const selected = computed(() => boards.find(item => item.value === board.value)!);
const { data, isPending, isFetching, isError, refetch } = useQuery({
  queryKey: computed(() => ['dashboard', session.identity, 'rankings', 50, scopedGroup.value ?? null]),
  queryFn: ({ signal }) => requestJSON<Rankings>(`/api/rankings${queryString({ limit: 50, group_id: scopedGroup.value })}`, { signal }),
});
const format = new Intl.NumberFormat('zh-CN');
const rows = computed(() => (data.value?.[board.value] || []).slice(0, 50).map((item, index) => {
  const id = board.value === 'contribution' ? item.user_id : board.value === 'characters' ? item.character_id : item.group_id;
  const score = board.value === 'contribution' ? item.score ?? item.contribution_count ?? 0 : item.image_count ?? item.count ?? 0;
  const name = item.nickname || item.name || '未命名';
  const mine = board.value === 'contribution' && id !== undefined && id === session.user?.id;
  const to: RouteLocationRaw | undefined = board.value !== 'contribution' && id !== undefined
    ? { path: '/gallery', query: { [board.value === 'characters' ? 'character_id' : 'group_id']: id } } : undefined;
  return { key: `${board.value}-${id ?? index}`, rank: index + 1, name, score, avatar: item.avatar_url, mine, to,
    subtitle: board.value === 'contribution' ? '图库共建者' : board.value === 'characters' ? item.group_name || '未分组' : `${format.format(item.character_count ?? 0)} 位角色` };
}));
const leaders = computed(() => rows.value.slice(0, 3)), remaining = computed(() => rows.value.slice(3));
const maxScore = computed(() => Math.max(1, ...rows.value.map(row => row.score)));
const content = ref<HTMLElement>();
const feedback = ref('');
const animations = new Set<Animation>();
let active = true;
watch(() => [board.value, scopedGroup.value], () => { feedback.value = ''; });
async function refresh() {
  if (isFetching.value) return;
  feedback.value = '';
  const previousGroup = scopedGroup.value, previousBoard = board.value;
  const result = await refetch();
  if (!active || previousGroup !== scopedGroup.value || previousBoard !== board.value) return;
  feedback.value = result.isError ? data.value ? '刷新失败，已保留当前榜单' : '暂时无法读取榜单，请稍后重试' : '榜单已更新';
  if (result.isError || reducedMotion()) return;
  content.value?.querySelectorAll('.rank-value').forEach(element => {
    const animation = element.animate([{ opacity: .4, transform: 'translateY(4px)' }, { opacity: 1, transform: 'none' }], { duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)' });
    animations.add(animation); void animation.finished.then(() => animations.delete(animation), () => animations.delete(animation));
  });
}
onBeforeUnmount(() => { active = false; animations.forEach(animation => animation.cancel()); });
</script>

<template>
  <section class="rankings-workspace" aria-label="完整榜单">
    <header class="rank-toolbar">
      <div class="rank-toolbar-context"><div v-if="board === 'characters'" class="rank-group-picker"><EntityPicker label="分组" :items="groups.data.value || []" :model-value="groupId" :disabled="groups.isPending.value" @update:model-value="filterGroup"/></div><span v-else class="rank-toolbar-kicker" aria-hidden="true">HONOR ARCHIVE <i>＋</i> TOP 50</span></div>
      <div class="rank-toolbar-actions"><RouterLink to="/" class="rank-home"><AppIcon name="left"/>返回首页</RouterLink><button class="rank-refresh" type="button" :disabled="isFetching" aria-label="刷新榜单" @click="refresh"><AppIcon name="refresh" :class="{ 'is-spinning': isFetching }"/><span>{{ isFetching ? '更新中' : '刷新' }}</span></button></div>
    </header>
    <div v-if="board === 'characters' && groups.isError.value" class="rank-filter-error" role="alert">分组列表暂时无法加载<button type="button" :disabled="groups.isFetching.value" @click="groups.refetch()">重试分组</button></div>
    <div class="rank-feedback" role="status">{{ isError && data ? '' : feedback }}</div>
    <div v-if="isError && data" class="rank-refresh-error" role="alert">{{ feedback || '更新暂时失败，当前榜单仍可查看' }}<button type="button" :disabled="isFetching" @click="refresh">重试</button></div>
    <div v-if="isPending" class="rank-loading" role="status" aria-label="正在读取榜单" aria-busy="true"><div class="rank-podium" aria-hidden="true"><div v-for="n in 3" :key="n" class="rank-skeleton rank-skeleton-leader"></div></div><div class="rank-skeleton-list" aria-hidden="true"><div v-for="n in 6" :key="n" class="rank-skeleton"></div></div></div>
    <div v-else-if="!data && isError" class="rank-empty" role="alert"><AppIcon name="refresh"/><h2>榜单暂时无法加载</h2><p>稍后重试，重新读取共建记录。</p><button class="rank-primary" type="button" :disabled="isFetching" @click="refresh">重新加载</button></div>
    <Transition v-else name="rank-board" mode="out-in">
      <section :key="board" ref="content" class="rank-board" :data-board="board" role="region" :aria-label="selected.name" :aria-busy="isFetching">
        <header class="rank-board-heading"><div><h2>{{ selected.heading }}</h2><p>{{ selected.description }}<template v-if="scopedGroup"> · {{ groupName }}</template></p></div><span class="rank-edition" :aria-label="`当前展示 ${rows.length} 条记录，最多 50 条`"><b>{{ String(rows.length).padStart(2, '0') }}</b><span>/ TOP 50</span></span></header>
        <template v-if="rows.length">
          <div class="rank-podium" aria-label="前三名">
            <component :is="row.to ? RouterLink : 'article'" v-for="(row, index) in leaders" :key="row.key" :to="row.to" class="rank-leader rank-entry" :class="{ 'is-first': index === 0, 'is-link': row.to, 'is-mine': row.mine }" :style="{ '--rank-order': index }" :aria-label="row.to ? `浏览${row.name}的图片` : undefined">
              <div class="rank-leader-top"><span class="rank-leader-number"><small aria-hidden="true">NO.</small>{{ String(row.rank).padStart(2, '0') }}</span><span v-if="row.mine" class="rank-you">你</span><span v-else class="rank-leader-mark" aria-hidden="true">{{ index === 0 ? '＋' : '·' }}</span></div>
              <EntityAvatar :name="row.name" :src="row.avatar"/>
              <h3 :title="row.name">{{ row.name }}</h3><p class="rank-subtitle">{{ row.subtitle }}</p>
              <div class="rank-leader-score"><strong class="rank-value">{{ format.format(row.score) }}</strong><span>{{ selected.unit }}</span><AppIcon v-if="row.to" name="right"/></div>
              <span class="rank-leader-line" aria-hidden="true"></span>
            </component>
          </div>
          <div v-if="remaining.length" class="rank-list-panel">
            <div class="rank-columns" aria-hidden="true"><span>名次</span><span>{{ selected.subject }}</span><span>{{ selected.unit }}</span><span></span></div>
            <ol class="rank-list" start="4">
              <li v-for="(row, index) in remaining" :key="row.key" class="rank-entry" :style="{ '--rank-order': Math.min(index + 3, 8) }">
                <component :is="row.to ? RouterLink : 'div'" :to="row.to" class="rank-row" :class="{ 'is-link': row.to, 'is-mine': row.mine }" :aria-label="row.to ? `浏览${row.name}的图片` : undefined">
                  <span class="rank-position">{{ String(row.rank).padStart(2, '0') }}</span><div class="rank-identity"><EntityAvatar :name="row.name" :src="row.avatar"/><div><strong :title="row.name">{{ row.name }}<span v-if="row.mine" class="rank-you">你</span></strong><small>{{ row.subtitle }}</small></div></div>
                  <div class="rank-row-score"><strong class="rank-value">{{ format.format(row.score) }}</strong><span class="rank-meter" aria-hidden="true"><i :style="{ width: `${Math.max(0, Math.min(100, row.score / maxScore * 100))}%` }"></i></span></div><AppIcon v-if="row.to" name="right"/><span v-else></span>
                </component>
              </li>
            </ol>
          </div>
          <footer class="rank-footnote"><span aria-hidden="true">＋ ──── ＋</span>{{ board === 'contribution' ? '仅统计登录用户审核通过的提交' : '仅统计可用图片，同图在每个所属角色或分组内计一次' }}</footer>
        </template>
        <div v-else class="rank-empty" role="status"><AppIcon :name="selected.icon"/><h3>{{ selected.empty }}</h3><p>{{ board === 'contribution' ? '上传或完善图片，留下第一份共建记录。' : '整理图片，让喜欢的角色与分组出现在这里。' }}</p><RouterLink class="rank-primary" :to="board === 'contribution' ? '/upload' : '/gallery'">{{ board === 'contribution' ? '上传资源' : '进入图库' }}<AppIcon name="right"/></RouterLink></div>
      </section>
    </Transition>
  </section>
</template>
