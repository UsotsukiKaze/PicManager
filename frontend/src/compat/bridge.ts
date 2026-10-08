/** One isolated DOM island for established upload/review/Pixiv controllers. */
import { router } from '../router';
import { queryClient, invalidateDomain, pinia } from '../state/client';
import { useSession } from '../state/session';
import { useWorkspace } from '../state/workspace';
import { allEntities } from '../api/catalog';
import { loadClassicScript, PINYIN_SCRIPT } from './scripts';

const scripts = [
  '/static/js/auth.js?v=20261008-modes', '/static/js/security.js?v=20260820a',
  PINYIN_SCRIPT, '/static/js/pinyin-search.js?v=20260820c',
  '/static/js/character-selector.js?v=20260820b', '/static/js/tag-selector.js?v=20261004f',
  '/static/js/api.js?v=20261007a', '/static/js/upload-queue.js?v=20261007a',
  '/static/js/query-panel.js?v=20260820d', '/static/js/entity-cache.js?v=20260820a',
  '/static/js/search-selector.js?v=20260820d', '/static/js/image-list.js?v=20261007a',
  '/static/js/modal.js?v=20261004q', '/static/js/workspace-shell.js?v=20261007a', '/static/js/ui.js?v=20261007d',
];
let bootstrap: Promise<void> | null = null;
let hydrated = false;
const pagePaths: Record<string, string> = {
  home: '/', management: '/gallery', upload: '/upload', 'emoji-library': '/emoji',
  'pixiv-ol': '/pixiv', profile: '/profile', settings: '/settings', rankings: '/rankings',
};

function hydrate() {
  const session = useSession(pinia);
  Object.assign(window.auth, { currentUser: session.user || null, isGuest: !!session.data?.is_guest,
    guestInfo: session.data?.is_guest ? session.data : null });
  window.auth.applyPermissions();
}

