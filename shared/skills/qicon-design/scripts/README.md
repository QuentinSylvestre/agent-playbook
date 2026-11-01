# Scripts

These scripts are conservative. They package already-approved clean source images; they do not invent new logos, add glows, compose wordmarks, or derive missing assets unless you explicitly add that behavior.

## Requirements

```bash
python -m pip install pillow
```

## Generate asset pack

```bash
python scripts/generate_icon_pack.py --config asset-pack.config.example.json
```

## Run QC

```bash
python scripts/qc_icon_pack.py --manifest output/asset-manifest.json
```

## Notes

- `app-icon-source.png` is required.
- Optional source files are skipped when missing.
- `.ico` generation uses Pillow.
- `.icns` generation is attempted only on macOS when `iconutil` is available.
- Preview sheets are generated for manual review.
