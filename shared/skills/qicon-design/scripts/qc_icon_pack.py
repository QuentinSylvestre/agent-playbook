#!/usr/bin/env python3
"""Basic QC report for generated icon identity asset packs."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required. Install with: python -m pip install pillow") from exc


def has_alpha(path: Path) -> Optional[bool]:
    try:
        img = Image.open(path).convert("RGBA")
        alpha = img.getchannel("A")
        return alpha.getextrema()[0] < 255
    except Exception:
        return None


def image_size(path: Path) -> Optional[List[int]]:
    try:
        img = Image.open(path)
        return [img.width, img.height]
    except Exception:
        return None


def qc(manifest_path: Path) -> Path:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_dir = manifest_path.parent
    lines: List[str] = []
    failures = 0
    warnings = 0

    lines.append(f"# Icon Pack QC Report")
    lines.append("")
    lines.append(f"Generated at: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Project: {manifest.get('display_name')} ({manifest.get('project_slug')})")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    detail_lines: List[str] = []
    for asset in manifest.get("assets", []):
        rel_path = asset.get("path")
        if not rel_path:
            continue
        path = out_dir / rel_path
        exists = path.exists()
        expected_size = asset.get("size")
        actual_size = image_size(path) if exists and path.suffix.lower() in [".png", ".ico", ".icns"] else None
        alpha = has_alpha(path) if exists and path.suffix.lower() == ".png" else None
        status = "PASS"
        notes: List[str] = []
        if not exists:
            status = "FAIL"
            failures += 1
            notes.append("missing file")
        if exists and expected_size and actual_size and actual_size != expected_size:
            status = "FAIL"
            failures += 1
            notes.append(f"expected {expected_size}, got {actual_size}")
        alpha_expectation = asset.get("alpha_expectation")
        if exists and path.suffix.lower() == ".png" and alpha_expectation == "expected" and alpha is False:
            status = "WARN" if status == "PASS" else status
            warnings += 1
            notes.append("expected transparency but PNG appears fully opaque")
        if exists and path.suffix.lower() == ".png" and alpha_expectation == "allowed" and alpha is False and "transparent" in str(asset.get("background_expectation", "")).lower():
            status = "WARN" if status == "PASS" else status
            warnings += 1
            notes.append("transparent/background-safe asset may be opaque")
        detail_lines.append(f"| {status} | `{rel_path}` | {asset.get('role')} | {actual_size or '-'} | {'; '.join(notes) or '-'} |")

    skipped = manifest.get("skipped", [])
    lines.append(f"- Assets listed: {len(manifest.get('assets', []))}")
    lines.append(f"- Skipped optional assets: {len(skipped)}")
    lines.append(f"- Failures: {failures}")
    lines.append(f"- Warnings: {warnings}")
    lines.append("")

    if skipped:
        lines.append("## Skipped optional assets")
        lines.append("")
        lines.append("| Role | Path/pattern | Reason |")
        lines.append("|---|---|---|")
        for item in skipped:
            lines.append(f"| {item.get('role')} | `{item.get('path')}` | {item.get('skip_reason') or '-'} |")
        lines.append("")

    lines.append("## Asset checks")
    lines.append("")
    lines.append("| Status | Path | Role | Actual size | Notes |")
    lines.append("|---|---|---|---|---|")
    lines.extend(detail_lines)
    lines.append("")
    lines.append("## Manual review required")
    lines.append("")
    lines.append("Automated QC cannot judge aesthetics. Manually inspect preview sheets for:")
    lines.append("")
    lines.append("- fake transparency or hidden background boxes;")
    lines.append("- dark/light/checkerboard halos;")
    lines.append("- tiny-size readability;")
    lines.append("- wordmark spelling, casing, spacing, and kerning;")
    lines.append("- tray-state distinctiveness;")
    lines.append("- whether generated `.ico` / `.icns` files are accepted by the target platform.")

    report_path = out_dir / "qc-report.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> None:
    parser = argparse.ArgumentParser(description="QC a generated icon identity asset pack manifest.")
    parser.add_argument("--manifest", required=True, help="Path to asset-manifest.json")
    args = parser.parse_args()
    report = qc(Path(args.manifest).resolve())
    print(f"QC report written to: {report}")


if __name__ == "__main__":
    main()
