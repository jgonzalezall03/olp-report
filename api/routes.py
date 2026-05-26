from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import db
from .models import JiraProject, MetricsSnapshot
from .schemas import MetricsSnapshotSchema, ProjectSchema, SyncResponse
from .tasks import fetch_project_metrics, fetch_all_projects_metrics

router = APIRouter()


def get_db():
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/projects/", response_model=list[ProjectSchema])
def get_projects(db: Session = Depends(get_db)):
    projects = db.query(JiraProject).filter(JiraProject.active.is_(True)).all()
    return projects


@router.get("/projects/{project_key}/metrics/", response_model=list[MetricsSnapshotSchema])
def get_project_metrics(project_key: str, db: Session = Depends(get_db)):
    project = db.query(JiraProject).filter(JiraProject.key == project_key).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    metrics = (
        db.query(MetricsSnapshot)
        .filter(MetricsSnapshot.project_id == project.id)
        .order_by(MetricsSnapshot.id)
        .all()
    )
    return metrics


@router.post("/projects/{project_key}/sync/", response_model=SyncResponse)
def post_project_sync(project_key: str):
    task = fetch_project_metrics.delay(project_key)
    return {
        "status": "queued",
        "detail": f"Task {task.id} queued to sync project {project_key}.",
    }


@router.post("/sync/", response_model=SyncResponse)
def post_sync_all():
    task = fetch_all_projects_metrics.delay()
    return {
        "status": "queued",
        "detail": f"Task {task.id} queued to sync all active projects.",
    }
