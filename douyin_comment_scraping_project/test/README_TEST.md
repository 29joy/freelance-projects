
# Douyin Comment Feasibility Test (Playwright)

A lightweight script to quickly verify whether Douyin (TikTok China) comment blocks
are accessible via browser automation. It reads the first valid Douyin URL from an Excel
file and tries to detect comment elements.

## 1) Install dependencies
```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 2) Put your Excel next to the script
Default file name expected: `data_Sept 3.xlsx` (you can override with `--excel`).

Expected column for URLs: `Link1` (override with `--link-column`).

## 3) Run
```bash
python test_playwright_douyin.py --excel "data_Sept 3.xlsx"
```
Options:
- `--headless` run without UI.
- `--sheet SHEET_NAME` to specify an Excel sheet.
- `--link-column COLUMN` to specify URL column (default: Link1).
- `--wait N` wait seconds after page load (default: 6).
- `--max-print N` number of sample comment blocks to print (default: 5).

## Notes
- If comments don't appear, they may require deeper selectors, scrolling, or an authenticated session.
- This script is for quick feasibility checks; production code should add robust waits, retries, logging, and structured extraction.
