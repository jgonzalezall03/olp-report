import argparse

from .db import init_db
from . import db
from .models import JiraProject, JiraSprint, MetricsSnapshot
from .services.jira_service import JiraClient, parse_date


def _fetch_metrics(project):
    client = JiraClient()
    if project.is_kanban:
        metrics, wip = client.compute_kanban_metrics(
            project_key=project.key,
            story_points_field=project.story_points_field,
        )
    else:
        metrics, wip = client.compute_metrics(
            project_key=project.key,
            board_id=project.board_id,
            story_points_field=project.story_points_field,
            sprint_field=project.sprint_field,
        )
    return metrics


def _save_metrics(project, metrics, session):
    for sprint_data in metrics:
        sprint_obj = None
        if sprint_data["sprint_id"] is not None:
            sprint_obj = session.query(JiraSprint).filter(
                JiraSprint.project_id == project.id,
                JiraSprint.jira_id == sprint_data["sprint_id"],
            ).first()
            if not sprint_obj:
                sprint_obj = JiraSprint(project_id=project.id, jira_id=sprint_data["sprint_id"])
                session.add(sprint_obj)
                session.flush()
            sprint_obj.name = sprint_data["sprint"]
            sprint_obj.state = "active" if sprint_data["end"] is None else "closed"
            sprint_obj.start_date = parse_date(sprint_data["start"])
            sprint_obj.end_date = parse_date(sprint_data["end"])

        snapshot = session.query(MetricsSnapshot).filter(
            MetricsSnapshot.project_id == project.id,
            MetricsSnapshot.sprint_name == sprint_data["sprint"],
        ).first()
        if not snapshot:
            snapshot = MetricsSnapshot(
                project_id=project.id,
                sprint=sprint_obj,
                sprint_name=sprint_data["sprint"],
            )
            session.add(snapshot)

        snapshot.sprint_start_date = parse_date(sprint_data["start"])
        snapshot.completed = sprint_data["completed"]
        snapshot.velocity = sprint_data["velocity"]
        snapshot.lead_time_avg = sprint_data["lead_time_avg"]
        snapshot.lead_time_med = sprint_data["lead_time_med"]
        snapshot.cycle_time_avg = sprint_data["cycle_time_avg"]
        snapshot.cycle_time_med = sprint_data["cycle_time_med"]
        snapshot.total_issues = sprint_data["total_issues"]
        snapshot.bugs_count = sprint_data.get("bugs", 0)

    session.commit()


def sync_project(project_key: str):
    session = db.SessionLocal()
    try:
        project = session.query(JiraProject).filter(JiraProject.key == project_key).first()
        if not project:
            raise ValueError(f"Project {project_key} not found in database")
        metrics = _fetch_metrics(project)
        _save_metrics(project, metrics, session)
        return f"Synced {len(metrics)} buckets for {project_key}"
    finally:
        session.close()


def create_project(project_key: str, board_id: int, name: str | None = None, is_kanban: bool = False):
    session = db.SessionLocal()
    try:
        project = session.query(JiraProject).filter(JiraProject.key == project_key).first()
        if not project:
            project = JiraProject(key=project_key, name=name or project_key, board_id=board_id, is_kanban=is_kanban)
            session.add(project)
            session.commit()
        elif project.board_id != board_id or project.is_kanban != is_kanban:
            project.board_id = board_id
            project.is_kanban = is_kanban
            session.commit()
        return project
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="FastAPI OLP seed and sync utility")
    parser.add_argument("--project-key", required=True)
    parser.add_argument("--board-id", type=int, required=True)
    parser.add_argument("--project-name", type=str, help="Display name for the project")
    args = parser.parse_args()

    init_db()
    create_project(args.project_key, args.board_id, args.project_name)
    print(sync_project(args.project_key))


if __name__ == "__main__":
    main()
