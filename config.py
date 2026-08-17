# Step1 Grounder v2 - Config (NO argparse)
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

@dataclass
class Config:
    ttl_path: Path
    structured_terms_csv: Path
    table_layout_csv: Path
    table_ref_csv: Path
    sample_query: str
    out_dir: Path
    data_dir: Path
    topk_per_mention: int

    def setSampleQuery(self, q: str):
        self.sample_query = q

    def setTtlPath(self, path: str):
        self.ttl_path = Path(path)

    def setStructuredTermsCsv(self, path: str):
        self.structured_terms_csv = Path(path)

    def setTableLayoutCsv(self, path: str):
        self.table_layout_csv = Path(path)

    def setTableRefCsv(self, path: str):
        self.table_ref_csv = Path(path)

CFG = Config(
    ttl_path=Path(""),
    structured_terms_csv=Path(""),
    table_layout_csv=Path(""),
    table_ref_csv=Path(""),
    sample_query="",
    out_dir=Path(__file__).parent / "out",
    data_dir=Path(__file__).parent / "data",
    topk_per_mention=3,
)

if __name__ == "__main__":
    CFG.out_dir.mkdir(parents=True, exist_ok=True)
    print("Config loaded:")
    print(" - ttl_path:", CFG.ttl_path)
    print(" - structured_terms_csv:", CFG.structured_terms_csv)
    print(" - out_dir:", CFG.out_dir)
    print(" - topk_per_mention:", CFG.topk_per_mention)
    print(" - sample_query:", CFG.sample_query)
