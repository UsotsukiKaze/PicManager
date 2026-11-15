import { QueryClient } from '@tanstack/vue-query';
import { createPinia } from 'pinia';
import { APIError } from '../api/http';

export const pinia = createPinia();
export const queryClient = new QueryClient({
  defaultOptions: { queries: {
    staleTime: 30_000, gcTime: 5 * 60_000, refetchOnWindowFocus: false,
    retry: (count, error) => count < 2 && !(error instanceof APIError && error.status >= 400 && error.status < 500),
  }, mutations: { retry: false } },
});

export function invalidateDomain(path: string) {
  // Temp inspection uses POST for session control, but does not mutate the
  // library or labels. Invalidating active catalogs here cancels the promises
  // shared with the temp detail editor (TanStack CancelledError).
  if (/^\/(?:api\/)?upload\/(?:temp-pixiv\/(?:start|check|stop)|temp-duplicates\/scan)(?:\?|$)/.test(path)) return;
  if (/\/emojis|\/emotion-tags/.test(path)) {
    void queryClient.invalidateQueries({ queryKey: ['emojis'] });
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
  }
  if (/\/emotion-tags/.test(path)) void queryClient.invalidateQueries({ queryKey: ['catalog'] });
  // Mutations made by either runtime invalidate the same server-data cache.
  if (/\/images|\/groups|\/characters|\/feature-tags|\/upload|\/imports|\/jobs|\/pending|\/system|\/tag-mappings/.test(path)) {
    void queryClient.invalidateQueries({ queryKey: ['images'] });
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    window.ui?.invalidateCache('images');
  }
  if (/\/groups|\/characters|\/feature-tags|\/tag-mappings|\/imports|\/upload|\/pending|\/system/.test(path)) {
    void queryClient.invalidateQueries({ queryKey: ['catalog'] });
    for (const kind of ['groups', 'characters', 'featureTags']) window.ui?.invalidateCache(kind);
  }
}
