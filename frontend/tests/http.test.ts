import { afterEach, describe, expect, it, vi } from 'vitest';
import { APIError, queryString, requestJSON, safeAvatar } from '../src/api/http';
import { allEntities, searchImages } from '../src/api/catalog';

afterEach(() => vi.unstubAllGlobals());
describe('HTTP contracts', () => {
  it('encodes filters while retaining zero/false', () => {
    expect(queryString({ pid: '1_p0&2', missing: undefined, blank: '', zero: 0, no: false }))
      .toBe('?pid=1_p0%262&zero=0&no=false');
  });
  it('uses the same-origin session and forwards cancellation', async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ images: [], total: 0 }));
    vi.stubGlobal('fetch', fetcher);
    const controller = new AbortController();
    await searchImages({ group_id: 9 }, 2, controller.signal);
    expect(fetcher.mock.calls[0][0]).toContain('offset=20&limit=20&view=card');
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: 'same-origin', signal: controller.signal });
  });
  it('does not set a multipart boundary manually', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetcher);
    expect(await requestJSON('/upload', { method: 'POST', body: new FormData() })).toBeUndefined();
    expect(fetcher.mock.calls[0][1].headers.has('Content-Type')).toBe(false);
  });
  it('reports non-JSON proxy errors safely and never retries a mutation', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response('<h1>proxy secret</h1>', { status: 502 }));
    vi.stubGlobal('fetch', fetcher);
    await expect(requestJSON('/api/images/id', { method: 'DELETE' })).rejects.toEqual(new APIError(502, '请求失败 (502)'));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
  it('does not recursively dispatch expiry for logout', async () => {
    const expired = vi.fn();
    window.addEventListener('picmanager-session-expired', expired);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
    await expect(requestJSON('/auth/logout', { method: 'POST' })).rejects.toBeInstanceOf(APIError);
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener('picmanager-session-expired', expired);
  });
  it('rejects executable avatar URLs', () => {
    expect(safeAvatar('javascript:alert(1)')).toBe('/favicon.ico');
    expect(safeAvatar('data:text/html,hello')).toBe('/favicon.ico');
    expect(safeAvatar('/favicon.ico')).toContain('/favicon.ico');
  });
});
describe('catalog pagination', () => {
  it('loads subsequent pages and deduplicates IDs', async () => {
    const first = Array.from({ length: 100 }, (_, id) => ({ id, name: String(id) }));
    const fetcher = vi.fn().mockResolvedValueOnce(Response.json(first))
      .mockResolvedValueOnce(Response.json([{ id: 99, name: 'duplicate' }, { id: 100, name: 'last' }]));
    vi.stubGlobal('fetch', fetcher);
    const rows = await allEntities('groups');
    expect(rows).toHaveLength(101);
    expect(fetcher.mock.calls[1][0]).toContain('skip=100');
  });
  it('propagates aborts without returning a partial catalog', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Cancelled', 'AbortError')));
    await expect(allEntities('characters')).rejects.toMatchObject({ name: 'AbortError' });
  });
  it('reports overflow rather than silently truncating labels', async () => {
    const full = Array.from({ length: 100 }, (_, id) => ({ id, name: String(id) }));
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(Response.json(full))));
    await expect(allEntities('groups')).rejects.toThrow('加载上限');
  });
});
