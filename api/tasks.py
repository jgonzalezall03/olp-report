from celery import shared_task
from sqlalchemy.orm import Session

from . import db
from .models import JiraProject
from .seed import _fetch_metrics, _save_metrics


def _sync_project(project_key: str, session: Session) -> str:
    project = session.query(JiraProject).filter(JiraProject.key == project_key).first()
    if not project:
        return f"Project {project_key} not found"
    metrics = _fetch_metrics(project)
    _save_metrics(project, metrics, session)
    return f"Synced {len(metrics)} buckets for {project_key}"


@shared_task
def fetch_project_metrics(project_key: str):
    session = db.SessionLocal()
    try:
        result = _sync_project(project_key, session)
    finally:
        session.close()
    return result


@shared_task
def fetch_all_projects_metrics():
    session = db.SessionLocal()
    try:
        project_keys = [project.key for project in session.query(JiraProject).filter(JiraProject.active.is_(True)).all()]
    finally:
        session.close()

    for project_key in project_keys:
        fetch_project_metrics.delay(project_key)
    return f"Triggered sync for {len(project_keys)} active projects"
