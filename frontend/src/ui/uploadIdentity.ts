/** Local file identity only; server-side content validation remains authoritative. */
const hex = (bytes: Uint8Array) => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');

export async function uploadDigest(file: Blob): Promise<string> {
  if (globalThis.crypto?.subtle) {
    try { return hex(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))); }
    catch { /* Some browsers expose SubtleCrypto but restrict its use. */ }
  }
  // Load only on browsers without usable SubtleCrypto. Hash in bounded chunks
  // and yield between them so large selections do not freeze the workbench.
  const { sha256 } = await import('@noble/hashes/sha2.js');
  const digest = sha256.create();
  for (let offset = 0; offset < file.size; offset += 1024 * 1024) {
    digest.update(new Uint8Array(await file.slice(offset, offset + 1024 * 1024).arrayBuffer()));
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  return hex(digest.digest());
}

export function uploadId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return crypto.randomUUID();
  // getRandomValues is also available in ordinary HTTP contexts. This ID is a
  // UI key, never an authorization token or a replacement for the file digest.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 15) | 64;
  bytes[8] = (bytes[8]! & 63) | 128;
  const value = hex(bytes);
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}
