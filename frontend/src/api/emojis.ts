import { queryString, requestJSON } from './http';
import type { Entity } from './types';

export interface EmojiRecord {
  emoji_id: string; file_path: string; file_extension: string; file_size?: number;
  width?: number; height?: number; description?: string; original_filename?: string; created_at?: string;
  groups: Entity[]; characters: Entity[]; emotions: Entity[];
}
export interface EmojiFilters { group_id?: number; character_id?: number; emotion_id?: number; function_id?: number; description?: string }
export interface EmojiResult { emojis: EmojiRecord[]; total: number; offset: number; limit: number }
export interface EmojiFacet extends Entity { emoji_count: number }
export const searchEmojis = (filters: EmojiFilters, page: number, signal?: AbortSignal) =>
  requestJSON<EmojiResult>(`/api/emojis/search${queryString({ ...filters, offset: (page - 1) * 20, limit: 20 })}`, { signal });
export const emojiDetail = (id: string, signal?: AbortSignal) => requestJSON<EmojiRecord>(`/api/emojis/${encodeURIComponent(id)}`, { signal });
export const emojiFacets = (signal?: AbortSignal) => requestJSON<EmojiFacet[]>('/api/emojis/characters', { signal });

export async function editEmoji(kind: 'upload' | 'emoji' | 'emotion', id?: string | number) {
  const { ensureLegacy } = await import('../compat/bridge');
  await ensureLegacy();
  const controller = await window.auth.loadFeature('emoji');
  await controller.loadOptions();
  if (kind === 'upload') await controller.showUploadModal();
  else if (kind === 'emoji') await controller.showEditEmojiModal(id);
  else if (id) controller.showEditEmotionModal(id);
  else controller.showCreateEmotionModal();
}
