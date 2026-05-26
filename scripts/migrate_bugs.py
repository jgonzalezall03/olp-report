from sqlalchemy import text
from api.db import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE metrics_snapshots ADD COLUMN IF NOT EXISTS bugs_count INTEGER DEFAULT 0"))
    conn.commit()
print("Migration applied: bugs_count")
