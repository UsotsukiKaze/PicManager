/** Shared classic resources used by both native components and the DOM island. */
export const PINYIN_SCRIPT = '/static/vendor/pinyin-pro-3.29.2.min.js?v=3.29.2';
const pending = new Map<string, Promise<void>>();

export function loadClassicScript(src: string): Promise<void> {
  const url = new URL(src, location.origin).href;
  const active = pending.get(url);
  if (active) return active;
  const existing = Array.from(document.scripts).find(item => item.src === url);
  if (existing?.dataset.loaded === 'true') return Promise.resolve();
  const loading = new Promise<void>((resolve, reject) => {
    const node = existing || document.createElement('script');
    node.async = false;
    if (!existing) node.src = url;
    const loaded = () => { node.dataset.loaded = 'true'; dispose(); resolve(); };
    const failed = () => { dispose(); node.remove(); reject(new Error('功能模块加载失败，请重试')); };
    const dispose = () => { node.removeEventListener('load', loaded); node.removeEventListener('error', failed); };
    node.addEventListener('load', loaded, { once: true });
    node.addEventListener('error', failed, { once: true });
    if (!existing) document.body.append(node);
  }).finally(() => { pending.delete(url); });
  pending.set(url, loading);
  return loading;
}
