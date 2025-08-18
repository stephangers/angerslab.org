#!/usr/bin/env python3
"""
Scan assets/carousel and write a JSON manifest of image paths for the site.

Usage:
  python scripts/build_carousel_manifest.py

The script writes: assets/carousel/manifest.json
Paths are written relative to the repository root, e.g. "assets/carousel/figure1.jpg"
Supported extensions: .png .jpg .jpeg .webp .gif .svg
"""
import json
import sys
from pathlib import Path

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg'}

REPO_ROOT = Path(__file__).resolve().parents[1]
CAROUSEL_DIR = REPO_ROOT / 'assets' / 'carousel'
MANIFEST = CAROUSEL_DIR / 'manifest.json'

def main() -> int:
    if not CAROUSEL_DIR.exists():
        print(f"[build-carousel] Directory not found: {CAROUSEL_DIR}", file=sys.stderr)
        return 1

    images = []
    for p in sorted(CAROUSEL_DIR.rglob('*')):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            rel = p.relative_to(REPO_ROOT).as_posix()
            images.append(rel)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open('w', encoding='utf-8') as f:
        json.dump({'images': images}, f, ensure_ascii=False, indent=2)

    print(f"[build-carousel] Wrote {len(images)} images to {MANIFEST}")
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
