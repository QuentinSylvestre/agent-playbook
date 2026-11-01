#!/usr/bin/env python3
"""Generate a conservative icon identity asset pack from approved source PNGs.

This script does not create new designs. It resizes/copies clean source assets into a
standard concept-raster package, creates preview sheets, and writes an asset manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError as exc:
    raise SystemExit("Pillow is required. Install with: python -m pip install pillow") from exc


@dataclass
class AssetRecord:
    path: str
    role: str
    size: Optional[List[int]]
    source_input: Optional[str]
    alpha_expectation: str
    background_expectation: str
    status: str
    skip_reason: Optional[str] = None
    manual_review: Optional[List[str]] = None


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def slugify(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-").replace("--", "-")


def ensure_rgba(path: Path) -> Image.Image:
    img = Image.open(path)
    return img.convert("RGBA")


def fit_square(img: Image.Image, size: int) -> Image.Image:
    """Resize an image into a square canvas without cropping."""
    if img.width == size and img.height == size:
        return img.copy()
    scale = min(size / img.width, size / img.height)
    new_size = (max(1, int(round(img.width * scale))), max(1, int(round(img.height * scale))))
    resized = img.resize(new_size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pos = ((size - resized.width) // 2, (size - resized.height) // 2)
    canvas.alpha_composite(resized, pos)
    return canvas


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def copy_png_source(src: Path, dst: Path) -> Tuple[int, int]:
    dst.parent.mkdir(parents=True, exist_ok=True)
    img = ensure_rgba(src)
    img.save(dst, "PNG")
    return [img.width, img.height]


def has_alpha(img: Image.Image) -> bool:
    if img.mode != "RGBA":
        return False
    alpha = img.getchannel("A")
    extrema = alpha.getextrema()
    return extrema[0] < 255


def rel(path: Path, base: Path) -> str:
    return str(path.relative_to(base).as_posix())


def write_manifest(records: List[AssetRecord], skipped: List[AssetRecord], config: Dict[str, Any], out_dir: Path) -> None:
    manifest = {
        "project_slug": config["project_slug"],
        "display_name": config.get("display_name", config["project_slug"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package_type": config.get("package_type", "concept-raster"),
        "app_icon_treatment": config.get("app_icon_treatment", "contained"),
        "assets": [asdict(r) for r in records],
        "skipped": [asdict(r) for r in skipped],
    }
    (out_dir / "asset-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def try_font(size: int = 14) -> ImageFont.ImageFont:
    for candidate in ["DejaVuSans.ttf", "Arial.ttf", "Helvetica.ttf"]:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            pass
    return ImageFont.load_default()


def checkerboard(size: Tuple[int, int], block: int = 12) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    a = (220, 220, 220, 255)
    b = (255, 255, 255, 255)
    for y in range(0, h, block):
        for x in range(0, w, block):
            draw.rectangle([x, y, x + block - 1, y + block - 1], fill=a if ((x // block + y // block) % 2) else b)
    return img


def make_preview_sheet(items: List[Tuple[str, Path]], out_path: Path, title: str, max_thumb: int = 128) -> None:
    if not items:
        return
    font = try_font(13)
    title_font = try_font(18)
    cell_w = 230
    cell_h = max_thumb + 90
    cols = min(3, len(items))
    rows = (len(items) + cols - 1) // cols
    header_h = 38
    canvas = Image.new("RGBA", (cols * cell_w, header_h + rows * cell_h), (245, 245, 245, 255))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 8), title, fill=(0, 0, 0, 255), font=title_font)
    backgrounds = [
        ("light", Image.new("RGBA", (max_thumb, max_thumb), (255, 255, 255, 255))),
        ("dark", Image.new("RGBA", (max_thumb, max_thumb), (24, 24, 28, 255))),
        ("check", checkerboard((max_thumb, max_thumb), 10)),
    ]
    for idx, (label, path) in enumerate(items):
        col = idx % cols
        row = idx // cols
        x0 = col * cell_w
        y0 = header_h + row * cell_h
        draw.rectangle([x0 + 8, y0 + 8, x0 + cell_w - 8, y0 + cell_h - 8], outline=(210, 210, 210, 255), fill=(255, 255, 255, 255))
        try:
            img = ensure_rgba(path)
            thumb = fit_square(img, 64 if img.width <= 64 and img.height <= 64 else max_thumb)
        except Exception:
            draw.text((x0 + 16, y0 + 24), "Could not open", fill=(180, 0, 0, 255), font=font)
            continue
        bg_y = y0 + 32
        bg_size = 56
        if max_thumb >= 96:
            bg_size = 64
        for b_idx, (b_label, bg) in enumerate(backgrounds):
            bx = x0 + 18 + b_idx * 68
            bg_small = bg.resize((bg_size, bg_size), Image.Resampling.NEAREST)
            canvas.alpha_composite(bg_small, (bx, bg_y))
            icon = fit_square(img, bg_size)
            canvas.alpha_composite(icon, (bx, bg_y))
            draw.text((bx, bg_y + bg_size + 2), b_label, fill=(70, 70, 70, 255), font=font)
        text = label[:28]
        draw.text((x0 + 16, y0 + cell_h - 34), text, fill=(0, 0, 0, 255), font=font)
        draw.text((x0 + 16, y0 + cell_h - 18), f"{img.width}x{img.height}", fill=(80, 80, 80, 255), font=font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, "PNG")


def generate_iconset(app_img: Image.Image, iconset_dir: Path) -> None:
    sizes = [16, 32, 128, 256, 512]
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for s in sizes:
        save_png(fit_square(app_img, s), iconset_dir / f"icon_{s}x{s}.png")
        save_png(fit_square(app_img, s * 2), iconset_dir / f"icon_{s}x{s}@2x.png")


def try_iconutil(iconset_dir: Path, icns_path: Path) -> bool:
    if platform.system() != "Darwin" or shutil.which("iconutil") is None:
        return False
    try:
        subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
        return icns_path.exists()
    except Exception:
        return False


def generate_pack(config_path: Path) -> None:
    config = load_config(config_path)
    root = config_path.parent.resolve()
    project_slug = slugify(config.get("project_slug") or config.get("display_name") or "project")
    config["project_slug"] = project_slug
    display_name = config.get("display_name", project_slug)
    input_dir = (root / config.get("input_dir", "input")).resolve()
    out_dir = (root / config.get("output_dir", "output")).resolve()
    package_type = config.get("package_type", "concept-raster")
    base = out_dir / package_type
    sources = config.get("sources", {})
    sizes = config.get("sizes", {})
    records: List[AssetRecord] = []
    skipped: List[AssetRecord] = []

    app_source = input_dir / sources.get("app_icon", "app-icon-source.png")
    if not app_source.exists():
        raise SystemExit(f"Required source missing: {app_source}")
    app_img = ensure_rgba(app_source)

    # App PNGs
    app_png_items = []
    for s in sizes.get("app_png", [16, 20, 24, 32, 48, 64, 128, 256, 512, 1024]):
        dst = base / "app" / "png" / f"{project_slug}-app-icon-concept-{s}x{s}.png"
        save_png(fit_square(app_img, int(s)), dst)
        records.append(AssetRecord(rel(dst, out_dir), "app_icon_png", [int(s), int(s)], rel(app_source, root), "allowed", config.get("app_icon_treatment", "contained"), "generated", manual_review=["small-size readability", "background safety"]))
        app_png_items.append((dst.name, dst))

    # Windows ICO
    ico_path = base / "app" / "windows" / f"{display_name}-concept.ico"
    ico_path.parent.mkdir(parents=True, exist_ok=True)
    ico_sizes = [(int(s), int(s)) for s in sizes.get("ico", [16, 20, 24, 32, 48, 64, 128, 256])]
    app_img.save(ico_path, format="ICO", sizes=ico_sizes)
    records.append(AssetRecord(rel(ico_path, out_dir), "windows_ico", None, rel(app_source, root), "allowed", config.get("app_icon_treatment", "contained"), "generated", manual_review=["verify embedded sizes"] ))

    # macOS iconset / conditional icns
    iconset_dir = base / "app" / "macos" / f"{display_name}-concept.iconset"
    generate_iconset(app_img, iconset_dir)
    records.append(AssetRecord(rel(iconset_dir, out_dir), "macos_iconset_pngs", None, rel(app_source, root), "allowed", config.get("app_icon_treatment", "contained"), "generated", manual_review=["run iconutil on macOS if .icns skipped"] ))
    icns_path = base / "app" / "macos" / f"{display_name}-concept.icns"
    if try_iconutil(iconset_dir, icns_path):
        records.append(AssetRecord(rel(icns_path, out_dir), "macos_icns", None, rel(app_source, root), "allowed", config.get("app_icon_treatment", "contained"), "generated"))
    else:
        skipped.append(AssetRecord(rel(icns_path, out_dir), "macos_icns", None, rel(app_source, root), "allowed", config.get("app_icon_treatment", "contained"), "skipped", skip_reason="iconutil unavailable or not running on macOS"))

    # Favicons and PWA
    for s in sizes.get("favicon_png", [16, 32]):
        dst = base / "web" / "favicon" / f"favicon-{s}x{s}.png"
        save_png(fit_square(app_img, int(s)), dst)
        records.append(AssetRecord(rel(dst, out_dir), "favicon_png", [int(s), int(s)], rel(app_source, root), "allowed", "favicon", "generated", manual_review=["tiny-size readability"]))
    favicon_ico = base / "web" / "favicon" / "favicon.ico"
    favicon_ico.parent.mkdir(parents=True, exist_ok=True)
    app_img.save(favicon_ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    records.append(AssetRecord(rel(favicon_ico, out_dir), "favicon_ico", None, rel(app_source, root), "allowed", "favicon", "generated"))

    for filename, size in sizes.get("pwa", {"apple-touch-icon.png": 180, "android-chrome-192x192.png": 192, "android-chrome-512x512.png": 512}).items():
        dst = base / "web" / "pwa" / filename
        save_png(fit_square(app_img, int(size)), dst)
        records.append(AssetRecord(rel(dst, out_dir), "pwa_icon", [int(size), int(size)], rel(app_source, root), "allowed", "pwa", "generated"))

    # Logo mark and wordmark copies
    optional_copies = [
        ("logo_mark", sources.get("logo_mark", "logo-mark-source.png"), base / "web" / "logo" / f"{project_slug}-mark-concept.png", "transparent_logo_mark", "expected"),
        ("wordmark_dark", sources.get("wordmark_dark", "wordmark-dark-source.png"), base / "web" / "logo" / f"{project_slug}-wordmark-dark-concept.png", "wordmark_dark", "expected"),
        ("wordmark_light", sources.get("wordmark_light", "wordmark-light-source.png"), base / "web" / "logo" / f"{project_slug}-wordmark-light-concept.png", "wordmark_light", "expected"),
    ]
    logo_items = []
    for key, filename, dst, role, alpha_expectation in optional_copies:
        src = input_dir / filename
        if src.exists():
            size = copy_png_source(src, dst)
            records.append(AssetRecord(rel(dst, out_dir), role, size, rel(src, root), alpha_expectation, "transparent asset", "generated", manual_review=["transparency", "light/dark behavior", "spelling/casing if wordmark"]))
            logo_items.append((dst.name, dst))
        else:
            skipped.append(AssetRecord(rel(dst, out_dir), role, None, rel(src, root), alpha_expectation, "transparent asset", "skipped", skip_reason="optional source missing"))

    # Tray base and explicit states
    tray_items = []
    tray_sizes = sizes.get("tray_png", [16, 20, 24, 32, 48, 64])
    tray_sources = {}
    if sources.get("tray_base"):
        tray_sources["base"] = sources.get("tray_base")
    for state, filename in sources.get("tray_states", {}).items():
        tray_sources[state] = filename
    for state, filename in tray_sources.items():
        src = input_dir / filename
        if not src.exists():
            skipped.append(AssetRecord(f"{package_type}/tray/png/{project_slug}-tray-{state}-concept-*.png", "tray_state_png", None, rel(src, root), "expected", "transparent tray state", "skipped", skip_reason="optional source missing"))
            continue
        tray_img = ensure_rgba(src)
        ico_state_images = []
        for s in tray_sizes:
            dst = base / "tray" / "png" / f"{project_slug}-tray-{state}-concept-{s}x{s}.png"
            resized = fit_square(tray_img, int(s))
            save_png(resized, dst)
            records.append(AssetRecord(rel(dst, out_dir), "tray_state_png", [int(s), int(s)], rel(src, root), "expected", "transparent tray state", "generated", manual_review=["tiny-size readability", "state differentiation"]))
            tray_items.append((dst.name, dst))
            if int(s) in [16, 20, 24, 32, 48, 64]:
                ico_state_images.append((int(s), int(s)))
        ico_dst = base / "tray" / "ico" / f"{project_slug}-tray-{state}-concept.ico"
        ico_dst.parent.mkdir(parents=True, exist_ok=True)
        tray_img.save(ico_dst, format="ICO", sizes=ico_state_images or [(16,16),(32,32),(48,48)])
        records.append(AssetRecord(rel(ico_dst, out_dir), "tray_state_ico", None, rel(src, root), "expected", "transparent tray state", "generated"))

    # Brand README stub
    brand_readme = base / "docs" / "brand-readme.md"
    brand_readme.parent.mkdir(parents=True, exist_ok=True)
    brand_readme.write_text(f"# {display_name} Brand Assets\n\nGenerated concept-raster package. Review preview sheets and QC report before use.\n", encoding="utf-8")
    records.append(AssetRecord(rel(brand_readme, out_dir), "brand_readme", None, None, "n/a", "documentation", "generated"))

    # Preview sheets
    previews = base / "previews"
    if config.get("generate_previews", True):
        make_preview_sheet(app_png_items, previews / "app-icon-sizes-preview.png", "App icon sizes")
        records.append(AssetRecord(rel(previews / "app-icon-sizes-preview.png", out_dir), "preview_sheet", None, None, "n/a", "preview", "generated"))
        favicon_items = [(p.name, p) for p in (base / "web" / "favicon").glob("*.png")]
        make_preview_sheet(favicon_items, previews / "favicon-sizes-preview.png", "Favicons")
        records.append(AssetRecord(rel(previews / "favicon-sizes-preview.png", out_dir), "preview_sheet", None, None, "n/a", "preview", "generated"))
        make_preview_sheet(logo_items, previews / "logo-light-dark-preview.png", "Logo/wordmark transparent assets")
        if logo_items:
            records.append(AssetRecord(rel(previews / "logo-light-dark-preview.png", out_dir), "preview_sheet", None, None, "n/a", "preview", "generated"))
        make_preview_sheet(tray_items, previews / "tray-states-preview.png", "Tray states")
        if tray_items:
            records.append(AssetRecord(rel(previews / "tray-states-preview.png", out_dir), "preview_sheet", None, None, "n/a", "preview", "generated"))

    if config.get("generate_manifest", True):
        write_manifest(records, skipped, config, out_dir)
    print(f"Generated asset pack at: {out_dir}")
    print(f"Generated assets: {len(records)}; skipped optional assets: {len(skipped)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an icon identity asset pack from approved source PNGs.")
    parser.add_argument("--config", default="asset-pack.config.json", help="Path to asset-pack config JSON.")
    args = parser.parse_args()
    generate_pack(Path(args.config).resolve())


if __name__ == "__main__":
    main()
