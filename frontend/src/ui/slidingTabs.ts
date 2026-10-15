import type { ObjectDirective } from 'vue';
import { reducedMotion } from '../state/appearance';
import '../styles/gallery-wave.css';

const states = new WeakMap<HTMLElement, { schedule: () => void; dispose: () => void }>();
export const vSlidingTabs: ObjectDirective<HTMLElement> = {
  mounted(element) {
    const indicator = document.createElement('span');
    indicator.className = 'gallery-tab-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    element.classList.add('gallery-sliding-tabs');
    element.prepend(indicator);
    let initialized = false;
    let selected: HTMLElement | null = null;
    let frame = 0;
    function position() {
      frame = 0;
      const button = element.querySelector<HTMLElement>('button[aria-pressed="true"]');
      indicator.hidden = !button;
      if (!button || !element.getClientRects().length) return;
      const container = element.getBoundingClientRect(), target = button.getBoundingClientRect();
      indicator.style.transition = initialized ? '' : 'none';
      indicator.style.width = `${target.width}px`;
      indicator.style.height = `${target.height}px`;
      indicator.style.transform = `translate(${target.left - container.left + element.scrollLeft}px, ${target.top - container.top + element.scrollTop}px)`;
      if (initialized && selected !== button && (target.left < container.left || target.right > container.right)) {
        element.scrollTo({ left: element.scrollLeft + target.left - container.left - 12, behavior: reducedMotion() ? 'instant' : 'smooth' });
      }
      selected = button;
      initialized = true;
    }
    const schedule = () => { if (!frame) frame = requestAnimationFrame(position); };
    const mutations = new MutationObserver(schedule);
    mutations.observe(element, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-pressed'] });
    const resize = new ResizeObserver(schedule);
    resize.observe(element);
    // Font loading can change a long role name without resizing the scroll container.
    document.fonts?.addEventListener('loadingdone', schedule);
    schedule();
    states.set(element, { schedule, dispose: () => {
      cancelAnimationFrame(frame); mutations.disconnect(); resize.disconnect();
      document.fonts?.removeEventListener('loadingdone', schedule);
      indicator.remove();
    } });
  },
  updated(element) { states.get(element)?.schedule(); },
  beforeUnmount(element) { states.get(element)?.dispose(); states.delete(element); },
};
