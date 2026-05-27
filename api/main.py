import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi import Form
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from . import db
from .db import init_db
from .models import JiraProject, MetricsSnapshot, AssigneeSnapshot
from .routes import router as api_router
from .auth import authenticate, clear_session, get_auth_settings, require_login

BASE_DIR = Path(__file__).resolve().parent

def _metrics_to_json(metrics):
    def serialize(m):
        return {
            "sprint_name": m.sprint_name,
            "sprint_start_date": m.sprint_start_date.isoformat() if m.sprint_start_date else None,
            "completed": m.completed,
            "velocity": m.velocity,
            "lead_time_avg": m.lead_time_avg,
            "lead_time_med": m.lead_time_med,
            "cycle_time_avg": m.cycle_time_avg,
            "cycle_time_med": m.cycle_time_med,
            "total_issues": m.total_issues,
            "bugs_count": m.bugs_count,
        }
    return Markup(json.dumps([serialize(m) for m in metrics], ensure_ascii=False))


jinja_env = Environment(
    loader=FileSystemLoader(str(BASE_DIR / "templates")),
    autoescape=select_autoescape(["html", "xml"]),
)
jinja_env.filters["tojson"] = lambda v: json.dumps(v) if not isinstance(v, str) else v


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


def render_template(name: str, context: dict) -> HTMLResponse:
    template = jinja_env.get_template(name)
    return HTMLResponse(template.render(**context))

app = FastAPI(
    title="OLP Dashboard API",
    description="FastAPI service for Jira OLP dashboards and metric sync.",
    lifespan=lifespan,
)
app.include_router(api_router, prefix="/api")

username, password, secret_key = get_auth_settings()
app.add_middleware(SessionMiddleware, secret_key=secret_key)


def get_db():
    session = db.SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/dashboard")


