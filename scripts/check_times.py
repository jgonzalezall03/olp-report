import sys
from api.db import SessionLocal
from api.models import MetricsSnapshot, JiraProject

s = SessionLocal()
for key in ["OLP", "UA", "DCV"]:
    p = s.query(JiraProject).filter(JiraProject.key == key).first()
    if not p:
        continue
    ms = s.query(MetricsSnapshot).filter(MetricsSnapshot.project_id == p.id).all()
    sys.stdout.write(f"\n{key} ({len(ms)} snapshots):\n")
    for m in ms:
        sys.stdout.write(f"  {m.sprint_name} | lead_avg={m.lead_time_avg} | cycle_avg={m.cycle_time_avg} | completed={m.completed}\n")
s.close()
