from api.db import SessionLocal
from api.models import MetricsSnapshot, JiraProject

s = SessionLocal()
p = s.query(JiraProject).filter(JiraProject.key == 'OLP').first()
print("Project:", p.id, p.name)
ms = s.query(MetricsSnapshot).filter(MetricsSnapshot.project_id == p.id).all()
print("Snapshots:", len(ms))
for m in ms:
    print(m.sprint_name, '|', m.sprint_start_date, '|', m.completed, '|', m.velocity)
s.close()
