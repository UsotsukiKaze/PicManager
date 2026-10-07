<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { router } from './router';
import { useSession } from './state/session';
import { useWorkspace } from './state/workspace';
import { requestJSON, safeAvatar } from './api/http';
import ManagementTabs from './components/ManagementTabs.vue';
import AppIcon from './components/AppIcon.vue';

const session = useSession();
const workspace = useWorkspace();
const route = useRoute();
const scrollPositions = new Map<string, number>();
function restoreScroll() { document.getElementById('workspace-scroll')?.scrollTo({ top: scrollPositions.get(route.fullPath) || 0, behavior: 'instant' }); }
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
const pageName = computed(() => route.path === '/profile' ? '我的' : navigation.value.find(item => item.to === activePath.value)?.name || '图库');
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
    <img src="/static/icon/Pic.png" alt="PicManager" width="48" height="48">
    <p>{{ session.status === 'error' ? session.error : '正在验证登录状态…' }}</p>
    <button v-if="session.status === 'error'" class="btn btn-primary" @click="retrySession">重试</button>
  </div>
  <div v-else class="app-container modern-app">
    <header class="top-user-bar" id="top-user-bar">
      <div class="modern-header-start"><RouterLink to="/" class="modern-brand"><img src="/static/icon/Pic.png" alt="" width="30" height="30"><span>PicManager</span></RouterLink><span class="modern-header-context">{{ pageName }}</span></div>
      <nav class="user-actions-compact" aria-label="账户"><RouterLink class="header-link" to="/profile"><AppIcon name="character"/>我的</RouterLink><button class="header-link" @click="session.logout"><AppIcon name="logout"/>退出</button></nav>
    </header>
    <div class="main-wrapper">
      <nav class="sidebar modern-sidebar" id="workspace-sidebar" data-shell-owner="vue" aria-label="主导航">
        <div class="sidebar-menu">
          <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" class="modern-nav-link" :class="{ active: activePath === item.to }" :title="item.name" :aria-current="activePath === item.to ? 'page' : undefined">
            <img v-if="item.icon === 'pixiv'" class="modern-pixiv-nav-icon" src="/static/icon/pixiv-ol.svg" alt="" aria-hidden="true" width="24" height="24">
            <AppIcon v-else :name="item.icon"/>
            <span class="menu-text">{{ item.name }}</span>
          </RouterLink>
        </div>
        <div class="sidebar-footer">
          <button id="sidebar-toggle" class="modern-sidebar-toggle" :aria-expanded="!workspace.collapsed" aria-controls="workspace-sidebar" :aria-label="workspace.collapsed ? '展开侧栏' : '收起侧栏'" :title="workspace.collapsed ? '展开侧栏' : '收起侧栏'" @click="workspace.collapsed = !workspace.collapsed">
            <AppIcon :name="workspace.collapsed ? 'expand' : 'collapse'"/>
          </button>
          <RouterLink to="/profile" class="sidebar-user" :aria-current="route.path === '/profile' ? 'page' : undefined" :title="session.name">
            <div class="user-info-compact">
              <img class="user-avatar-small" id="header-avatar" :src="safeAvatar(session.user?.avatar_url)" alt="" @error="($event.target as HTMLImageElement).src = '/static/icon/Pic.png'">
              <span class="user-name-small" id="header-username">{{ session.name }}</span>
              <span class="user-role-small" id="header-role" :class="`role-${session.data?.is_guest ? 'guest' : session.user?.role || 'guest'}`">{{ session.data?.is_guest ? `今天还能提交: ${session.data.remaining_operations ?? 0}` : session.role }}</span>
            </div>
            <span class="sidebar-user-chevron" aria-hidden="true">›</span>
          </RouterLink>
          <span hidden id="total-images">0</span><span hidden id="total-groups">0</span>
        </div>
      </nav>
      <main class="main-content modern-content" id="workspace-scroll">
        <ManagementTabs v-if="management"/>
        <RouterView v-slot="{ Component }"><Transition name="workspace-page" mode="out-in" @after-enter="restoreScroll"><KeepAlive :max="3" :include="['HomeView', 'GalleryView']"><component :is="Component" :key="route.path"/></KeepAlive></Transition></RouterView>
        <div id="legacy-page-host" class="legacy-surface" v-show="route.meta.legacy"></div>
      </main>
    </div>
  </div>
  <div id="legacy-portals"></div>
  <div class="modern-toasts" aria-live="polite"><TransitionGroup name="toast"><div v-for="item in workspace.toasts" :key="item.id" class="modern-toast" :class="item.tone">{{ item.message }}</div></TransitionGroup></div>
</template>
