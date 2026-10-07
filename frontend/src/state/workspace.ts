import { ref, shallowRef, watch } from 'vue';
import { defineStore } from 'pinia';
import type { ImageFilters } from '../api/types';

function saved<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; }
}
export const useWorkspace = defineStore('workspace', () => {
  const collapsed = ref(saved<boolean>('picmanager.sidebarCollapsed', false) === true);
  const filters = ref<ImageFilters>({});
  const page = ref(1);
  const toasts = shallowRef<Array<{ id: number; message: string; tone: string }>>([]);
  let nextToast = 0;
  watch(collapsed, value => { try { localStorage.setItem('picmanager.sidebarCollapsed', JSON.stringify(value)); } catch { /* Optional persistence. */ } });
  function notify(message: string, tone = 'info') {
    const id = ++nextToast;
    toasts.value = [...toasts.value.slice(-3), { id, message, tone }];
    setTimeout(() => { toasts.value = toasts.value.filter(item => item.id !== id); }, 5000);
  }
  return { collapsed, filters, page, toasts, notify };
});
