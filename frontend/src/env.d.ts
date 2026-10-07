/// <reference types="vite/client" />
import type { PinyinEngine } from './api/phonetics';
declare global {
  interface Window {
    __PICMANAGER_MODERN__?: boolean;
    pinyinPro?: PinyinEngine;
    // Imperative controllers are restricted to the compatibility boundary.
    auth: Record<string, any>;
    ui: Record<string, any>;
    api: Record<string, any>;
    pixivOL?: Record<string, any>;
    upload?: Record<string, any>;
  }
}
export {};
