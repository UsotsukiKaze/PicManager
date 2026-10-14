interface CloudGroup { id: number; name: string; image_count?: number }
interface Bounds { width: number; height: number }
export interface CloudWord extends CloudGroup { x: number; y: number; width: number; height: number; size: number }
type Measure = (name: string, size: number) => number;

// Eight names at most: deterministic rectangle packing, no physics loop or runtime dependency.
export function layoutWordCloud(groups: CloudGroup[], bounds: Bounds, measure: Measure): CloudWord[] {
  if (bounds.width < 40 || bounds.height < 40) return [];
  const rows = [...new Map(groups.slice(0, 8).map(group => [group.id, group])).values()]
    .sort((a, b) => (b.image_count || 0) - (a.image_count || 0));
  const weights = rows.map(row => Math.log1p(Math.max(0, row.image_count || 0)));
  const low = Math.min(...weights), high = Math.max(...weights);
  const maxSize = bounds.width < 340 ? 29 : 36;
  for (let attempt = 0; attempt < 12; attempt++) {
    const placed: CloudWord[] = [];
    for (let index = 0; index < rows.length; index++) {
      const row = rows[index]!;
      const weight = high === low ? .6 : (weights[index]! - low) / (high - low);
      let size = Math.max(10, (16 + (maxSize - 16) * weight) * .88 ** attempt);
      // Long names stay on one line, scaled to the available width.
      size = Math.min(size, size * (bounds.width - 24) / Math.max(1, measure(row.name, size)));
      const width = Math.min(bounds.width - 20, Math.ceil(measure(row.name, size)) + 2);
      const height = Math.ceil(size * 1.2);
      let match: CloudWord | undefined;
      for (let step = 0; step < 6500; step++) {
        const radius = 2.9 * Math.sqrt(step), angle = step * .39;
        const x = Math.round(bounds.width / 2 + radius * Math.cos(angle) - width / 2);
        const y = Math.round(bounds.height / 2 + radius * .72 * Math.sin(angle) - height / 2);
        if (x < 10 || y < 8 || x + width > bounds.width - 10 || y + height > bounds.height - 8) continue;
        if (placed.some(other => x < other.x + other.width + 10 && x + width + 10 > other.x && y < other.y + other.height + 12 && y + height + 12 > other.y)) continue;
        match = { ...row, x, y, width, height, size }; break;
      }
      if (!match) break;
      placed.push(match);
    }
    if (placed.length === rows.length) return placed;
  }
  // Extremely narrow containers still retain every link and its complete accessible name.
  const size = Math.max(1, Math.min(10, (bounds.height - 16) / Math.max(1, rows.length) / 2.4));
  return rows.map((row, index) => {
    const width = Math.min(bounds.width - 20, Math.ceil(measure(row.name, size)) + 2);
    return { ...row, size, width, height: size * 1.2, x: (bounds.width - width) / 2, y: 8 + index * size * 2.4 };
  });
}
