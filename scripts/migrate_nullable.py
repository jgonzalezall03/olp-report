from sqlalchemy import text
from api.db import engine

with engine.connect() as conn:
    conn.execute(text("ALTER TABLE jira_sprints ALTER COLUMN name DROP NOT NULL"))
    conn.execute(text("ALTER TABLE jira_sprints ALTER COLUMN sprint_name DROP NOT NULL") if False else text("SELECT 1"))
    conn.commit()
print("Migration applied")
