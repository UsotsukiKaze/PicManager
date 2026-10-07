import { createRouter, createWebHashHistory } from 'vue-router';
import { pinia } from './state/client';
import { useSession } from './state/session';

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('./views/HomeView.vue') },
    { path: '/gallery', name: 'gallery', component: () => import('./views/GalleryView.vue') },
    ...[
      ['groups', '/manage/groups', 'management', 'group-management'],
      ['characters', '/manage/characters', 'management', 'character-management'],
      ['features', '/manage/features', 'management', 'feature-tag-management'],
      ['upload', '/upload', 'upload', ''], ['emoji', '/emoji', 'emoji-library', ''],
      ['pixiv', '/pixiv', 'pixiv-ol', ''], ['settings', '/settings', 'settings', ''],
      ['profile', '/profile', 'profile', ''], ['rankings', '/rankings', 'rankings', ''],
    ].map(([name, path, page, tab]) => ({ name, path, component: () => import('./views/FeatureView.vue'),
      meta: { legacy: true, page, tab, admin: name === 'pixiv' } })),
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});
router.beforeEach(async to => {
  const session = useSession(pinia);
  if (session.status !== 'ready') await session.bootstrap();
  if (session.status !== 'ready') return false;
  if (to.meta.admin && !session.isAdmin) return '/';
});
