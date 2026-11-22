// Cache Storage for the model and data files, for a fast second start. Node.js, and browsers without the Cache API
// (or where it fails, for example some private windows), use fetch() only.
export const CACHE_NAME = "gazetini-files";

let opened: Promise<Cache | null> | null = null;
function open(): Promise<Cache | null> {
  opened ??= (async () => {
    if (typeof window === "undefined" || !("caches" in globalThis)) return null;
    try {
      // Ask the browser not to remove the files when storage is low. The browser can refuse.
      navigator.storage?.persist?.().catch(() => undefined);
      return await caches.open(CACHE_NAME);
    } catch {
      return null;
    }
  })();
  return opened;
}

function store(c: Cache, url: string, r: Response) {
  if (r.ok) c.put(url, r.clone()).catch(() => undefined);
}

/** immutable: the URL has a content hash (models/<hash>/, data `?h=`), so a stored response is always correct.
 * fallback: the file can change (`?v=` JSON files); the network first, the stored response if the network fails. */
export async function cachedFetch(url: string, mode: "immutable" | "fallback"): Promise<Response> {
  const c = await open();
  if (!c) return fetch(url);
  if (mode === "immutable") {
    const hit = await c.match(url).catch(() => undefined);
    if (hit) return hit;
    const r = await fetch(url);
    store(c, url, r);
    return r;
  }
  try {
    const r = await fetch(url);
    store(c, url, r);
    return r;
  } catch (e) {
    const hit = await c.match(url).catch(() => undefined);
    if (hit) return hit;
    throw e;
  }
}

/** Remove the stored files whose URL starts with prefix and for which keep() is false (old models, changed data). */
export async function prune(prefix: string, keep: (url: string) => boolean): Promise<void> {
  const c = await open();
  if (!c) return;
  try {
    for (const req of await c.keys()) if (req.url.startsWith(prefix) && !keep(req.url)) await c.delete(req);
  } catch {
    // A failed clean-up only keeps old files.
  }
}
