"""regen_report.py — re-render matriz.md/json from the last run's saved matriz.json,
without re-running the agents. Use after editing matrix.py wording."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import matrix as mx  # noqa

data = json.loads((HERE / "report" / "matriz.json").read_text())
caps = data["capabilities"]
runs = data["niche_runs_brain"]
prod_runs = data.get("niche_runs_prod_cheap", {})
prod_cheap = data.get("prod_cheap_headline", {})
opus_live = data.get("opus_as_brain_live")
brain = data.get("brain_model", "gpt-4o-mini")

grid = mx.build_grid(caps, runs, brain_label=brain)
md, js = mx.write_reports(HERE / "report", caps, runs, grid, prod_cheap, opus_live,
                          prod_runs=prod_runs, brain_label=brain)
print("regenerado:", md)
