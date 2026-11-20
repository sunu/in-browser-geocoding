"""Deploy the browser version to Cloudflare (plan-008 phase 6).

- Data: the country layout of one Overture release goes to R2 under `<release>/`. Only new or changed files are
  uploaded (the MD5 of each uploaded file is kept in .cache/deploy/).
- Models: the int8 models and the tokenizer files go to R2 under `models/<hash>/`. The hash is from the content,
  so a new model gets a new path and no cache purge is necessary.
- Page: `vite build` with the data and model URLs, then `wrangler deploy` (a Worker with static assets).

Usage:
  uv run python scripts/deploy_web.py                        # data, models, page
  uv run python scripts/deploy_web.py --only data --dry-run  # show what would be uploaded
  uv run python scripts/deploy_web.py --only data --assume-uploaded   # record files that are already in R2

Needs `npx wrangler@4.164.0 login` (R2 and Workers permissions).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from geoparse.config import REPO_ROOT, load_config

WEB = REPO_ROOT / "web"
STATE_DIR = REPO_ROOT / ".cache" / "deploy"
WRANGLER = "wrangler@4.164.0"
CONTENT_TYPES = {".json": "application/json", ".parquet": "application/vnd.apache.parquet",
                 ".onnx": "application/octet-stream"}
MODEL_FILES = {
    "t5": ["encoder_int8.onnx", "decoder_int8.onnx", "tokenizer.json", "tokenizer_config.json", "generation.json"],
    "xenc": ["model_int8.onnx", "tokenizer.json", "tokenizer_config.json", "calibration.json", "inputs.json"],
}
# COOP and COEP: the ONNX Runtime threads need SharedArrayBuffer. The Vite dev server sends the same headers.
HEADERS = """/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: credentialless
/assets/*
  Cache-Control: public, max-age=31536000, immutable
"""


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def wrangler(args: list[str], cwd: str) -> str:
    # Run outside the repository: wrangler writes a .wrangler/ directory in the working directory.
    r = subprocess.run(["npx", "--yes", WRANGLER, *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"wrangler {' '.join(args[:3])} failed:\n{(r.stdout + r.stderr)[-3000:]}")
    return r.stdout


def upload(bucket: str, files: dict[str, Path], state_name: str, dry_run: bool, assume: bool, cwd: str) -> None:
    """files: R2 key to local path. Upload the files whose MD5 is not in the state file."""
    state_path = STATE_DIR / f"{state_name}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    hashes = {k: md5(p) for k, p in files.items()}
    todo = sorted(k for k in files if state.get(k) != hashes[k])
    size = sum(files[k].stat().st_size for k in todo)
    print(f"{state_name}: {len(files)} files, {len(todo)} to upload ({size / 1e6:.1f} MB)")
    if dry_run:
        for k in todo[:20]:
            print("  ", k)
        return

    def put(k: str) -> str:
        ct = CONTENT_TYPES.get(files[k].suffix, "application/octet-stream")
        wrangler(["r2", "object", "put", f"{bucket}/{k}", "--file", str(files[k]), "--content-type", ct, "--remote"], cwd)
        return k

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    with ThreadPoolExecutor(8) as pool:
        for k in (todo if assume else pool.map(put, todo)):
            state[k] = hashes[k]
            done += 1
            if done % 100 == 0 or done == len(todo):
                state_path.write_text(json.dumps(state, indent=0, sort_keys=True))
                print(f"  {done}/{len(todo)}")
    state_path.write_text(json.dumps(state, indent=0, sort_keys=True))


def data_files(root: Path, release: str) -> dict[str, Path]:
    return {f"{release}/{p.relative_to(root).as_posix()}": p for p in sorted(root.rglob("*")) if p.is_file()}


def model_files() -> tuple[str, dict[str, Path]]:
    paths = [WEB / "public" / "models" / d / f for d, fs in MODEL_FILES.items() for f in fs]
    h = hashlib.md5("".join(f"{p.relative_to(WEB / 'public' / 'models')}:{md5(p)}" for p in paths).encode()).hexdigest()[:12]
    return h, {f"models/{h}/{p.relative_to(WEB / 'public' / 'models').as_posix()}": p for p in paths}


def data_version(root: Path) -> str:
    return hashlib.md5((root / "manifest.json").read_bytes() + (root / "names" / "index.json").read_bytes()).hexdigest()[:12]


def build_page(data_url: str, model_url: str, version: str) -> Path:
    dist = WEB / "dist"
    env = {**os.environ, "VITE_DATA_URL": data_url, "VITE_MODEL_URL": model_url, "VITE_DATA_VERSION": version}
    subprocess.run(["npx", "vite", "build", "--emptyOutDir"], cwd=WEB, env=env, check=True)
    shutil.copyfile(WEB / "public" / "bundle.json", dist / "bundle.json")
    (dist / "_headers").write_text(HEADERS)
    # transformers.js bundles a second ONNX Runtime with an asyncify build (27 MB, more than the 25 MiB file limit
    # of Workers static assets). The page uses only the tokenizers of transformers.js and loads ort-wasm-simd-threaded.wasm.
    for f in (dist / "assets").glob("*asyncify*.wasm"):
        f.unlink()
    big = [f for f in dist.rglob("*") if f.is_file() and f.stat().st_size > 25 * 1024 * 1024]
    if big:
        raise SystemExit(f"files larger than 25 MiB: {big}")
    return dist


def main() -> None:
    release = load_config()["data"]["overture_release"]
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["data", "models", "page"], action="append", help="Default: all three.")
    ap.add_argument("--data", type=Path, default=REPO_ROOT / "data" / "build-world" / "web" / release,
                    help="The country layout of the release.")
    ap.add_argument("--bucket", default="geoparse-world-test")
    ap.add_argument("--files-url", default="https://files.geoparse.labs.sunu.in")
    ap.add_argument("--worker", default="geoparse", help="Cloudflare Worker that serves the page.")
    ap.add_argument("--domain", default="gazetini.labs.sunu.in")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--assume-uploaded", action="store_true", help="Record the files as uploaded. Do not upload.")
    args = ap.parse_args()
    parts = args.only or ["data", "models", "page"]
    if not (args.data / "manifest.json").exists():
        raise SystemExit(f"{args.data}/manifest.json not found. Run export_web.py data --layout country first.")
    cwd = tempfile.mkdtemp(prefix="deploy-web-")
    h, models = model_files()
    if "data" in parts:
        upload(args.bucket, data_files(args.data, release), f"{args.bucket}-data", args.dry_run, args.assume_uploaded, cwd)
    if "models" in parts:
        upload(args.bucket, models, f"{args.bucket}-models", args.dry_run, args.assume_uploaded, cwd)
    if "page" in parts:
        version = data_version(args.data)
        dist = build_page(f"{args.files_url}/{release}", f"{args.files_url}/models/{h}", version)
        print(f"page: data {release} (version {version}), models {h}")
        if not args.dry_run:
            # A Worker with static assets (Cloudflare Pages is now part of Workers). The custom domain
            # route also makes the DNS record.
            conf = {"name": args.worker, "compatibility_date": "2026-11-01", "assets": {"directory": str(dist)},
                    "routes": [{"pattern": args.domain, "custom_domain": True}]}
            (Path(cwd) / "wrangler.json").write_text(json.dumps(conf))
            wrangler(["deploy", "--config", str(Path(cwd) / "wrangler.json")], cwd)
            print(f"deployed: Worker {args.worker}, https://{args.domain}")
    shutil.rmtree(cwd, ignore_errors=True)


if __name__ == "__main__":
    main()
