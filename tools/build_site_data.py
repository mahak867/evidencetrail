"""Export the data the static demo site replays: evaluation results, scorecard, metadata, audit log.
The captured live incident (site/data/live_run.json, health_*.json, series.json) is kept as is.

  python tools/build_site_data.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from evidencetrail import server  # noqa: E402

out = ROOT / "site" / "data"
out.mkdir(parents=True, exist_ok=True)


def dump(name, obj):
    (out / f"{name}.json").write_text(json.dumps(obj, default=str))


dump("meta", server.meta())
rec = server.recorded()
live = json.loads((out / "live_run.json").read_text())
rec.insert(0, {"id": "LIVE", "set": "live capture 19 Nov", "truth": {"service": "payment", "fault_type": "bad_deploy"},
               "alert": live["alert"], "result": live["result"]})
dump("recorded", rec)
dump("scorecard", server.scorecard_json())
dump("audit", server.audit_log(200))
print(f"site data: {len(rec)} recorded runs; sets: {list(server.scorecard_json())}")
