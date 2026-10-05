/** Count changed values without counting unchanged object keys or array order. */
export function countConfigChanges(before: unknown, after: unknown): number {
  if (Object.is(before, after)) return 0;
  if (Array.isArray(before) && Array.isArray(after)) {
    const identity = (value: unknown) => {
      if (typeof value === "string") return value;
      if (!value || typeof value !== "object") return null;
      const row = value as Record<string, unknown>;
      if (typeof row.capability_id === "string")
        return `${row.endpoint_id ?? row.publisher_id}:${row.capability_id}`;
      return typeof row.id === "string" && row.id ? row.id : null;
    };
    const left = before.map(identity);
    const right = after.map(identity);
    if (
      [...left, ...right].every((key) => key !== null) &&
      new Set(left).size === left.length &&
      new Set(right).size === right.length
    ) {
      const previous = new Map(before.map((row, index) => [left[index], row]));
      const next = new Map(after.map((row, index) => [right[index], row]));
      return [...new Set([...left, ...right])].reduce(
        (count, key) => count + countConfigChanges(previous.get(key), next.get(key)),
        0,
      );
    }
    return Array.from({ length: Math.max(before.length, after.length) }).reduce<number>(
      (count, _, index) => count + countConfigChanges(before[index], after[index]),
      0,
    );
  }
  if (
    before &&
    after &&
    typeof before === "object" &&
    typeof after === "object" &&
    !Array.isArray(before) &&
    !Array.isArray(after)
  ) {
    const previous = before as Record<string, unknown>;
    const next = after as Record<string, unknown>;
    return [...new Set([...Object.keys(previous), ...Object.keys(next)])].reduce(
      (count, key) => count + countConfigChanges(previous[key], next[key]),
      0,
    );
  }
  return 1;
}

export function matchesConfigSearch(value: string, query: string): boolean {
  const text = value.toLocaleLowerCase("en");
  return query
    .trim()
    .toLocaleLowerCase("en")
    .split(/\s+/)
    .every((word) => text.includes(word));
}
