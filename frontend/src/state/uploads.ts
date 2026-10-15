import { computed, markRaw, ref, watch } from 'vue';
import { defineStore } from 'pinia';
import { requestJSON } from '../api/http';
import { invalidateDomain } from './client';
import { useSession } from './session';
import { useWorkspace } from './workspace';
import { uploadDigest, uploadId } from '../ui/uploadIdentity';
import { cloneMetadata, defaultMetadata, editable, formatBytes, inferPixiv, missingMetadata, type UploadCapabilities, type UploadItem, type UploadMetadata, type UploadResult, type UploadStatus } from '../ui/uploadModel';

type SavedDraft = { digest: string; name: string; metadata: UploadMetadata };
type Queue = { add: (value: Record<string, unknown>) => number; update: (id: number, patch: Record<string, unknown>) => void; discard?: (id: number) => void };
const queue = () => (window as unknown as { uploadQueue?: Queue }).uploadQueue;
export const useUploads = defineStore('uploads', () => {
  const session = useSession(), workspace = useWorkspace();
  const items = ref<UploadItem[]>([]), adding = ref(false), preparing = ref(false), reviewing = ref(false);
  const defaults = ref(defaultMetadata()), restored = ref<SavedDraft[]>([]), capabilities = ref<UploadCapabilities>();
  const capabilityError = ref('');
  let generation = 0, active = 0, addChain = Promise.resolve(), boot: Promise<void> | undefined;
  const ready = computed(() => items.value.filter(item => editable(item) && !missingMetadata(item.metadata, session.isAdmin).length));
  const busy = computed(() => preparing.value || items.value.some(item => ['checking', 'queued', 'uploading', 'processing', 'reviewing'].includes(item.status)));
  const storageKey = () => `picmanager.upload-drafts.${session.identity}`;
  function loadDrafts() {
    try { restored.value = JSON.parse(sessionStorage.getItem(storageKey()) || '[]'); } catch { restored.value = []; }
  }
  loadDrafts();
  function saveDrafts() {
    const drafts = items.value.filter(item => editable(item) && item.digest).map(item => ({ digest: item.digest, name: item.file.name, metadata: cloneMetadata(item.metadata) }));
    const present = new Set(items.value.map(item => item.digest));
    try { sessionStorage.setItem(storageKey(), JSON.stringify([...drafts, ...restored.value.filter(item => !present.has(item.digest))].slice(0, 500))); } catch { /* Draft storage is optional. */ }
  }
  watch(items, saveDrafts, { deep: true });
  watch(() => session.identity, () => {
    generation++; boot = undefined; capabilities.value = undefined; capabilityError.value = '';
    if (reviewing.value) window.ui?.closeModal();
    for (const item of items.value) { if (item.queueId) queue()?.discard?.(item.queueId); URL.revokeObjectURL(item.url); }
    items.value = []; defaults.value = defaultMetadata(); restored.value = []; active = 0; preparing.value = false; reviewing.value = false; loadDrafts();
  });
  async function configure() {
    const token = generation;
    try {
      const result = await requestJSON<UploadCapabilities>('/api/upload/capabilities');
      if (!Number.isFinite(result.max_file_size) || result.max_file_size <= 0 || !Array.isArray(result.extensions)) throw new Error('Invalid upload limits');
      if (token === generation) { capabilities.value = result; capabilityError.value = ''; }
    }
    catch { if (token === generation) capabilityError.value = '无法读取上传限制，请重试'; }
  }
  function stage(item: UploadItem, status: UploadStatus, message = '') {
    item.status = status; item.message = message;
    if (item.queueId) queue()?.update(item.queueId, { status: status === 'pending' ? 'success' : status === 'uncertain' ? 'attention' : status === 'reviewing' ? 'attention' : status,
      message: message || (status === 'pending' ? '已提交审核' : ''), progress: item.progress,
      retry: status === 'failed' ? () => submit([item.id]) : null });
  }
  function addFiles(files: File[]) {
    const token = generation;
    addChain = addChain.catch(() => {}).then(async () => {
      if (token !== generation) return;
      adding.value = true;
      try {
        if (!capabilities.value) await configure();
        if (!capabilities.value) return;
        const skipped: string[] = [];
        for (const file of files) {
          if (token !== generation) return;
          const ext = file.name.split('.').pop()?.toLowerCase() || '';
          if (!capabilities.value.extensions.includes(ext)) { skipped.push(`${file.name}：格式不支持`); continue; }
          if (!file.size || file.size > capabilities.value.max_file_size) { skipped.push(`${file.name}：${!file.size ? '文件为空' : '超过 ' + formatBytes(capabilities.value.max_file_size)}`); continue; }
          const url = URL.createObjectURL(file);
          try {
            // Decode sequentially so a large selection does not allocate all full-size images at once.
            const dimensions = await new Promise<{ width: number; height: number }>((resolve, reject) => {
              const image = new Image(); const timer = setTimeout(() => { image.src = ''; reject(new Error('读取超时')); }, 15000);
              image.onload = () => { clearTimeout(timer); resolve({ width: image.naturalWidth, height: image.naturalHeight }); image.src = ''; };
              image.onerror = () => { clearTimeout(timer); reject(new Error('图片无法解码')); }; image.src = url;
            });
            const digest = await uploadDigest(file);
            if (token !== generation) { URL.revokeObjectURL(url); return; }
            if (items.value.some(item => item.digest === digest)) { URL.revokeObjectURL(url); skipped.push(`${file.name}：已在列表中`); continue; }
            const saved = restored.value.find(item => item.digest === digest);
            const metadata = saved ? cloneMetadata(saved.metadata) : cloneMetadata(defaults.value);
            const pid = inferPixiv(file.name); if (!saved && pid) metadata.pid = pid;
            items.value.push({ id: uploadId(), file: markRaw(file), url, digest, ...dimensions, metadata, status: 'draft', progress: 0, message: '', pidInferred: !saved && !!pid });
            restored.value = restored.value.filter(item => item.digest !== digest);
          } catch { URL.revokeObjectURL(url); skipped.push(`${file.name}：图片读取失败`); }
        }
        if (skipped.length) workspace.notify(`跳过 ${skipped.length} 个文件：${skipped.slice(0, 3).join('；')}${skipped.length > 3 ? '…' : ''}`, 'info');
      } finally { adding.value = false; saveDrafts(); }
    });
    return addChain;
  }
  async function ensureTransport() {
    if (!boot) boot = import('../compat/bridge').then(async ({ ensureLegacy }) => { await ensureLegacy(); }).catch(error => { boot = undefined; throw error; });
    await boot;
    window.auth.updateUI?.();
  }
  function finish(item: UploadItem, result: UploadResult) {
    item.result = result; item.progress = 100;
    const pending = result.image_id === 'pending' || ['pending', 'pending_review'].includes(result.status || '');
    stage(item, result.status === 'cancelled' ? 'cancelled' : pending ? 'pending' : 'success', pending ? '已提交，等待管理员审核' : result.message || '入库完成');
    invalidateDomain(item.snapshot?.kind === 'emoji' ? '/emojis' : '/upload'); saveDrafts();
  }
  async function run(item: UploadItem, token: number) {
    if (token !== generation || !item.snapshot) return;
    stage(item, 'uploading');
    try {
      const metadata = item.snapshot;
      const progress = (value: number) => {
        if (token !== generation) return;
        item.progress = value; stage(item, value >= 100 ? 'processing' : 'uploading', value >= 100 ? '文件已传输，等待处理' : `已上传 ${value}%`);
      };
      const emojiForm = new FormData();
      if (metadata.kind === 'emoji') {
        emojiForm.append('file', item.file);
        for (const key of ['group_ids', 'character_ids', 'emotion_ids'] as const) emojiForm.append(key, JSON.stringify(metadata[key]));
        if (metadata.description) emojiForm.append('description', metadata.description);
      }
      const result: UploadResult = metadata.kind === 'emoji'
        ? await window.api.uploadWithProgress('/emojis/upload', emojiForm, progress)
        : await window.api.uploadSingleImage(item.file, metadata, progress);
      if (token !== generation) return;
      if (result.status === 'duplicate') {
        item.result = result; stage(item, 'attention', '发现相似图片，等待比对');
      } else finish(item, result);
    } catch (error) {
      if (token !== generation) return;
      const reason = error as Error & { status?: number; outcomeUnknown?: boolean };
      // A lost response can follow a committed write. Do not offer an automatic retry.
      const uncertain = reason.outcomeUnknown || !reason.status || reason.status >= 500;
      stage(item, uncertain ? 'uncertain' : 'failed', uncertain ? '服务器结果未确认，请先到图库核对，避免重复提交' : reason.message || '上传失败');
      if (reason.status === 401) window.dispatchEvent(new Event('picmanager-session-expired'));
    }
  }
  function pump() {
    const token = generation;
    while (active < 3) {
      const item = items.value.find(item => item.status === 'queued'); if (!item) break;
      active++; item.status = 'uploading';
      void run(item, token).finally(() => { if (token === generation) { active--; pump(); } });
    }
  }
  async function submit(ids = ready.value.map(item => item.id)) {
    if (preparing.value) return;
    const pending = items.value.filter(item => ids.includes(item.id) && editable(item) && !missingMetadata(item.metadata, session.isAdmin).length);
    if (!pending.length) return;
    const token = generation; preparing.value = true;
    try {
      await ensureTransport(); if (token !== generation) return;
      for (const item of pending) {
        if (!editable(item) || missingMetadata(item.metadata, session.isAdmin).length) continue;
        item.snapshot = cloneMetadata(item.metadata); item.progress = 0; item.result = undefined;
        item.queueId ??= queue()?.add({ name: item.file.name, size: item.file.size, retry: () => submit([item.id]),
          review: () => import('../router').then(({ router }) => router.push({ path: '/upload', query: { state: 'attention' } })) });
        stage(item, 'queued', '等待上传');
      }
      pump();
    } catch (error) { if (token === generation) workspace.notify((error as Error).message || '上传组件加载失败，请重试', 'error'); }
    finally { if (token === generation) preparing.value = false; }
  }
  async function compare(item: UploadItem) {
    if (reviewing.value || item.status !== 'attention' || !item.result) return;
    const token = generation; reviewing.value = true; stage(item, 'reviewing');
    try {
      await ensureTransport();
      await window.auth.loadFeature('upload');
      if (token !== generation) return;
      const decision = await window.upload!.resolveDuplicateChoice(item.result, item.url);
      if (token !== generation) return;
      if (!decision || decision.action === 'later') { stage(item, 'attention', '稍后继续比对'); return; }
      const choice = window.upload!.duplicateDecisionRequest(decision);
      stage(item, 'processing', '正在保存比对结果');
      const result = await window.api.resolveDuplicateImage(item.result.duplicate_token, choice.keep, choice.metadataSources);
      if (token === generation) finish(item, result);
    } catch (error) {
      if (token === generation) {
        const reason = error as Error & { status?: number };
        stage(item, !reason.status || reason.status >= 500 ? 'uncertain' : reason.status === 410 ? 'cancelled' : 'attention',
          reason.status === 410 ? '比对凭据已过期，可重新提交' : !reason.status || reason.status >= 500 ? '比对结果未确认，请先到图库核对' : reason.message || '比对结果保存失败，请重试');
      }
    }
    finally { if (token === generation) reviewing.value = false; }
  }
  async function cancelAttention(item: UploadItem) {
    if (item.status !== 'attention' || reviewing.value) return;
    const token = generation; stage(item, 'processing', '正在放弃本次提交');
    try {
      await ensureTransport();
      const result = await window.api.resolveDuplicateImage(item.result?.duplicate_token, 'cancel');
      if (token === generation) finish(item, result);
    } catch (error) {
      if (token === generation) stage(item, (error as { status?: number }).status === 410 ? 'cancelled' : 'attention', (error as Error).message);
    }
  }
  function remove(ids: string[]) {
    const discarded = items.value.filter(item => ids.includes(item.id) && !['queued', 'uploading', 'processing', 'attention', 'reviewing'].includes(item.status));
    for (const item of discarded) { URL.revokeObjectURL(item.url); if (item.queueId) queue()?.update(item.queueId, { retry: null }); }
    items.value = items.value.filter(item => !discarded.includes(item)); saveDrafts();
  }
  function cancelQueued() { for (const item of items.value.filter(item => item.status === 'queued')) stage(item, 'cancelled', '已取消排队'); }
  function resumeUnknown(item: UploadItem) { if (item.status === 'uncertain') { item.status = 'draft'; item.message = ''; } }
  function discardDrafts() { restored.value = []; saveDrafts(); }
  window.addEventListener('beforeunload', event => { if (busy.value || items.value.some(item => item.status === 'attention')) { event.preventDefault(); event.returnValue = ''; } });
  return { items, defaults, restored, capabilities, capabilityError, adding, preparing, reviewing, ready, busy, configure, addFiles, submit, compare, cancelAttention, remove, cancelQueued, resumeUnknown, discardDrafts };
});
