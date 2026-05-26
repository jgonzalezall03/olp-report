from sqlalchemy import text
from api.db import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE jira_projects ADD COLUMN IF NOT EXISTS is_kanban BOOLEAN DEFAULT FALSE"))
    conn.commit()
print("Migration applied: is_kanban")
