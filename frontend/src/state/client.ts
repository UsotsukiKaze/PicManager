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
