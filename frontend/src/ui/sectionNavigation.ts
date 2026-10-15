import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router';

export interface SectionItem { key: string; name: string; title: string; icon: string; to: RouteLocationRaw }
export type SectionFamily = 'management' | 'emoji' | 'upload' | 'settings' | 'profile' | 'rankings';
type SectionRoute = Pick<RouteLocationNormalizedLoaded, 'path' | 'query'>;
export const workspaceTitles: Array<{ family: SectionFamily; title: string }> = [
  { family: 'management', title: '图片管理' },
  { family: 'emoji', title: '表情包库' },
  { family: 'upload', title: '上传资源' },
  { family: 'settings', title: '设置' },
  { family: 'profile', title: '我的' },
  { family: 'rankings', title: '榜上有名' },
];
export const managementSections: SectionItem[] = [
  { key: 'images', name: '图片', title: '图片管理', icon: 'gallery', to: '/gallery' },
  { key: 'groups', name: '分组', title: '分组管理', icon: 'groups', to: '/manage/groups' },
  { key: 'characters', name: '角色', title: '角色管理', icon: 'character', to: '/manage/characters' },
  { key: 'features', name: '特征', title: '特征标签', icon: 'tags', to: '/manage/features' },
];
export function sectionFamily(path: string): SectionFamily | undefined {
  if (path === '/gallery' || managementSections.some(item => item.to === path)) return 'management';
  if (path === '/upload') return 'upload';
  if (path === '/emoji') return 'emoji';
  if (path === '/settings') return 'settings';
  if (path === '/profile') return 'profile';
  if (path === '/rankings') return 'rankings';
}
export function sectionsFor(route: SectionRoute): SectionItem[] {
  if (route.path === '/rankings') return [
    { key: 'contribution', name: '贡献榜', title: '榜上有名', icon: 'rankings', to: { path: '/rankings', query: { ...route.query, board: undefined } } },
    { key: 'characters', name: '角色榜', title: '角色榜', icon: 'character', to: { path: '/rankings', query: { ...route.query, board: 'characters' } } },
    { key: 'groups', name: '分组榜', title: '分组榜', icon: 'groups', to: { path: '/rankings', query: { ...route.query, board: 'groups' } } },
  ];
  if (['/settings', '/profile'].includes(route.path)) return [{
    key: route.path.slice(1), name: workspaceTitles.find(item => item.family === sectionFamily(route.path))!.title,
    title: workspaceTitles.find(item => item.family === sectionFamily(route.path))!.title, icon: route.path === '/settings' ? 'settings' : 'character', to: route.path,
  }];
  if (sectionFamily(route.path) === 'management') return managementSections;
  if (route.path === '/upload') return [
    { key: 'local', name: '上传', title: '上传资源', icon: 'upload', to: { path: '/upload', query: { ...route.query, tab: undefined } } },
    { key: 'temp', name: '待整', title: '待整理图片', icon: 'groups', to: { path: '/upload', query: { ...route.query, tab: 'temp' } } },
  ];
  return [
    { key: 'list', name: '全部表情', title: '表情包库', icon: 'emoji', to: { path: '/emoji', query: { ...route.query, tab: undefined } } },
    { key: 'tags', name: '情绪 / 功能', title: '情绪与功能', icon: 'tags', to: { path: '/emoji', query: { ...route.query, tab: 'tags' } } },
  ];
}
export function activeSection(route: SectionRoute) {
  if (route.path === '/rankings') return route.query.board === 'characters' || route.query.board === 'groups' ? route.query.board : 'contribution';
  if (['/settings', '/profile'].includes(route.path)) return route.path.slice(1);
  if (route.path === '/upload') return route.query.tab === 'temp' ? 'temp' : 'local';
  return route.path === '/emoji' ? (route.query.tab === 'tags' ? 'tags' : 'list')
    : managementSections.find(item => item.to === route.path)?.key || 'images';
}
