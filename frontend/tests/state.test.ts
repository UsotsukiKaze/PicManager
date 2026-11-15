import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { nextTick } from 'vue';
import { QueryObserver } from '@tanstack/vue-query';
import { queryClient, invalidateDomain } from '../src/state/client';
import { useSession } from '../src/state/session';

beforeEach(() => { setActivePinia(createPinia()); queryClient.clear(); });
afterEach(() => { queryClient.clear(); vi.unstubAllGlobals(); });
it('deduplicates simultaneous authentication checks', async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ is_guest: false, user: { id: 1, role: 'root' } }));
  vi.stubGlobal('fetch', fetcher);
  const session = useSession();
  await Promise.all([session.bootstrap(), session.bootstrap(), session.bootstrap()]);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(session.isAdmin).toBe(true);
});
it('clears account-owned caches on identity or permission changes', () => {
  const session = useSession();
  session.apply({ is_guest: false, user: { id: 1, role: 'root' } });
  queryClient.setQueryData(['images', session.identity], { private: true });
  session.apply({ is_guest: false, user: { id: 1, role: 'user' } });
  expect(queryClient.getQueryCache().getAll()).toHaveLength(0);
  expect(session.isAdmin).toBe(false);
  session.apply({ is_guest: true, guest_name: '游客' });
  expect(session.role).toBe('游客');
});
it('keeps mounted features during profile refresh', async () => {
  const session = useSession();
  session.apply({ is_guest: false, user: { id: 1, role: 'root' } });
  let resolve!: (value: Response) => void;
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>(done => { resolve = done; })));
  const refresh = session.bootstrap(true);
  await nextTick();
  expect(session.status).toBe('ready');
  resolve(Response.json({ is_guest: false, user: { id: 1, role: 'root', nickname: '新名称' } }));
  await refresh;
  expect(session.name).toBe('新名称');
});
it('invalidates list/detail/catalog caches after Pixiv imports and maintenance', () => {
  for (const key of [['images', 'identity', 'list'], ['images', 'identity', 'detail'], ['catalog', 'identity', 'groups'], ['dashboard', 'identity']]) {
    queryClient.setQueryData(key, { current: true });
  }
  invalidateDomain('/pixiv-ol/imports/1/resolve');
  expect(queryClient.getQueryCache().getAll().every(query => query.state.isInvalidated)).toBe(true);
  queryClient.setQueryData(['catalog', 'identity', 'groups'], []);
  invalidateDomain('/system/local-check');
  expect(queryClient.getQueryState(['catalog', 'identity', 'groups'])?.isInvalidated).toBe(true);
});


it('temp inspections preserve a catalog request shared by mounted controls and the detail editor', async () => {
  const key = ['catalog', 'identity', 'groups'];
  queryClient.setQueryData(key, [{ id: 1, name: 'before' }]);
  let finish!: (value: { id: number; name: string }[]) => void;
  const aborted = vi.fn();
  const fetcher = vi.fn(({ signal }: { signal: AbortSignal }) => new Promise<{ id: number; name: string }[]>(resolve => {
    signal.addEventListener('abort', aborted);
    finish = resolve;
  }));
  const observer = new QueryObserver(queryClient, { queryKey: key, queryFn: fetcher, staleTime: 60_000 });
  const unsubscribe = observer.subscribe(() => {});
  const refresh = observer.refetch();
  const editor = queryClient.fetchQuery({ queryKey: key, queryFn: fetcher, staleTime: 0 });
  const result = expect(editor).resolves.toEqual([{ id: 1, name: 'after' }]);
  try {
    for (const endpoint of ['/upload/temp-pixiv/start', '/upload/temp-pixiv/check', '/upload/temp-pixiv/stop', '/upload/temp-duplicates/scan?limit=1']) invalidateDomain(endpoint);
    expect(aborted).not.toHaveBeenCalled();
    expect(fetcher).toHaveBeenCalledTimes(1);
    finish([{ id: 1, name: 'after' }]);
    await result; await refresh;
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(false);
  } finally { unsubscribe(); observer.destroy(); }
});

it('temp imports and duplicate resolution still invalidate catalogs', () => {
  const key = ['catalog', 'identity', 'characters'];
  for (const endpoint of ['/upload/temp', '/upload/temp-duplicates/resolve', '/upload/duplicates/resolve']) {
    queryClient.setQueryData(key, []);
    invalidateDomain(endpoint);
    expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
  }
});
