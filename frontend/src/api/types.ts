export type AgeRating = 'all' | 'r12' | 'r16' | 'r18';
export interface User { id: number; nickname?: string; qq_number?: string; role: 'root' | 'admin' | 'user'; avatar_url?: string }
export interface SessionEnvelope { is_guest: boolean; user?: User; guest_name?: string; guest_ip?: string; remaining_operations?: number }
export interface Entity { id: number; name: string; avatar_url?: string; group_id?: number; group_name?: string; aliases?: string[]; nicknames?: string[] }
export interface Artist { id: string; name: string; avatar_url?: string }
export interface ImageCardRecord {
  image_id: string; pid?: string; age_rating: AgeRating; width?: number; height?: number;
  characters: Entity[]; groups: Entity[]; artist?: Artist;
}
export interface ImageRecord extends ImageCardRecord {
  description?: string; file_extension: string; file_size?: number;
  feature_tags: Entity[]; pixiv_tags: Array<{ name: string; translated_name?: string }>;
  pixiv_verified: boolean; local_verified: boolean; pixiv_page?: number; pixiv_page_count?: number;
}
export interface ImageSearchResult { images: ImageCardRecord[]; total: number; offset: number; limit: number }
export interface ImageFilters {
  group_id?: number; character_id?: number; feature_tag_id?: number;
  artist?: string; pid?: string; description?: string; age_rating?: AgeRating | '';
}
export interface SystemStatus { total_images: number; total_emojis: number; total_groups: number; total_characters: number }
export interface Ranking { nickname?: string; qq_number?: string; avatar_url?: string; name?: string; group_name?: string; score?: number; count?: number; contribution_count?: number; upload_count?: number }
export interface Rankings { contribution: Ranking[]; recent_groups: Ranking[]; recent_days: number }
