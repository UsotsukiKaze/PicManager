import type { RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router';

export interface SectionItem { key: string; name: string; title: string; icon: string; to: RouteLocationRaw }
export type SectionFamily = 'management' | 'emoji';
export const managementSections: SectionItem[] = [
  { key: 'images', name: '图片', title: '图片管理', icon: 'gallery', to: '/gallery' },
  { key: 'groups', name: '分组', title: '分组管理', icon: 'groups', to: '/manage/groups' },
  { key: 'characters', name: '角色', title: '角色管理', icon: 'character', to: '/manage/characters' },
  { key: 'features', name: '特征', title: '特征标签', icon: 'tags', to: '/manage/features' },
];
export function sectionFamily(path: string): SectionFamily | undefined {
  if (path === '/gallery' || managementSections.some(item => item.to === path)) return 'management';
  if (path === '/emoji') return 'emoji';
}
export function sectionsFor(route: RouteLocationNormalizedLoaded): SectionItem[] {
  if (sectionFamily(route.path) === 'management') return managementSections;
  return [
    { key: 'list', name: '全部表情', title: '表情包库', icon: 'emoji', to: { path: '/emoji', query: { ...route.query, tab: undefined } } },
    { key: 'tags', name: '情绪 / 功能', title: '情绪与功能', icon: 'tags', to: { path: '/emoji', query: { ...route.query, tab: 'tags' } } },
  ];
}
export function activeSection(route: RouteLocationNormalizedLoaded) {
  return route.path === '/emoji' ? (route.query.tab === 'tags' ? 'tags' : 'list')
    : managementSections.find(item => item.to === route.path)?.key || 'images';
}
