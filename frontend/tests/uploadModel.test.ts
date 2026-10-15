import { describe, expect, it } from 'vitest';
import { defaultMetadata, inferPixiv, mergeTagIds, missingMetadata } from '../src/ui/uploadModel';

describe('unified upload metadata', () => {
  it('only extracts a Pixiv PID from an explicit page filename', () => {
    expect(inferPixiv('12345678_p0.png')).toBe('12345678');
    expect(inferPixiv('12345678_p12_master1200.jpg')).toBe('12345678');
    expect(inferPixiv('12345678.jpg')).toBe('');
    expect(inferPixiv('holiday-12345678_p0.png')).toBe('');
  });
  it('keeps per-file tag exceptions when appending and removing batch labels', () => {
    expect(mergeTagIds([1, 2], [2, 3], 'append')).toEqual([1, 2, 3]);
    expect(mergeTagIds([1, 2], [2, 3], 'remove')).toEqual([1]);
    expect(mergeTagIds([1, 2], [], 'replace')).toEqual([]);
  });
  it('validates each resource with its own permission and metadata requirements', () => {
    const image = defaultMetadata();
    expect(missingMetadata(image, true)).toEqual(['分组', '角色']);
    image.group_ids = [1]; image.character_ids = [1];
    expect(missingMetadata(image, false)).toEqual([]);
    image.pid = '123_p0'; expect(missingMetadata(image, true)).toEqual(['有效的数字 PID']);
    expect(missingMetadata(defaultMetadata('emoji'), false)).toEqual(['表情包上传需要管理员权限']);
    expect(missingMetadata(defaultMetadata('emoji'), true)).toEqual([]);
  });
});
