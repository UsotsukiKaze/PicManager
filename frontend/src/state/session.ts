import { computed, shallowRef } from 'vue';
import { defineStore } from 'pinia';
import { APIError, requestJSON } from '../api/http';
import type { SessionEnvelope } from '../api/types';
import { queryClient } from './client';

export const useSession = defineStore('session', () => {
  const data = shallowRef<SessionEnvelope | null>(null);
  const status = shallowRef<'loading' | 'ready' | 'error'>('loading');
  const error = shallowRef('');
  let pending: Promise<void> | null = null;
  let loggingOut = false;
  const user = computed(() => data.value?.user);
  const isAdmin = computed(() => ['root', 'admin'].includes(user.value?.role || ''));
  const identity = computed(() => `${user.value?.id ?? data.value?.guest_ip ?? data.value?.guest_name ?? 'anonymous'}:${user.value?.role || 'guest'}`);
  const name = computed(() => user.value?.nickname || user.value?.qq_number || data.value?.guest_name || '游客');
  const role = computed(() => ({ root: 'Root', admin: '管理员', user: '用户', guest: '游客' }[user.value?.role || 'guest']) || '游客');

  function apply(next: SessionEnvelope) {
    const before = identity.value;
    const previous = data.value;
    data.value = next;
    if (before !== identity.value) {
      void queryClient.cancelQueries(); queryClient.clear();
      if (previous) window.dispatchEvent(new Event('picmanager-identity-changed'));
    }
    status.value = 'ready';
  }
  function bootstrap(force = false): Promise<void> {
    if (pending) return pending;
    if (status.value === 'ready' && !force) return Promise.resolve();
    if (!data.value) status.value = 'loading';
    pending = requestJSON<SessionEnvelope>('/auth/me').then(apply).catch(reason => {
      status.value = data.value ? 'ready' : 'error';
      error.value = reason instanceof APIError && reason.status === 401 ? '请先登录' : '暂时无法连接服务器，请重试';
      if (reason instanceof APIError && reason.status === 401) window.location.replace('/login');
    }).finally(() => { pending = null; });
    return pending;
  }
  async function logout() {
    if (loggingOut) return;
    loggingOut = true;
    await queryClient.cancelQueries();
    queryClient.clear();
    data.value = null;
    try { await requestJSON('/auth/logout', { method: 'POST' }); }
    catch { /* Navigation clears local identity even if the server is offline. */ }
    finally { window.location.assign('/login'); }
  }
  return { data, status, error, user, isAdmin, identity, name, role, apply, bootstrap, logout };
});
