// Photon geocoder for the browser (CORS is open). Port of geoparse.execute.geocoder.PhotonGeocoder (no disk cache).
export interface GeoFeature { id: string; name: string; lon: number; lat: number; osm_key: string | null; osm_value: string | null; label: string }

export class Photon {
  last = 0;
  cache = new Map<string, GeoFeature[]>();
  constructor(public url = "https://photon.komoot.io/api", public minIntervalS = 1.0) {}

  /** bbox: only results inside. location: [lon, lat] for a location bias. osmTag: for example "amenity:hospital". */
  async search(q: string, opts: { limit?: number; bbox?: number[]; location?: number[]; osmTag?: string } = {}): Promise<GeoFeature[]> {
    const params = new URLSearchParams({ q, limit: String(opts.limit ?? 5), lang: "en" });
    if (opts.location) { params.set("lon", opts.location[0].toFixed(4)); params.set("lat", opts.location[1].toFixed(4)); }
    if (opts.osmTag) params.set("osm_tag", opts.osmTag);
    if (opts.bbox) params.set("bbox", opts.bbox.map((v) => v.toFixed(5)).join(","));
    const key = params.toString();
    if (this.cache.has(key)) return this.cache.get(key)!;
    const wait = this.last + this.minIntervalS * 1000 - Date.now();
    if (wait > 0) await new Promise((r) => setTimeout(r, wait));
    this.last = Date.now();
    const r = await fetch(`${this.url}?${key}`);
    if (!r.ok) throw new Error(`Photon HTTP ${r.status}`);
    const data = await r.json();
    const out: GeoFeature[] = (data.features ?? []).map((f: any) => {
      const p = f.properties;
      const label = [p.name, p.street, p.locality, p.district, p.city, p.county, p.state].filter(Boolean).filter((v, i, a) => a.indexOf(v) === i).join(", ");
      return { id: `osm:${p.osm_type ?? "?"}${p.osm_id ?? ""}`, name: p.name ?? p.street ?? q, lon: f.geometry.coordinates[0],
        lat: f.geometry.coordinates[1], osm_key: p.osm_key ?? null, osm_value: p.osm_value ?? null, label };
    });
    this.cache.set(key, out);
    return out;
  }
}
