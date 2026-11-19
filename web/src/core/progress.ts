// Download progress of the data and model files, for the loading messages of the page. Node.js has no listener.
export interface Download { file: string; loaded: number; total: number; done: boolean }

const listeners = new Set<(d: Download) => void>();

export function onDownload(cb: (d: Download) => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/** The body of r as bytes. size: the expected size if the response has no usable Content-Length (0: unknown). */
export async function readBody(r: Response, file: string, size = 0): Promise<Uint8Array> {
  if (!listeners.size || !r.body) return new Uint8Array(await r.arrayBuffer());
  // With a content encoding, Content-Length is the compressed size, not the size of the body that we read.
  const len = r.headers.get("content-encoding") ? 0 : Number(r.headers.get("content-length")) || 0;
  const total = len || size;
  const emit = (loaded: number, done: boolean) => listeners.forEach((cb) => cb({ file, loaded, total: Math.max(total, loaded), done }));
  const reader = r.body.getReader();
  const chunks: Uint8Array[] = [];
  let loaded = 0;
  emit(0, false);
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    loaded += value.length;
    emit(loaded, false);
  }
  const out = new Uint8Array(loaded);
  let o = 0;
  for (const c of chunks) { out.set(c, o); o += c.length; }
  emit(loaded, true);
  return out;
}
