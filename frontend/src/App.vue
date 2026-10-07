<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { router } from './router';
import { useSession } from './state/session';
import { useWorkspace } from './state/workspace';
import { requestJSON, safeAvatar } from './api/http';
import ManagementTabs from './components/ManagementTabs.vue';

const session = useSession();
const workspace = useWorkspace();
const route = useRoute();
const scrollPositions = new Map<string, number>();
const stopBefore = router.beforeEach(async (to, from) => {
  const scroll = document.getElementById('workspace-scroll');
  if (scroll && to.fullPath !== from.fullPath) scrollPositions.set(from.fullPath, scroll.scrollTop);
  // Capture and suspend before hiding the DOM island so Pixiv keeps its reading position.
  if (window.ui && to.fullPath !== from.fullPath) {
    const bridge = await import('./compat/bridge');
    bridge.suspendFeatures();
  }
});
const stopAfter = router.afterEach(async (to, _from, failure) => {
  if (failure) return;
  await nextTick();
  document.getElementById('workspace-scroll')?.scrollTo({ top: scrollPositions.get(to.fullPath) || 0, behavior: 'instant' });
  if (scrollPositions.size > 100) scrollPositions.delete(scrollPositions.keys().next().value!);
});
const notificationController = new AbortController();
let notificationTimer: ReturnType<typeof setTimeout> | undefined;
const navigation = computed(() => [
  { to: '/', page: 'home', name: '首页', icon: 'home' },
  { to: '/gallery', page: 'management', name: '图片管理', icon: 'gallery' },
  { to: '/emoji', page: 'emoji', name: '表情包库', icon: 'emoji' },
  { to: '/upload', page: 'upload', name: '上传资源', icon: 'upload' },
  ...(session.isAdmin ? [{ to: '/pixiv', page: 'pixiv', name: 'Pixiv-ol', icon: 'pixiv' }] : []),
  { to: '/settings', page: 'settings', name: '设置', icon: 'settings' },
]);
const management = computed(() => route.path.startsWith('/manage/') || route.path === '/gallery');
const activePath = computed(() => management.value ? '/gallery' : route.path);
watch(() => workspace.collapsed, value => document.documentElement.classList.toggle('sidebar-collapsed', value), { immediate: true });
const expired = () => { void session.logout(); };
const profileUpdate = (event: MessageEvent) => {
  const frame = document.getElementById('profile-frame') as HTMLIFrameElement | null;
  if (event.origin === location.origin && event.source === frame?.contentWindow && event.data?.type === 'picmanager-profile-updated') void session.bootstrap(true);
};
const identityChanged = () => {
  workspace.filters = {}; workspace.page = 1;
  // Existing imperative feature controllers also discard all account-owned state.
  if (window.ui) window.location.reload();
};
async function retrySession() {
  await session.bootstrap();
  if (session.status === 'ready') await router.replace(route.fullPath);
}
onMounted(() => {
  void session.bootstrap().then(() => {
    if (location.pathname === '/pixiv-ol' && !location.hash && session.isAdmin) void router.replace('/pixiv');
    if (session.user) notificationTimer = setTimeout(async () => {
      try {
        const data = await requestJSON<{ approved: number; rejected: number }>('/auth/notifications', { signal: notificationController.signal });
        const count = data.approved + data.rejected;
        if (count) workspace.notify(`有 ${count} 条审核结果更新（通过 ${data.approved}，驳回 ${data.rejected}），可到个人中心查看详情`);
      } catch { /* Optional notification failure does not block navigation. */ }
    }, 1000);
  });
  window.addEventListener('picmanager-session-expired', expired);
  window.addEventListener('message', profileUpdate);
  window.addEventListener('picmanager-identity-changed', identityChanged);
});
onUnmounted(() => {
  stopBefore(); stopAfter(); clearTimeout(notificationTimer); notificationController.abort();
  window.removeEventListener('picmanager-session-expired', expired);
  window.removeEventListener('message', profileUpdate);
  window.removeEventListener('picmanager-identity-changed', identityChanged);
});
</script>

