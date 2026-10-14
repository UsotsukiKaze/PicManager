import { mount } from '@vue/test-utils';
import { defineComponent, KeepAlive, nextTick, ref } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DecodeText from '../src/components/DecodeText.vue';

let intersect: IntersectionObserverCallback;
let raf: FrameRequestCallback | undefined;
const disconnect = vi.fn();
const wrappers: { unmount(): void }[] = [];
const visual = (wrapper: ReturnType<typeof mount>) => wrapper.find('[data-decoding]').exists() || wrapper.attributes('data-decoding')
  ? wrapper.findAll('.decode-text-glyph').map(node => node.text()).join('')
  : wrapper.find('.decode-text-readable').text();

beforeEach(() => {
  raf = undefined;
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: IntersectionObserverCallback) { intersect = callback; }
    observe() {}
    disconnect = disconnect;
  });
  vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => { raf = callback; return 1; }));
  vi.stubGlobal('cancelAnimationFrame', vi.fn(() => { raf = undefined; }));
});
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount());
  delete document.documentElement.dataset.motion;
  vi.unstubAllGlobals();
});
function enter() { intersect([{ isIntersecting: true } as IntersectionObserverEntry], {} as IntersectionObserver); }
function render(props: { text: string; mode?: 'number'; ready?: boolean }) {
  const wrapper = mount(DecodeText, { props });
  wrappers.push(wrapper);
  return wrapper;
}

describe('archive text decoding', () => {
  it('waits for visibility and real data, preserves separators, and settles to the exact count', async () => {
    const wrapper = render({ text: '—', mode: 'number', ready: false });
    enter();
    expect(raf).toBeUndefined();
    await wrapper.setProps({ text: '12,486', ready: true });
    expect(wrapper.attributes('data-decoding')).toBe('true');
    expect(visual(wrapper)).toBe('··,···');
    raf!(performance.now() + 100);
    await nextTick();
    expect(visual(wrapper)).toMatch(/^\d{2},\d{3}$/);
    expect(wrapper.find('.decode-text-readable').text()).toBe('12,486');
    raf!(performance.now() + 2000);
    await nextTick();
    expect(visual(wrapper)).toBe('12,486');
    expect(wrapper.attributes('data-decoding')).toBeUndefined();
    await wrapper.setProps({ text: '12,500' });
    expect(visual(wrapper)).toBe('12,500');
    expect(raf).toBeUndefined();
  });

  it('shows zero and reduced motion content immediately', async () => {
    const zero = render({ text: '0', mode: 'number' });
    enter();
    expect(raf).toBeUndefined();
    expect(visual(zero)).toBe('0');
    document.documentElement.dataset.motion = 'reduced';
    const reduced = render({ text: 'ARCHIVE' });
    enter();
    await nextTick();
    expect(visual(reduced)).toBe('ARCHIVE');
    expect(raf).toBeUndefined();
  });

  it('stops a running animation when reduced motion is enabled', async () => {
    const wrapper = render({ text: 'ARCHIVE' });
    enter();
    await nextTick();
    expect(wrapper.attributes('data-decoding')).toBe('true');
    document.documentElement.dataset.motion = 'reduced';
    // MutationObserver delivery is asynchronous in the DOM implementation.
    await new Promise(resolve => setTimeout(resolve, 0));
    await nextTick();
    expect(visual(wrapper)).toBe('ARCHIVE');
    expect(raf).toBeUndefined();
  });

  it('cancels on deactivation and keeps the final text on a cached return', async () => {
    const shown = ref(true);
    const wrapper = mount(defineComponent({
      components: { KeepAlive, DecodeText },
      setup: () => ({ shown }),
      template: '<KeepAlive><DecodeText v-if="shown" text="ARCHIVE"/></KeepAlive>',
    }));
    wrappers.push(wrapper);
    enter();
    await nextTick();
    shown.value = false;
    await nextTick();
    expect(raf).toBeUndefined();
    shown.value = true;
    await nextTick();
    expect(visual(wrapper)).toBe('ARCHIVE');
    expect(wrapper.find('[data-decoding]').exists()).toBe(false);
    expect(disconnect).toHaveBeenCalled();
  });
});
