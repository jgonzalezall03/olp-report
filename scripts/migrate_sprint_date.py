from sqlalchemy import text
from api.db import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE metrics_snapshots ADD COLUMN IF NOT EXISTS sprint_start_date TIMESTAMP"))
    conn.commit()
print("Migration applied: sprint_start_date")
