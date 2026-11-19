// Port of geoparse.options keyword matching (used by the rules).
import { norm } from "./text.ts";

export function edit1(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length, lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  if (la === lb) {
    const diff: number[] = [];
    for (let i = 0; i < la; i++) if (a[i] !== b[i]) diff.push(i);
    if (diff.length === 1) return true;
    return diff.length === 2 && diff[1] === diff[0] + 1 && a[diff[0]] === b[diff[1]] && a[diff[1]] === b[diff[0]];
  }
  if (la > lb) [a, b] = [b, a];
  let i = 0;
  while (i < a.length && a[i] === b[i]) i++;
  return a.slice(i) === b.slice(i + 1);
}

/** typo: words of 5 or more letters can have one typo. */
export function keywordHits(text: string, keywords: string[], typo = true): number {
  const words = norm(text).split(" ").filter(Boolean);
  const covered = new Set<number>();
  for (const kw of [...keywords].sort((x, y) => y.length - x.length)) {
    const kws = kw.split(" ");
    const n = kws.length;
    for (let i = 0; i + n <= words.length; i++) {
      let free = true;
      for (let j = i; j < i + n; j++) if (covered.has(j)) free = false;
      if (!free) continue;
      let ok = true;
      for (let j = 0; j < n; j++) {
        const w = words[i + j], k = kws[j];
        if (!(w === k || (typo && k.length >= 5 && edit1(w, k)))) { ok = false; break; }
      }
      if (ok) for (let j = i; j < i + n; j++) covered.add(j);
    }
  }
  return covered.size;
}
