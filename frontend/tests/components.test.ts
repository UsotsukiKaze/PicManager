import { mount, flushPromises } from '@vue/test-utils';
import { afterEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createContext, runInContext } from 'node:vm';
import ImageCard from '../src/components/ImageCard.vue';
import EntityPicker from '../src/components/EntityPicker.vue';
import type { ImageCardRecord } from '../src/api/types';
import type { PinyinEngine } from '../src/api/phonetics';

afterEach(() => { delete window.pinyinPro; document.querySelectorAll('script').forEach(node => node.remove()); });

const image: ImageCardRecord = { image_id: 'ABCD123456', pid: '123_p0', age_rating: 'r12', characters: [{ id: 1, name: '角色' }], groups: [{ id: 2, name: '分组' }] };
describe('card interaction', () => {
  it('does not download restricted images before explicit reveal', async () => {
    const wrapper = mount(ImageCard, { props: { image: { ...image, age_rating: 'r18' } } });
    expect(wrapper.find('.modern-image-open img').attributes('src')).toBeUndefined();
    await wrapper.find('.modern-reveal').trigger('click');
    expect(wrapper.find('.modern-image-open img').attributes('src')).toContain('/resource/thumbs/');
  });
  it('hides action state after closing and resumes only upon leaving or keyboard input', async () => {
    const wrapper = mount(ImageCard, { props: { image, suppressActions: true } });
    expect(wrapper.classes()).toContain('suppress-actions');
    await wrapper.trigger('pointerleave');
    expect(wrapper.emitted('resume')).toHaveLength(1);
    expect(wrapper.find('.modern-validation').exists()).toBe(false);
  });
});
describe('entity picker', () => {
  it('matches aliases and bounds rendered options', async () => {
    const items = Array.from({ length: 200 }, (_, id) => ({ id, name: `分组${id}`, aliases: id === 177 ? ['特别别名'] : [] }));
    const wrapper = mount(EntityPicker, { props: { label: '分组', items } });
    await wrapper.find('input').trigger('focus');
    expect(wrapper.findAll('[role=option]')).toHaveLength(61);
    await wrapper.find('input').setValue('特别别名');
    expect(wrapper.findAll('[role=option]')).toHaveLength(2);
    await wrapper.find('input').trigger('keydown', { key: 'Enter' });
    expect(wrapper.emitted('update:modelValue')?.[0]).toEqual([177]);
  });
  it('loads phonetic search only when Latin text is entered', async () => {
    const wrapper = mount(EntityPicker, { props: { label: '角色', items: [{ id: 9, name: '初音未来' }] } });
    await wrapper.find('input').trigger('focus');
    expect(document.scripts).toHaveLength(0);
    await wrapper.find('input').setValue('cywl');
    const script = document.querySelector('script')!;
    expect(script.src).toContain('/static/vendor/pinyin-pro-3.29.2.min.js');
    const context = createContext({ setTimeout: (callback: () => void) => callback() });
    runInContext(readFileSync(resolve('../static/vendor/pinyin-pro-3.29.2.min.js'), 'utf8'), context);
    window.pinyinPro = context.pinyinPro as PinyinEngine;
    script.dispatchEvent(new Event('load'));
    await flushPromises();
    expect(wrapper.text()).toContain('初音未来');
    wrapper.unmount();
  });
});
