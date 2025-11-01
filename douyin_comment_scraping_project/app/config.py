
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

import json
import yaml

@dataclass
class RuntimeCfg:
    headless: bool = False
    polite_mode: bool = True
    max_concurrency: int = 2
    screenshot_on_error: bool = True

@dataclass
class InputCfg:
    excel_path: str = "data/input.xlsx"
    sheet_name: Optional[str] = None
    url_column_candidates: List[str] = None
    content_column_candidates: List[str] = None
    segmented_column_candidates: List[str] = None

@dataclass
class SearchBackfillCfg:
    enabled: bool = False
    min_match_score: int = 85
    max_candidates: int = 5
    engine: str = "douyin_web"

@dataclass
class ExtractionCfg:
    rank_preference: str = "hot"
    top_n_comments: int = 200
    grab_replies: bool = True
    max_replies_per_parent: int = 5
    like_threshold: Optional[int] = None

@dataclass
class OutputCfg:
    dir: str = "data/output"
    format: str = "csv"
    aggregate_filename: str = "douyin_comments.csv"
    failed_filename: str = "failed_urls.csv"
    backfill_report_filename: str = "search_backfill_report.csv"

@dataclass
class LegalCfg:
    disclaimer: str = ""

@dataclass
class AppConfig:
    runtime: RuntimeCfg
    input: InputCfg
    search_backfill: SearchBackfillCfg
    extraction: ExtractionCfg
    output: OutputCfg
    legal: LegalCfg

def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    if path.suffix.lower() in [".yaml", ".yml"]:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    elif path.suffix.lower() == ".json":
        import json
        cfg = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError("Config must be .yaml/.yml or .json")

    runtime = RuntimeCfg(**cfg.get("runtime", {}))
    input_cfg = InputCfg(**cfg.get("input", {}))
    search_backfill = SearchBackfillCfg(**cfg.get("search_backfill", {}))
    extraction = ExtractionCfg(**cfg.get("extraction", {}))
    output = OutputCfg(**cfg.get("output", {}))
    legal = LegalCfg(**cfg.get("legal", {}))

    return AppConfig(runtime=runtime, input=input_cfg, search_backfill=search_backfill,
                     extraction=extraction, output=output, legal=legal)
