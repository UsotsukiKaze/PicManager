import { computed, onScopeDispose, ref, watch } from 'vue';
import { defineStore } from 'pinia';

export type Theme = 'system' | 'light' | 'dark';
const key = 'picmanager.appearance';
function read() {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || '{}');
    return { theme: (['system', 'light', 'dark'].includes(saved.theme) ? saved.theme : 'system') as Theme, reduced: saved.reduced === true };
  } catch { return { theme: 'system' as Theme, reduced: false }; }
}
export function reducedMotion() {
  return document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion:reduce)').matches;
}
export const useAppearance = defineStore('appearance', () => {
  const saved = read();
  const theme = ref<Theme>(saved.theme);
  const reduced = ref(saved.reduced);
  const system = matchMedia('(prefers-color-scheme:dark)');
  const systemDark = ref(system.matches);
  const changed = (event: MediaQueryListEvent) => { systemDark.value = event.matches; };
  system.addEventListener('change', changed);
  onScopeDispose(() => system.removeEventListener('change', changed));
  const resolvedTheme = computed(() => theme.value === 'system' ? (systemDark.value ? 'dark' : 'light') : theme.value);
  watch([resolvedTheme, reduced], ([mode, quiet]) => {
    document.documentElement.dataset.theme = mode;
    document.documentElement.dataset.motion = quiet ? 'reduced' : 'full';
  }, { immediate: true, flush: 'sync' });
  watch([theme, reduced], ([mode, quiet]) => {
    try { localStorage.setItem(key, JSON.stringify({ theme: mode, reduced: quiet })); } catch { /* Appearance works without persistence. */ }
  }, { flush: 'sync' });
  return { theme, reduced, resolvedTheme };
});
