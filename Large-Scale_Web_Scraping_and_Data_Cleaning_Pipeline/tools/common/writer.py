import json
from datetime import datetime, timezone
from pathlib import Path


class JsonlWriter:
    def __init__(self, path: Path):
        self.f = open(path, "w", encoding="utf-8")

    def write(self, obj):
        self.f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def close(self):
        self.f.close()


class RollingWriter:
    """每 10k 行滚动分卷，命名 site_YYYYMMDD_HHMM_partNN.jsonl"""

    def __init__(self, out_dir: Path, site_name: str, chunk_size: int = 10_000):
        self.out_dir = out_dir
        self.site = site_name
        self.chunk_size = chunk_size
        self.count = 0
        self.part = 1
        self._open_new()

    def _open_new(self):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        name = f"site_{stamp}_part{self.part:02d}.jsonl"
        self.fp = open(self.out_dir / name, "w", encoding="utf-8")

    def write(self, obj):
        self.fp.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.count += 1
        if self.count % self.chunk_size == 0:
            self.fp.close()
            self.part += 1
            self._open_new()
