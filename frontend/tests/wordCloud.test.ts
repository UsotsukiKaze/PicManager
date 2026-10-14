import { describe, expect, it } from 'vitest';
import { layoutWordCloud } from '../src/ui/wordCloud';

const groups = ['原神', '崩坏：星穹铁道', '明日方舟', '东方Project', '蔚蓝档案', '碧蓝航线', '鸣潮', '绝区零']
  .map((name, index) => ({ id: index + 1, name, image_count: 500 / (index + 1) ** 2 }));
const measure = (name: string, size: number) => [...name].reduce((sum, character) => sum + (/[^\x00-\x7F]/.test(character) ? size : size * .6), 0);

describe('word cloud layout', () => {
  it.each([{ width: 388, height: 220 }, { width: 240, height: 220 }, { width: 800, height: 220 }])('retains all words without overlaps within $width px', bounds => {
    const words = layoutWordCloud(groups, bounds, measure);
    expect(words).toHaveLength(groups.length);
    expect(words[0]!.size).toBeGreaterThan(words.at(-1)!.size);
    words.forEach((word, index) => {
      expect(word.x).toBeGreaterThanOrEqual(0);
      expect(word.y).toBeGreaterThanOrEqual(0);
      expect(word.x + word.width).toBeLessThanOrEqual(bounds.width);
      expect(word.y + word.height).toBeLessThanOrEqual(bounds.height);
      words.slice(index + 1).forEach(other => {
        expect(word.x + word.width <= other.x || other.x + other.width <= word.x || word.y + word.height <= other.y || other.y + other.height <= word.y).toBe(true);
      });
    });
    expect(layoutWordCloud(groups, bounds, measure)).toEqual(words);
  });
  it('fits long names on one line and tolerates equal counts and empty data', () => {
    const bounds = { width: 240, height: 220 };
    const long = '测试极长分组名称'.repeat(6);
    const words = layoutWordCloud([{ id: 1, name: long }, { id: 2, name: '无库存分组' }], bounds, measure);
    expect(words).toHaveLength(2);
    expect(measure(long, words[0]!.size)).toBeLessThanOrEqual(bounds.width - 20);
    expect(layoutWordCloud([], bounds, measure)).toEqual([]);
  });
});
