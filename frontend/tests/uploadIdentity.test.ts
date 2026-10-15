import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { uploadDigest, uploadId } from '../src/ui/uploadIdentity';

afterEach(() => vi.unstubAllGlobals());
describe('HTTP upload identity compatibility', () => {
  it('keeps SHA-256 identities identical across native and fallback paths', async () => {
    const bytes = new Uint8Array(1024 * 1024 + 17).map((_, n) => n % 251);
    const file = new Blob([bytes]);
    const expected = createHash('sha256').update(bytes).digest('hex');
    vi.stubGlobal('crypto', webcrypto);
    expect(await uploadDigest(file)).toBe(expected);
    vi.stubGlobal('crypto', { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) });
    expect(await uploadDigest(file)).toBe(expected);
    expect(uploadId()).toMatch(/^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
    expect(uploadId()).not.toBe(uploadId());
  });
  it('handles a present but unusable crypto digest without rejecting the file', async () => {
    vi.stubGlobal('crypto', { subtle: { digest: async () => { throw new Error('restricted'); } } });
    expect(await uploadDigest(new Blob(['abc']))).toBe('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
  });
});
