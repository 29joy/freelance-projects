# Large-Scale Web Scraping & Data Cleaning Pipeline

A scalable, validation-first web scraping framework built with **Python + Selenium + Requests**.  
Designed to collect, clean, and validate structured data (e.g., recipes, articles) across multiple websites using configuration-driven rules.

> 🚨 Note: This repository contains the core framework and **sample configs only**.  
> All client-specific configs and delivery data have been removed for confidentiality.

## 🚀 Features

- **Config-driven design (YAML)**  
  Adapt to new websites quickly by writing lightweight YAML configs (`selectors / discover / meta`).

- **Data Cleaning & Normalization**

  - Remove HTML tags, emojis, and special characters
  - Normalize punctuation and whitespace
  - Enforce schema consistency (JSONL / Excel)

- **Validation-First Pipeline**

  - Self-developed validation tool (`validate_delivery.py`)
  - Enforces mandatory fields, min length, URL checks, de-duplication
  - Rejects invalid entries (e.g., _content-only images_)
  - Generates **validation reports** for auditability

- **Preview Tool**

  - Lightweight JSONL → HTML preview (`preview_jsonl.py`)
  - Allows quick inspection of data structure before delivery

- **Scalable Scraping**

  - Modular architecture (`common/` utils for discover/extract/http/normalize/writer)
  - Robust logging, retry, and exception handling
  - Supports sitemap, index pages, and flexible allow/deny rules

- **Packaging & Delivery**
  - Merge outputs into large JSONL files (`merge_jsonl.py`)
  - Audit trail with `clean.jsonl` and `rejected.jsonl`

---

## 📂 Project Structure

Large-Scale_Web_Scraping&Data_Cleaning_Pipeline/
│── deliveries/ # (removed) final deliveries for client
│── deliveries_pre_check/ # (removed) preview HTML files
│── docs/ # documentation (optional)
│ ├── Cleaned_Data_Output_Preview.png
│ ├── Data_Validation_Report.png
│ ├── example.clean.jsonl
│ ├── Scraper_Running_in_Terminal.png
│── tools/
│ ├── common/ # shared utility modules
│ │ ├── discover.py
│ │ ├── extract.py
│ │ ├── http.py
│ │ ├── normalize.py
│ │ ├── pii.py
│ │ ├── util.py
│ │ └── writer.py
│ ├── configs/ # sample site configs (YAML)
│ │ ├── site_100daysofrealfood.yml
│ │ └── site_culinaryhill.com.yml
│ ├── preview_jsonl.py # preview tool
│ ├── scraper_and_clean.py # main scraper + cleaning pipeline
│ ├── validate_delivery.py # validation tool
│ └── merge_jsonl.py # merge JSONL outputs
│── requirements.txt
└── README.md

## ⚡️ Quick Start

### 1. Install dependencies

pip install -r requirements.txt

### 2. Run Scraper

python tools/scraper_and_clean.py --site_config tools/configs/site_100daysofrealfood.yml --out_dir out_data

### 3. Validate Output

python tools/validate_delivery.py --input out_data/clean.jsonl --report validation_report.json

### 4. Preview Output

python tools/preview_jsonl.py --input out_data/clean.jsonl --output preview.html

### 5. Merge Outputs

python tools/merge_jsonl.py --input out_data/\*.jsonl --min_lines 10000 --output final.jsonl

## 📊 Example Output

Clean JSONL: structured, validated entries
Rejected JSONL: invalid entries (e.g., image-only content)
Validation Report: summary of data quality
Preview HTML: lightweight visualization of scraped data

## 🛠 Tech Stack

Python
Selenium
Requests
YAML (site configs)
JSONL / Excel

## 📜 License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0).  
You are free to use and adapt the code for non-commercial purposes with proper attribution.  
Commercial use is not permitted.  
See the [LICENSE](LICENSE) file for details.

## 🙌 Author

Developed by Joy Jiao
💼 LinkedIn: [joysworld](https://www.linkedin.com/in/joysworld/)
