import { reducedMotion } from '../state/appearance';
import { motionEasing } from './motion';

/** Shared by resource pages so interrupted filter transitions keep their current frame. */
export function useFilterMotion() {
  const animations = new WeakMap<HTMLElement, Animation>();
  const frames = new WeakMap<HTMLElement, { height: string; opacity: number; paddingBottom: string }>();
  function filterMotion(element: Element, done: () => void, opening: boolean) {
    const node = element as HTMLElement;
    const interrupted = frames.get(node);
    frames.delete(node);
    if (reducedMotion()) { node.style.overflow = ''; done(); return; }
    const gap = getComputedStyle(node).getPropertyValue('--filter-gap').trim() || '16px';
    const height = `${(node.firstElementChild as HTMLElement).offsetHeight + Number.parseFloat(gap)}px`;
    node.style.overflow = 'hidden';
    const from = interrupted || { height: opening ? '0px' : height, opacity: opening ? 0 : 1, paddingBottom: opening ? '0px' : gap };
    const to = { height: opening ? height : '0px', opacity: opening ? 1 : 0, paddingBottom: opening ? gap : '0px' };
    const animation = node.animate([from, to], { duration: opening ? 360 : 280, easing: motionEasing() });
    animations.set(node, animation);
    const finish = () => { if (animations.get(node) !== animation) return; animations.delete(node); node.style.overflow = ''; done(); };
    void animation.finished.then(finish, finish);
  }
  function cancelFilterMotion(element: Element) {
    const node = element as HTMLElement;
    const animation = animations.get(node);
    if (!animation) return;
    const style = getComputedStyle(node);
    frames.set(node, { height: style.height, opacity: Number(style.opacity), paddingBottom: style.paddingBottom });
    animations.delete(node); animation.cancel(); node.style.overflow = '';
  }
  return { filterMotion, cancelFilterMotion };
}
