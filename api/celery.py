import os
from celery import Celery

BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

celery_app = Celery(
    "api",
    broker=BROKER_URL,
    backend=RESULT_BACKEND,
    include=["api.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "fetch-all-projects-daily": {
            "task": "api.tasks.fetch_all_projects_metrics",
            "schedule": 86400.0,
            "options": {"queue": "default"},
        },
    },
)
