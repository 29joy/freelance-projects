
# Douyin Comment Extractor (Pilot)

A pragmatic Playwright-based extractor for Douyin comment collection—designed per your spec:
- Open Douyin URLs, close login modal, enter comment panel
- Focus on **Hot (最热)** tab
- Scroll to trigger lazy loading, click "expand" buttons
- Collect **Top-N** comments (default 200) and export to **CSV**
- Excel reader auto-detects 3 columns: URL / Content / content_segmented
- Optional **search-backfill** for missing URLs (heuristic, configurable)
- Failed URLs report & simple logging

> Selectors are heuristic and may need tuning as Douyin updates its DOM.

## 1) Install
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 2) Configure
Edit `configs/default.yaml`:
- `input.excel_path` – path to your Excel
- Column candidates for URL/Content/Segmented detection
- `search_backfill.enabled` – set `true` to allow missing URL backfill
- `extraction.top_n_comments` – cap per URL
- `output.dir` – output folder

## 3) Run (CLI)
```bash
python -m cli.main --config configs/default.yaml --excel "data_Sept 3.xlsx" --sheet "high impact" --enable-backfill
```
Outputs:
- `data/output/douyin_comments.csv`
- `data/output/failed_urls.csv`
- optionally `data/output/search_backfill_report.csv`

## 4) Build .exe (PyInstaller)
```bash
pip install pyinstaller
pyinstaller -F -n douyin_extractor --add-data "configs/default.yaml;configs" cli/main.py
# Ship 'dist/douyin_extractor.exe'. Ensure Playwright browser installed on first run.
```

## Notes
- For authorized academic research only.
- Use polite mode, keep concurrency low.
- If coverage is insufficient without login, we can add cookie import later.
