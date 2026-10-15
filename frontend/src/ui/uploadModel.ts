import type { AgeRating } from '../api/types';

export type UploadKind = 'image' | 'emoji';
export type UploadStatus = 'checking' | 'draft' | 'queued' | 'uploading' | 'processing' | 'attention' | 'reviewing' | 'success' | 'pending' | 'failed' | 'uncertain' | 'cancelled';
export interface UploadMetadata {
  kind: UploadKind; group_ids: number[]; character_ids: number[]; feature_tag_ids: number[];
  emotion_ids: number[]; age_rating: AgeRating; pid: string; description: string;
}
export interface UploadResult { status?: string; image_id?: string; message?: string; duplicate_token?: string; [key: string]: unknown }
export interface UploadItem {
  id: string; file: File; url: string; digest: string; width: number; height: number;
  metadata: UploadMetadata; status: UploadStatus; progress: number; message: string;
  result?: UploadResult; snapshot?: UploadMetadata; queueId?: number; pidInferred?: boolean;
}
export interface UploadCapabilities { max_file_size: number; extensions: string[] }
export const defaultMetadata = (kind: UploadKind = 'image'): UploadMetadata => ({ kind, group_ids: [], character_ids: [], feature_tag_ids: [], emotion_ids: [], age_rating: 'r12', pid: '', description: '' });
export const cloneMetadata = (value: UploadMetadata): UploadMetadata => JSON.parse(JSON.stringify(value));
export const statusLabels: Record<UploadStatus, string> = {
  checking: '检查中', draft: '待补充', queued: '排队中', uploading: '上传中', processing: '处理中', attention: '待确认', reviewing: '比对中',
  success: '已入库', pending: '待审核', failed: '失败', uncertain: '结果待核对', cancelled: '已取消',
};
export const editable = (item: UploadItem) => ['draft', 'failed', 'cancelled'].includes(item.status);
export function missingMetadata(metadata: UploadMetadata, admin: boolean): string[] {
  if (metadata.kind === 'emoji') return admin ? [] : ['表情包上传需要管理员权限'];
  const missing: string[] = [];
  if (!metadata.group_ids.length) missing.push('分组');
  if (!metadata.character_ids.length) missing.push('角色');
  if (metadata.pid && !/^\d+$/.test(metadata.pid.trim())) missing.push('有效的数字 PID');
  return missing;
}
export function inferPixiv(name: string): string {
  return /^(\d{5,})_p\d+(?:[_.-].*)?\.(?:jpe?g|png|webp|gif|bmp)$/i.exec(name)?.[1] || '';
}
export function formatBytes(bytes: number) { return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(0)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`; }
export type TagOperation = 'append' | 'replace' | 'remove';
export function mergeTagIds(before: number[], values: number[], operation: TagOperation): number[] {
  return operation === 'replace' ? [...values] : operation === 'remove' ? before.filter(id => !values.includes(id)) : [...new Set([...before, ...values])];
}
