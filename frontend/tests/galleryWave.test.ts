import { mount, flushPromises } from '@vue/test-utils';
import { h, nextTick } from 'vue';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WaveGrid from '../src/components/WaveGrid.vue';
import { galleryResultKey, waveDelays } from '../src/ui/galleryWave';

interface Turn { frames: Keyframe[]; options: KeyframeAnimationOptions; finish: () => void; cancel: ReturnType<typeof vi.fn> }
let turns: Turn[] = [];
const wrappers: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  vi.useFakeTimers();
  turns = [];
  const styleFor = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation(element => {
    if (element.classList.contains('wave-results')) return { gridTemplateColumns: '100px 100px' } as CSSStyleDeclaration;
    return styleFor(element);
  });
  vi.spyOn(HTMLElement.prototype, 'animate').mockImplementation((frames, options) => {
    let finish!: () => void;
    const finished = new Promise<void>(resolve => { finish = resolve; });
    const cancel = vi.fn(finish);
    turns.push({ frames: frames as Keyframe[], options: options as KeyframeAnimationOptions, finish, cancel });
    return { finished, cancel } as unknown as Animation;
  });
});
afterEach(() => {
  wrappers.splice(0).forEach(wrapper => wrapper.unmount());
  delete document.documentElement.dataset.motion;
  vi.useRealTimers();
});
function grid(items = ['old-a', 'old-b']) {
  const wrapper = mount(WaveGrid, {
    props: { items, requestKey: 'first', scopeKey: 'account', pending: false, failed: false },
    attrs: { style: 'grid-template-columns: 100px 100px' },
    slots: { default: ({ item }: { item: unknown }) => h('button', { class: 'test-card' }, String(item)), empty: () => h('p', 'empty') },
  });
  wrappers.push(wrapper);
  return wrapper;
}
async function finishWave() { await flushPromises(); turns.forEach(turn => turn.finish()); await flushPromises(); }

describe('diagonal gallery wave', () => {
  it('starts in the top right, shares diagonal timing, and caps long mobile grids', () => {
    expect(waveDelays(10, 5)).toEqual([200, 150, 100, 50, 0, 250, 200, 150, 100, 50]);
    expect(waveDelays(4, 2)).toEqual([50, 0, 100, 50]);
    expect(Math.max(...waveDelays(100, 2))).toBeLessThanOrEqual(330);
    expect(waveDelays(1, 5)).toEqual([0]);
    expect(galleryResultKey('a', { character_id: 1, description: '' }, 1))
      .toBe(galleryResultKey('a', { description: undefined, character_id: 1 }, 1));
  });

  it('holds old images until covered and holds the blank backs until data arrives', async () => {
    const wrapper = grid();
    await wrapper.setProps({ requestKey: 'second', pending: true });
    await nextTick();
    expect(wrapper.attributes('data-wave-phase')).toBe('cover');
    expect(wrapper.findAll('.test-card').map(card => card.text())).toEqual(['old-a', 'old-b']);
    expect(turns.map(turn => turn.options.delay)).toEqual([50, 0]);
    expect(wrapper.find('.wave-front').attributes()).toHaveProperty('inert');
    await finishWave();
    expect(wrapper.attributes('data-wave-phase')).toBe('blank');
    await vi.advanceTimersByTimeAsync(2000);
    expect(wrapper.attributes('data-wave-phase')).toBe('blank');
    await wrapper.setProps({ items: ['new-a'], pending: false });
    await vi.advanceTimersByTimeAsync(80);
    await flushPromises();
    expect(wrapper.attributes('data-wave-phase')).toBe('reveal');
    expect(wrapper.find('.test-card').text()).toBe('new-a');
    expect(turns.at(-1)!.frames).toEqual([{ transform: 'rotateY(-180deg)' }, { transform: 'rotateY(-360deg)' }]);
    await finishWave();
    expect(wrapper.attributes('data-wave-phase')).toBe('idle');
    expect(wrapper.find('.wave-front').attributes()).not.toHaveProperty('inert');
  });

  it('coalesces rapid requests during the cover and only reveals the latest result', async () => {
    const wrapper = grid();
    await wrapper.setProps({ requestKey: 'second', pending: true });
    await nextTick();
    await wrapper.setProps({ requestKey: 'third', items: ['intermediate'], pending: false });
    expect(turns).toHaveLength(2);
    await finishWave();
    await wrapper.setProps({ requestKey: 'fourth', pending: true });
    await vi.advanceTimersByTimeAsync(100);
    expect(wrapper.attributes('data-wave-phase')).toBe('blank');
    await wrapper.setProps({ items: ['latest'], pending: false });
    await vi.advanceTimersByTimeAsync(80);
    await finishWave();
    expect(wrapper.find('.test-card').text()).toBe('latest');
    expect(wrapper.attributes('data-wave-phase')).toBe('idle');
  });

  it('returns to blank from an interrupted reveal and recovers from empty/error results', async () => {
    const wrapper = grid();
    await wrapper.setProps({ requestKey: 'second', items: ['second'] });
    await finishWave();
    await vi.advanceTimersByTimeAsync(80);
    await flushPromises();
    expect(wrapper.attributes('data-wave-phase')).toBe('reveal');
    const revealing = turns.at(-1)!;
    await wrapper.setProps({ requestKey: 'third', pending: true });
    await nextTick();
    expect(revealing.cancel).toHaveBeenCalled();
    expect(wrapper.attributes('data-wave-phase')).toBe('cover');
    await finishWave();
    await wrapper.setProps({ failed: true, pending: false });
    await vi.advanceTimersByTimeAsync(80);
    await flushPromises();
    expect(wrapper.find('.test-card').exists()).toBe(false);
    expect(wrapper.text()).toBe('empty');
    expect(wrapper.attributes('data-wave-phase')).toBe('idle');
    await wrapper.setProps({ failed: false, items: ['retry'], refreshKey: 1 });
    expect(wrapper.find('.test-card').text()).toBe('retry');
  });

  it('settles immediately when reduced motion is enabled and cancels work on unmount', async () => {
    const wrapper = grid();
    await wrapper.setProps({ requestKey: 'second', pending: true });
    await nextTick();
    document.documentElement.dataset.motion = 'reduced';
    await vi.advanceTimersByTimeAsync(0);
    await flushPromises();
    expect(wrapper.attributes('data-wave-phase')).toBe('idle');
    expect(turns.every(turn => turn.cancel.mock.calls.length)).toBe(true);
    await wrapper.setProps({ items: ['reduced'], pending: false });
    expect(wrapper.find('.test-card').text()).toBe('reduced');
    delete document.documentElement.dataset.motion;
    await wrapper.setProps({ requestKey: 'third', pending: true });
    await nextTick();
    wrapper.unmount(); wrappers.pop();
    expect(turns.every(turn => turn.cancel.mock.calls.length)).toBe(true);
    await flushPromises();
  });
});
