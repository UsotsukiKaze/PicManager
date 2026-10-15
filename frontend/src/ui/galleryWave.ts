/** Diagonals travel from the top right to the bottom left at every breakpoint. */
export function waveDelays(count: number, columns: number) {
  const width = Math.max(1, Math.min(count, columns));
  const diagonals = Array.from({ length: count }, (_, index) => Math.floor(index / width) + width - 1 - index % width);
  const last = Math.max(1, ...diagonals);
  return diagonals.map(diagonal => diagonal * Math.min(50, 330 / last));
}

/** Ignore empty fields and property insertion order when identifying a search. */
export function galleryResultKey(identity: string, filters: object, page: number) {
  return JSON.stringify([identity, page, Object.entries(filters)
    .filter(([, value]) => value !== undefined && value !== '')
    .sort(([a], [b]) => a.localeCompare(b))]);
}
