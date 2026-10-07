import { afterEach, expect, it } from 'vitest';
import { loadClassicScript } from '../src/compat/scripts';

afterEach(() => { document.querySelectorAll('script').forEach(node => node.remove()); });

it('shares concurrent resource requests between native and compatibility consumers', async () => {
  const native = loadClassicScript('/static/vendor/shared.js');
  const legacy = loadClassicScript('/static/vendor/shared.js');
  expect(native).toBe(legacy);
  expect(document.scripts).toHaveLength(1);
  document.scripts[0].dispatchEvent(new Event('load'));
  await Promise.all([native, legacy]);
  await loadClassicScript('/static/vendor/shared.js');
  expect(document.scripts).toHaveLength(1);
});

it('removes a failed resource and permits retry', async () => {
  const failed = loadClassicScript('/static/vendor/retry.js');
  const rejected = expect(failed).rejects.toThrow('功能模块加载失败');
  document.scripts[0].dispatchEvent(new Event('error'));
  await rejected;
  expect(document.scripts).toHaveLength(0);
  const retry = loadClassicScript('/static/vendor/retry.js');
  document.scripts[0].dispatchEvent(new Event('load'));
  await retry;
});

it('waits on an existing pending script without inserting it twice', async () => {
  const node = document.createElement('script');
  node.src = '/static/vendor/existing.js';
  document.body.append(node);
  const ready = loadClassicScript('/static/vendor/existing.js');
  expect(document.scripts).toHaveLength(1);
  node.dispatchEvent(new Event('load'));
  await ready;
  expect(node.dataset.loaded).toBe('true');
});
