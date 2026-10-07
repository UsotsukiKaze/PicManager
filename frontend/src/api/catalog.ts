import { queryString, requestJSON } from './http';
import type { Entity, ImageFilters, ImageRecord, ImageSearchResult } from './types';

export async function allEntities(kind: string, signal?: AbortSignal): Promise<Entity[]> {
  const rows: Entity[] = [];
  const seen = new Set<number>();
  for (let skip = 0; skip < 10000; skip += 100) {
    const page = await requestJSON<Entity[]>(`/api/${kind}/${queryString({ skip, limit: 100 })}`, { signal });
    for (const row of page) if (!seen.has(row.id)) { seen.add(row.id); rows.push(row); }
    if (page.length < 100) return rows;
  }
  throw new Error('标签数量超过当前加载上限，请缩小检索范围');
}

export const searchImages = (filters: ImageFilters, page: number, signal?: AbortSignal) =>
  requestJSON<ImageSearchResult>(`/api/images/search${queryString({ ...filters, offset: (page - 1) * 20, limit: 20, view: 'card' })}`, { signal });
export const imageDetail = (id: string, signal?: AbortSignal) =>
  requestJSON<ImageRecord>(`/api/images/${encodeURIComponent(id)}`, { signal });
