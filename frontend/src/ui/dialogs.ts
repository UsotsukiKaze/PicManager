import { loadClassicScript } from '../compat/scripts';

declare global {
  interface Window {
    PicManagerDialogs: { confirm(message: string): Promise<boolean> };
  }
}

export async function confirmAction(message: string): Promise<boolean> {
  if (!window.PicManagerDialogs) await loadClassicScript('/static/js/dialogs.js?v=20261115');
  return window.PicManagerDialogs.confirm(message);
}