@app.get("/home", response_class=HTMLResponse)
def home_view(request: Request, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")

    projects = db.query(JiraProject).filter(JiraProject.active.is_(True)).order_by(JiraProject.name).all()

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    rows = []
    for p in projects:
        snaps = (
            db.query(MetricsSnapshot)
            .filter(
                MetricsSnapshot.project_id == p.id,
                MetricsSnapshot.sprint_start_date >= cutoff,
            )
            .order_by(MetricsSnapshot.sprint_start_date.asc().nullslast())
            .all()
        )
        if not snaps:
            snaps = (
                db.query(MetricsSnapshot)
                .filter(MetricsSnapshot.project_id == p.id)
                .order_by(MetricsSnapshot.sprint_start_date.desc().nullslast())
                .limit(3)
                .all()
            )
            snaps = list(reversed(snaps))

        if not snaps:
            rows.append({"project": p, "empty": True})
            continue

        def _avg(vals):
            v = [x for x in vals if x is not None]
            return round(sum(v) / len(v), 1) if v else None

        last = snaps[-1]
        prev = snaps[-2] if len(snaps) >= 2 else None

        throughput = _avg([s.completed for s in snaps])
        lead       = _avg([s.lead_time_avg for s in snaps])
        cycle      = _avg([s.cycle_time_avg for s in snaps])
        flow       = round(cycle / lead * 100, 0) if lead and cycle else None
        bugs       = _avg([s.bugs_count for s in snaps])
        velocity   = _avg([s.velocity for s in snaps])

        def _trend(curr, prev_val, lower_better=False):
            if curr is None or prev_val is None:
                return "neutral"
            if curr == prev_val:
                return "neutral"
            better = curr < prev_val if lower_better else curr > prev_val
            return "up" if better else "down"

        rows.append({
            "project": p,
            "empty": False,
            "periods": len(snaps),
            "last_period": last.sprint_name,
            "throughput": throughput,
            "throughput_trend": _trend(last.completed, prev.completed if prev else None),
            "lead": lead,
            "lead_trend": _trend(last.lead_time_avg, prev.lead_time_avg if prev else None, lower_better=True),
            "cycle": cycle,
            "cycle_trend": _trend(last.cycle_time_avg, prev.cycle_time_avg if prev else None, lower_better=True),
            "flow": flow,
            "bugs": bugs,
            "velocity": velocity,
        })

    return render_template("home.html", {"request": request, "rows": rows})


@app.get("/login", response_class=HTMLResponse)
def login_view(request: Request):
    return render_template("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if authenticate(username, password):
        request.session["user"] = username
        return RedirectResponse(url="/dashboard", status_code=303)
    return render_template("login.html", {"request": request, "error": "Usuario o contraseña incorrectos."})


@app.get("/logout", response_class=HTMLResponse)
def logout(request: Request):
    clear_session(request)
    return RedirectResponse(url="/login", status_code=303)


def assert_authenticated(request: Request):
    if not require_login(request):
        return RedirectResponse(url="/login")

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, project: str | None = None, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")
    projects = db.query(JiraProject).filter(JiraProject.active.is_(True)).order_by(JiraProject.key).all()
    selected_project = None
    if project:
        selected_project = db.query(JiraProject).filter(JiraProject.key == project).first()
    if not selected_project and projects:
        selected_project = projects[0]

    metrics = []
    if selected_project:
        metrics = (
            db.query(MetricsSnapshot)
            .filter(MetricsSnapshot.project_id == selected_project.id)
            .order_by(MetricsSnapshot.sprint_start_date.asc().nullslast(), MetricsSnapshot.id)
            .all()
        )

    # WIP en tiempo real para Kanban
    wip_count = 0
    wip_items = []
    if selected_project and selected_project.is_kanban:
        try:
            from .services.jira_service import JiraClient
            from datetime import datetime, timezone
            client = JiraClient()
            active = client._get_all(
                client.base + "/search/jql",
                {"jql": f"project = {selected_project.key} AND statusCategory != Done ORDER BY created ASC",
                 "fields": "summary,status,created", "maxResults": 50},
                key="issues",
            )
            now = datetime.now(timezone.utc)
            wip_count = len(active)
            wip_items = [{
                "key": i["key"],
                "summary": i["fields"].get("summary", ""),
                "status": i["fields"]["status"]["name"],
                "age_days": max(0, (now - datetime.fromisoformat(
                    i["fields"]["created"].replace("Z", "+00:00")
                )).days),
            } for i in active]
            wip_items.sort(key=lambda x: x["age_days"], reverse=True)
        except Exception:
            pass

    template = "dashboard_kanban.html" if (selected_project and selected_project.is_kanban) else "dashboard_scrum.html"

    return render_template(template, {
        "request": request,
        "projects": projects,
        "selected_project": selected_project,
        "metrics": _metrics_to_json(metrics),
        "wip_count": wip_count,
        "wip_items": wip_items,
    })


@app.get("/admin/projects", response_class=HTMLResponse)
def admin_projects(request: Request, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")
    projects = db.query(JiraProject).order_by(JiraProject.key).all()
    return render_template("admin_projects.html", {
        "request": request,
        "projects": projects,
        "flash": request.session.pop("flash", None),
    })


@app.post("/admin/projects/{key}/toggle", response_class=HTMLResponse)
def admin_toggle(key: str, request: Request, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")
    project = db.query(JiraProject).filter(JiraProject.key == key).first()
    if project:
        project.active = not project.active
        db.commit()
        state = "activado" if project.active else "desactivado"
        request.session["flash"] = {"type": "success", "msg": f"{key} {state} correctamente."}
    return RedirectResponse(url="/admin/projects", status_code=303)


@app.post("/admin/projects/{key}/delete", response_class=HTMLResponse)
def admin_delete(key: str, request: Request, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")
    project = db.query(JiraProject).filter(JiraProject.key == key).first()
    if project:
        db.delete(project)
        db.commit()
        request.session["flash"] = {"type": "warn", "msg": f"{key} eliminado permanentemente."}
    return RedirectResponse(url="/admin/projects", status_code=303)


@app.post("/admin/projects/add", response_class=HTMLResponse)
def admin_add(
    request: Request,
    key: str = Form(...),
    name: str = Form(...),
    board_id: int = Form(...),
    is_kanban: str = Form("off"),
    db: Session = Depends(get_db),
):
    if not require_login(request):
        return RedirectResponse(url="/login")
    existing = db.query(JiraProject).filter(JiraProject.key == key.upper()).first()
    if existing:
        request.session["flash"] = {"type": "warn", "msg": f"{key.upper()} ya existe."}
    else:
        project = JiraProject(
            key=key.upper(), name=name, board_id=board_id,
            is_kanban=(is_kanban == "on"), active=True,
        )
        db.add(project)
        db.commit()
        request.session["flash"] = {"type": "success", "msg": f"{key.upper()} agregado. Recuerda sincronizarlo."}
    return RedirectResponse(url="/admin/projects", status_code=303)


@app.post("/admin/projects/{key}/sync-now", response_class=HTMLResponse)
def admin_sync_now(key: str, request: Request):
    if not require_login(request):
        return RedirectResponse(url="/login")
    from .seed import sync_project
    try:
        result = sync_project(key)
        request.session["flash"] = {"type": "success", "msg": result}
    except Exception as e:
        request.session["flash"] = {"type": "warn", "msg": f"Error sincronizando {key}: {e}"}
    return RedirectResponse(url="/admin/projects", status_code=303)


@app.get("/assignees/{project_key}", response_class=HTMLResponse)
def assignees_view(project_key: str, request: Request, db: Session = Depends(get_db)):
    if not require_login(request):
        return RedirectResponse(url="/login")
    project = db.query(JiraProject).filter(JiraProject.key == project_key).first()
    if not project:
        return RedirectResponse(url="/home")

    rows = db.query(AssigneeSnapshot).filter(
        AssigneeSnapshot.project_id == project.id
    ).order_by(AssigneeSnapshot.period.asc(), AssigneeSnapshot.assignee.asc()).all()

    import json as _json
    from markupsafe import Markup
    data = [
        {
            "assignee": r.assignee,
            "period": r.period,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "completed": r.completed,
            "lead_time_avg": r.lead_time_avg,
            "cycle_time_avg": r.cycle_time_avg,
            "bugs_count": r.bugs_count,
        }
        for r in rows
    ]
    projects = db.query(JiraProject).filter(JiraProject.active.is_(True)).order_by(JiraProject.name).all()
    return render_template("assignees.html", {
        "request": request,
        "project": project,
        "projects": projects,
        "data": Markup(_json.dumps(data, ensure_ascii=False)),
    })
