import { loadClassicScript, PINYIN_SCRIPT } from '../compat/scripts';

export interface PinyinEngine {
  pinyin(text: string, options: { toneType: 'none'; pattern?: 'first' }): string;
}

export async function loadPinyin(): Promise<PinyinEngine> {
  if (!window.pinyinPro?.pinyin) await loadClassicScript(PINYIN_SCRIPT);
  if (!window.pinyinPro?.pinyin) throw new Error('拼音词库暂时不可用');
  return window.pinyinPro;
}
