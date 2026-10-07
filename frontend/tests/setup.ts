import { beforeEach, vi } from 'vitest';

beforeEach(() => {
  const create = document.createElement.bind(document);
  // Unit tests dispatch resource events explicitly; never fetch scripts from localhost.
  vi.spyOn(document, 'createElement').mockImplementation(((tag: string, options?: ElementCreationOptions) => {
    const node = create(tag, options);
    if (tag.toLowerCase() === 'script') (node as HTMLScriptElement).type = 'application/x-test';
    return node;
  }) as typeof document.createElement);
});