<template>
  <div v-if="session.status !== 'ready'" class="modern-auth-state" role="status">
    <img src="/favicon.ico" alt="PicManager" width="48" height="48">
    <p>{{ session.status === 'error' ? session.error : '正在验证登录状态…' }}</p>
    <button v-if="session.status === 'error'" class="btn btn-primary" @click="retrySession">重试</button>
  </div>
  <div v-else class="app-container modern-app">
    <header class="top-user-bar" id="top-user-bar">
      <RouterLink to="/" class="modern-brand"><img src="/favicon.ico" alt="" width="30" height="30"><span>PicManager</span></RouterLink>
      <nav class="user-actions-compact" aria-label="账户"><RouterLink class="header-link" to="/profile">我的</RouterLink><button class="header-link" @click="session.logout">退出</button></nav>
    </header>
    <div class="main-wrapper">
      <nav class="sidebar modern-sidebar" id="workspace-sidebar" aria-label="主导航">
        <div class="sidebar-menu">
          <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" class="modern-nav-link" :class="{ active: activePath === item.to }" :title="item.name" :aria-current="activePath === item.to ? 'page' : undefined">
            <img v-if="item.icon === 'pixiv'" src="/static/icon/pixiv-ol.svg" width="20" height="20" alt="">
            <svg v-else viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
              <path v-if="item.icon === 'home'" d="m3 10 9-7 9 7v10H3Zm6 10v-7h6v7"/>
              <path v-else-if="item.icon === 'gallery'" d="M3 3h18v18H3Zm1 14 5-5 4 4 3-3 5 5M16 8h.01"/>
              <path v-else-if="item.icon === 'emoji'" d="M8 9h.01M16 9h.01M7 14c2 4 8 4 10 0M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0"/>
              <path v-else-if="item.icon === 'upload'" d="M12 16V3m-5 5 5-5 5 5M3 16v5h18v-5"/>
              <path v-else d="M12 3v3m0 12v3M3 12h3m12 0h3M6 6l2 2m8 8 2 2M6 18l2-2m8-8 2-2M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0"/>
            </svg>
            <span class="menu-text">{{ item.name }}</span>
          </RouterLink>
        </div>
        <div class="sidebar-footer">
          <button id="sidebar-toggle" class="shell-toggle" :aria-expanded="!workspace.collapsed" aria-controls="workspace-sidebar" :aria-label="workspace.collapsed ? '展开侧栏' : '收起侧栏'" @click="workspace.collapsed = !workspace.collapsed">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16m7-12-3 4 3 4"/></svg><span class="shell-toggle-label">{{ workspace.collapsed ? '展开侧栏' : '收起侧栏' }}</span>
          </button>
          <RouterLink to="/profile" class="sidebar-user" :aria-current="route.path === '/profile' ? 'page' : undefined" :title="session.name">
            <div class="user-info-compact"><img class="user-avatar-small" id="header-avatar" :src="safeAvatar(session.user?.avatar_url)" alt="" @error="($event.target as HTMLImageElement).src = '/favicon.ico'"><span class="user-name-small" id="header-username">{{ session.name }}</span><span class="user-role-small" id="header-role">{{ session.data?.is_guest ? `剩余 ${session.data.remaining_operations ?? 0} 次` : session.role }}</span></div>
          </RouterLink>
          <span hidden id="total-images">0</span><span hidden id="total-groups">0</span>
        </div>
      </nav>
      <main class="main-content modern-content" id="workspace-scroll">
        <ManagementTabs v-if="management"/>
        <RouterView v-slot="{ Component }"><KeepAlive :max="3" :include="['HomeView', 'GalleryView']"><component :is="Component"/></KeepAlive></RouterView>
        <div id="legacy-page-host" class="legacy-surface" v-show="route.meta.legacy"></div>
      </main>
    </div>
  </div>
  <div id="legacy-portals"></div>
  <div class="modern-toasts" aria-live="polite"><TransitionGroup name="toast"><div v-for="item in workspace.toasts" :key="item.id" class="modern-toast" :class="item.tone">{{ item.message }}</div></TransitionGroup></div>
</template>
