# 🇨🇳 Heavy-Truck EV Charging Station Data Collection (China)

A comprehensive data acquisition and processing pipeline for **nationwide heavy-truck EV charging stations in China**, developed as part of a Bloomberg‑affiliated research project.  
The project combines semi‑automated scraping, structured data enrichment, bilingual translation, and metadata validation for over **900+ stations**.

---

## 📘 Overview

This repository contains all scripts and logic used to:

1. **Deduplicate & reindex** station rows (by Station name + Partners + Province + City/County).
2. **Enrich metadata** (Investment (CNY), Year operational) via curated web search (gov sites, WeChat OA, corporate PR).
3. **Normalize/clean partner names** and brand tokens from mixed CN/EN sources.
4. **Translate** 4 key columns (Station name, Partners, Province, City/County) to English with custom CN rules.
5. **Export** clean bilingual Excel files suitable for client delivery.

---

## 🧭 Pipeline

```mermaid
graph TD
    A[Raw station data from app] --> B[dedupe_reindex.py]
    B --> C[enrich_year_investment.py]
    C --> D[fix_partners_from_source.py]
    D --> E[translate_ev_columns_mt.py]
    E --> F[Final Excel (CN+EN)]

---

## 🗂️ Repo Structure

```

.
├── dedupe_reindex.py # Remove duplicates & rebuild A:ID as 1..N
├── enrich_year_investment.py # Fill Year operational / Investment via web search
├── fix_partners_from_source.py # Normalize partner/company names
├── station_metadata_enrichment.py # Search engine helpers & extraction rules
├── translate_company_auto.py # Company name mapping / fallback translation
├── translate_ev_columns_mt.py # Translate B/D/E/F with bracket rules & cache
├── requirements.txt
└── README.md

````

---

## ⚙️ Installation

```bash
# (1) Create & activate a virtualenv (recommended)
python -m venv .venv
# Windows:
.\.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

# (2) Install dependencies
pip install -r requirements.txt
````

> Optional: create a `.env` in the project root to store keys safely:
>
> ```env
> SERPAPI_API_KEY=your_key_here
> YOUDAO_APP_KEY=your_key_here
> YOUDAO_APP_SECRET=your_secret_here
> ```

---

## 🚀 Quickstart

Assume your working Excel file is `Upwork_truck_charging_2.xlsx` and the target sheet is `StarCharge` (adjust as needed).

### 1) Deduplicate & Reindex IDs

```bash
python dedupe_reindex.py --excel Upwork_truck_charging_2.xlsx --sheet StarCharge --out 01_deduped.xlsx
```

### 2) (Optional) Partner Name Normalization

```bash
python fix_partners_from_source.py --excel 01_deduped.xlsx --sheet StarCharge --out 02_partners_fixed.xlsx
```

### 3) Enrich Year Operational & Investment

Two backends are supported:

- `--backend selenium --engine bing` (no API key; slower)
- or `--backend serpapi --engine google` (faster, requires SERPAPI key)

```bash
# Selenium backend + Bing
python enrich_year_investment.py   --excel 02_partners_fixed.xlsx --sheet StarCharge   --backend selenium --engine bing   --out 03_enriched.xlsx

# OR SerpAPI backend + Google
python enrich_year_investment.py   --excel 02_partners_fixed.xlsx --sheet StarCharge   --backend serpapi --engine google   --out 03_enriched.xlsx
```

### 4) Translate B/D/E/F (Station name, Partners, Province, City/County)

- Defaults to **Google** via `deep-translator`
- Optional Youdao keys if configured
- Caches company mappings to reduce lookups

```bash
python translate_ev_columns_mt.py   --excel 03_enriched.xlsx --sheet StarCharge   --out 04_translated.xlsx   --cache company_cache.json
```

> The translator applies **bracket-aware rules** (e.g., `【星星寅元特】`) and title‑case normalization; it also reuses any cached official English names where available.

---

## 🧪 Tips & Notes

- **Rate limiting**: When using search backends, the scripts include light throttling; tweak sleeps if you hit captchas.
- **Determinism**: If public sources disagree, the script leaves fields blank (conservative default).
- **Idempotency**: Safe to re‑run—outputs are written to new files so your source data remains unchanged.
- **Confidentiality**: The repo contains _only code_; delivery data should remain private unless anonymized.

---

## 🧰 Tech Stack

`Python` · `pandas` · `openpyxl` · `requests` · `selenium` · `deep-translator` · `pypinyin` · `SerpAPI` · `BeautifulSoup4` · `lxml`

---

## 🧠 Lessons Learned

Verified app-level data access feasibility (certificate and API validation).

Developed robust fallback between automated and manual workflows.

Designed a repeatable bilingual data pipeline for future EV or infrastructure datasets.

---

## 📄 License

MIT © 2025 Joy Jiao