export function ensureLegacy(): Promise<void> {
  if (bootstrap) return bootstrap;
  bootstrap = (async () => {
    const host = document.getElementById('legacy-page-host');
    const portals = document.getElementById('legacy-portals');
    if (!host || !portals) throw new Error('页面尚未就绪');
    if (!host.childElementCount) {
      const response = await fetch('/static/index.html', { credentials: 'same-origin' });
      if (!response.ok) throw new Error('功能页面加载失败');
      const parsed = new DOMParser().parseFromString(await response.text(), 'text/html');
      const pages = parsed.querySelector('main.main-content');
      if (!pages) throw new Error('功能页面缺少内容');
      pages.querySelector('#page-home')?.remove();
      pages.querySelector('#page-profile')?.remove();
      // Static, repository-owned templates. Executable scripts are not inserted.
      host.replaceChildren(...Array.from(pages.children));
      for (const id of ['modal-overlay', 'toast-container', 'upload-queue-dock']) {
        const node = parsed.getElementById(id);
        if (node) portals.append(node);
      }
    }
    // Classic scripts execute in insertion order and fetch concurrently.
    await Promise.all(scripts.slice(0, -1).map(loadClassicScript));
    await loadClassicScript(scripts[scripts.length - 1]);
    hydrate();
    if (!hydrated) {
      hydrated = true;
      const session = useSession(pinia);
      const workspace = useWorkspace(pinia);
      window.addEventListener('picmanager-data-changed', event => invalidateDomain((event as CustomEvent<string>).detail));
      // The Vue gallery owns list rendering; old mutations must not reload its hidden predecessor.
      window.ui.loadImages = (params?: Record<string, unknown> | null) => {
        invalidateDomain('/images');
        if (params && Object.keys(params).length) {
          const fields = ['group_id', 'character_id', 'feature_tag_id', 'artist', 'pid', 'description', 'age_rating'];
          const query = Object.fromEntries(Object.entries(params).filter(([key, value]) => fields.includes(key) && value != null && value !== '').map(([key, value]) => [key, String(value)]));
          return router.push({ path: '/gallery', query });
        }
      };
      window.ui.showToast = (message: string, tone: string) => workspace.notify(message, tone);
      window.ui.switchPage = (page: string) => { void router.push(pagePaths[page] || '/'); };
      const switchTab = window.ui.switchTab.bind(window.ui);
      window.ui.switchTab = (tab: string) => {
        if (tab === 'image-list') { void router.push('/gallery'); return; }
        switchTab(tab);
      };
      const activate = window.ui.activateFeature.bind(window.ui);
      window.ui.activateFeature = (key: string, page: string, action: () => Promise<unknown>, message: string) =>
        activate(key, page, async () => {
          try { return await action(); }
          finally {
            if (window.ui.currentPage !== page) {
              if (page === 'pixiv-ol') window.pixivOL?.suspend();
              if (page === 'upload') window.upload?.suspendTemp();
            }
          }
        }, message);
      const checkAuth = window.auth.checkAuth.bind(window.auth);
      window.auth.checkAuth = async () => {
        const ok = await checkAuth();
        if (ok) useSession(pinia).apply({ is_guest: window.auth.isGuest,
          ...(window.auth.isGuest ? window.auth.guestInfo : { user: window.auth.currentUser }) });
        return ok;
      };
      window.auth.updateUI = hydrate;
      const originalRequest = window.api.request.bind(window.api);
      window.api.request = async (endpoint: string, options: RequestInit = {}) => {
        try {
          const result = await originalRequest(endpoint, options);
          if (options.method && options.method !== 'GET') invalidateDomain(endpoint);
          return result;
        } catch (error) {
          if ((error as { status?: number }).status === 401) window.dispatchEvent(new Event('picmanager-session-expired'));
          throw error;
        }
      };
      for (const [method, kind] of [['getGroups', 'groups'], ['getFeatureTags', 'feature-tags']]) {
        const original = window.api[method]?.bind(window.api);
        if (original) window.api[method] = (options: Record<string, unknown> = {}) =>
          Object.keys(options).length ? original(options) : queryClient.fetchQuery({
            queryKey: ['catalog', session.identity, kind], queryFn: ({ signal }) => allEntities(kind, signal), staleTime: 60_000,
          });
      }
      const characters = window.api.getCharacters.bind(window.api);
      window.api.getCharacters = (groupId: number | null = null, options: Record<string, unknown> = {}) =>
        groupId || Object.keys(options).length ? characters(groupId, options) : queryClient.fetchQuery({
          queryKey: ['catalog', session.identity, 'characters'], queryFn: ({ signal }) => allEntities('characters', signal), staleTime: 60_000,
        });
      for (const method of ['uploadSingleImage', 'uploadTempImage']) {
        const original = window.api[method]?.bind(window.api);
        if (original) window.api[method] = async (...args: unknown[]) => {
          const result = await original(...args);
          invalidateDomain('/upload');
          return result;
        };
      }
    }
  })().catch(error => { bootstrap = null; throw error; });
  return bootstrap;
}

export function suspendFeatures() {
  window.pixivOL?.suspend();
  window.upload?.suspendTemp();
  if (window.ui) { window.ui.imageLoadRequestId++; window.ui.currentPage = ''; }
  document.querySelectorAll('#legacy-page-host .page-content').forEach(node => { (node as HTMLElement).style.display = 'none'; });
}

export async function activateFeature(page: string, tab: string, stillCurrent: () => boolean) {
  await ensureLegacy();
  if (!stillCurrent()) return;
  hydrate();
  document.querySelectorAll('#legacy-page-host .page-content').forEach(node => { (node as HTMLElement).style.display = 'none'; });
  const target = document.getElementById(`page-${page}`);
  if (!target) throw new Error('页面不存在');
  target.style.display = 'block';
  window.ui.currentPage = page;
  window.ui.currentTab = null;
  if (page === 'management') {
    window.ui.applyRolePreferences();
    window.ui.switchTab(tab || 'group-management');
  } else {
    window.ui.resetToFirstTab(page);
    window.ui.handlePageSwitch(page);
  }
  for (const node of target.querySelectorAll<HTMLImageElement>('img[data-auth-src]')) node.src = node.dataset.authSrc || '';
  const auto = document.getElementById('pixiv-check-auto') as HTMLInputElement | null;
  if (auto && !auto.dataset.modernBound) {
    auto.dataset.modernBound = 'true';
    try { auto.checked = localStorage.getItem('picmanager.pixivAutoReview') === 'true'; } catch { /* Optional persistence. */ }
    auto.onchange = () => { try { localStorage.setItem('picmanager.pixivAutoReview', String(auto.checked)); } catch { /* Optional persistence. */ } };
  }
}

export async function editImage(id: string) {
  await ensureLegacy();
  window.ui.currentPage = 'management';
  window.ui.editImage(id);
}
