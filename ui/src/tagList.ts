/** Adds each new tag once, ignoring case and blanks. */
export function addTags(tags: string[], added: string[]): string[] {
  const next = [...tags];
  for (const raw of added) {
    const tag = raw.trim();
    if (tag && !next.some((existing) => existing.toLowerCase() === tag.toLowerCase())) next.push(tag);
  }
  return next;
}
