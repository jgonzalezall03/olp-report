"""
OLP – Informe de Tendencias (6 Meses)
======================================
Recolecta datos de Jira, calcula metricas, genera charts y publica
en Confluence (espacio Olimpo).

Metricas: Velocity, Throughput, Lead Time, Cycle Time,
          Carga por Persona, Distribucion Tipo/Prioridad, WIP, Aging.

Uso:
  python3 olp_report.py [--publish] [--page-id ID]

  --publish   Publica en Confluence (si no, solo genera charts local)
  --page-id   ID de pagina de Confluence a actualizar (crea nueva si no se especifica)
"""

import json
import os
import base64
import argparse
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import requests
import pandas as pd
import numpy as np

# ─── Configuracion ───────────────────────────────────────────────────────────

ATLASSIAN_SITE = os.getenv("ATLASSIAN_SITE", "https://aurusjoyeria.atlassian.net")
ATLASSIAN_EMAIL = os.getenv("ATLASSIAN_EMAIL", "agonzalez@nxtara.com")
ATLASSIAN_TOKEN = os.getenv("ATLASSIAN_TOKEN")
if not ATLASSIAN_TOKEN:
    token_file = os.getenv("ATLASSIAN_TOKEN_FILE", "~/.config/opencode/atlassian-token.txt")
    token_path = os.path.expanduser(token_file)
    if os.path.exists(token_path):
        with open(token_path, "r", encoding="utf-8") as f:
            ATLASSIAN_TOKEN = f.read().strip()

BOARD_ID = int(os.getenv("OLP_BOARD_ID", "2"))
PROJECT_KEY = os.getenv("OLP_PROJECT_KEY", "OLP")
MONTHS_BACK = 6
STORY_POINTS_FIELD = "customfield_10016"
SPRINT_FIELD = "customfield_10020"

# Estados del flujo (de board/2/configuration + /rest/api/2/status)
STATUS_TODO = {"10020", "10101", "10039", "10041"}       # category 2
STATUS_IN_PROGRESS = {"10040", "10103", "10104", "10042", "10105", "10044"}  # category 4
STATUS_DONE = {"10022", "10102"}                          # category 3

CONFLUENCE_SPACE_KEY = "O"
CONFLUENCE_PARENT_ID = "33085"  # Olimpo Home

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# ─── Jira Client ─────────────────────────────────────────────────────────────

class JiraClient:
    def __init__(self):
        self.auth = (ATLASSIAN_EMAIL, ATLASSIAN_TOKEN)
        self.headers = {"Accept": "application/json"}
        self.base = f"{ATLASSIAN_SITE}/rest/api/2"
        self.agile_base = f"{ATLASSIAN_SITE}/rest/agile/1.0"

    def _get(self, url, params=None):
        r = requests.get(url, auth=self.auth, headers=self.headers, params=params)
        r.raise_for_status()
        return r.json()

    def _get_all(self, url, params=None, key="values"):
        params = params or {}
        all_data = []
        while True:
            r = requests.get(url, auth=self.auth, headers=self.headers, params=params)
            r.raise_for_status()
            data = r.json()
            all_data.extend(data.get(key, []))
            # Jira Cloud new pagination (search/jql)
            if "nextPageToken" in data and data.get("isLast") is False:
                params["nextPageToken"] = data["nextPageToken"]
                # Clean URL for next iteration
                base_url = url.split("?")[0] if "?" in url else url
                url = base_url
            # Standard pagination (agile API)
            elif "isLast" in data and data.get("isLast") is False:
                params["startAt"] = data.get("startAt", 0) + len(data.get(key, []))
                base_url = url.split("?")[0] if "?" in url else url
                url = base_url
            else:
                break
        return all_data

    def get_sprints(self):
        url = f"{self.agile_base}/board/{BOARD_ID}/sprint"
        params = {"state": "closed,active", "maxResults": 200}
        all_sprints = self._get_all(url, params)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MONTHS_BACK * 30 + 15)
        return [
            s for s in all_sprints
            if datetime.fromisoformat(s["startDate"].replace("Z", "+00:00")) > cutoff
        ][-12:]  # max 12 sprints

    def get_sprint_issues(self, sprint_id):
        jql = f"project = {PROJECT_KEY} AND Sprint = {sprint_id}"
        params = {
            "jql": jql,
            "fields": f"summary,status,assignee,issuetype,priority,created,resolutiondate,"
                      f"resolution,updated,{STORY_POINTS_FIELD},{SPRINT_FIELD}",
            "maxResults": 200,
        }
        return self._get_all(f"{self.base}/search", params, key="issues")

    def get_completed_with_changelogs(self, sprint_id):
        jql = f"project = {PROJECT_KEY} AND Sprint = {sprint_id} AND status IN (DONE, Terminado)"
        params = {
            "jql": jql,
            "fields": "key,resolutiondate,status",
            "expand": "changelog",
            "maxResults": 200,
        }
        issues = self._get_all(f"{self.base}/search/jql", params, key="issues")
        return {i["key"]: i.get("changelog", {}).get("histories", []) for i in issues}

    def get_active_issues(self):
        jql = f"project = {PROJECT_KEY} AND status NOT IN (DONE, Finalizada, Closed) "
        params = {
            "jql": jql,
            "fields": f"summary,status,assignee,issuetype,priority,created,updated,"
                      f"{STORY_POINTS_FIELD},{SPRINT_FIELD}",
            "maxResults": 200,
        }
        return self._get_all(f"{self.base}/search", params, key="issues")


# ─── Metrics Calculator ──────────────────────────────────────────────────────

def parse_date(d):
    if not d:
        return None
    return datetime.fromisoformat(d.replace("Z", "+00:00"))

STATUS_NAME_TO_ID = None

def get_first_in_progress(histories):
    """From a changelog (newest-first), find the first (oldest) entry where
    the issue entered an 'in progress' status (category 4)."""
    if not STATUS_NAME_TO_ID:
        return None
    # Search from the END (oldest entries first)
    for entry in reversed(histories):
        for item in entry.get("items", []):
            if item.get("field") == "status":
                to_status = item.get("toString")
                to_id = STATUS_NAME_TO_ID.get(to_status)
                if to_id and (to_id in STATUS_IN_PROGRESS or to_id in STATUS_DONE):
                    return parse_date(entry.get("created"))
    return None

def build_status_map():
    global STATUS_NAME_TO_ID
    if STATUS_NAME_TO_ID:
        return
    client = JiraClient()
    name_to_id = {}
    for sid in list(STATUS_TODO | STATUS_IN_PROGRESS | STATUS_DONE):
        data = client._get(f"{ATLASSIAN_SITE}/rest/api/2/status/{sid}")
        name_to_id[data["name"]] = sid
    STATUS_NAME_TO_ID = name_to_id

def compute_metrics(jira, sprints):
    build_status_map()

    total_issues = 0
    for sprint in sprints:
        sid = sprint["id"]
        print(f"  Sprint {sprint['name']} (id={sid})...")
        issues = jira.get_sprint_issues(sid)
        sprint["_issues"] = issues
        total_issues += len(issues)

        # Fetch changelogs for completed issues
        print(f"    → fetching changelogs for completed issues...")
        sprint["_changelogs"] = jira.get_completed_with_changelogs(sid)

    print(f"  Total issues fetched: {total_issues}")

    # Compute per-sprint metrics
    metrics = []
    all_issue_records = []

    for sprint in sprints:
        sid = sprint["id"]
        issues = sprint.get("_issues", [])
        changelogs = sprint.get("_changelogs", {})
        sprint_name = sprint["name"].replace("Tablero ", "")
        start_date = parse_date(sprint.get("startDate"))
        end_date = parse_date(sprint.get("endDate"))

        completed_issues = []
        completed_points = 0
        lead_times = []
        cycle_times = []
        assignee_counts = defaultdict(int)
        type_counts = defaultdict(int)
        priority_counts = defaultdict(int)

        for issue in issues:
            fields = issue.get("fields", {})
            key = issue["key"]
            created = parse_date(fields.get("created"))
            resolutiondate = parse_date(fields.get("resolutiondate"))
            status_id = fields.get("status", {}).get("id", "")
            status_name = fields.get("status", {}).get("name", "")
            story_points = fields.get(STORY_POINTS_FIELD)
            if story_points is None:
                story_points = 0
            elif isinstance(story_points, dict):
                story_points = 0
            assignee = fields.get("assignee")
            assignee_name = assignee["displayName"] if assignee else "Sin asignar"
            issuetype = fields.get("issuetype", {}).get("name", "Unknown")
            priority = fields.get("priority", {}).get("name", "Unknown")

            is_done = resolutiondate is not None or status_id in STATUS_DONE

            all_issue_records.append({
                "sprint": sprint_name,
                "sprint_id": sid,
                "key": key,
                "summary": fields.get("summary", ""),
                "assignee": assignee_name,
                "issuetype": issuetype,
                "priority": priority,
                "status": status_name,
                "created": created,
                "resolutiondate": resolutiondate,
                "story_points": story_points,
                "is_done": is_done,
            })

            if is_done:
                completed_issues.append(key)
                if story_points:
                    completed_points += story_points
                if created and resolutiondate:
                    lead_time = (resolutiondate - created).total_seconds() / 86400
                    lead_times.append(lead_time)

                    # Cycle time: from first "In Progress" to resolution
                    histories = changelogs.get(key, [])
                    first_ip = get_first_in_progress(histories)
                    if first_ip and first_ip < resolutiondate:
                        cycle_time = (resolutiondate - first_ip).total_seconds() / 86400
                        cycle_times.append(cycle_time)

            assignee_counts[assignee_name] += 1
            type_counts[issuetype] += 1
            priority_counts[priority] += 1

        metrics.append({
            "sprint": sprint_name,
            "sprint_id": sid,
            "start": start_date,
            "end": end_date,
            "completed": len(completed_issues),
            "velocity": completed_points,
            "lead_time_avg": round(np.mean(lead_times), 1) if lead_times else None,
            "lead_time_med": round(np.median(lead_times), 1) if lead_times else None,
            "cycle_time_avg": round(np.mean(cycle_times), 1) if cycle_times else None,
            "cycle_time_med": round(np.median(cycle_times), 1) if cycle_times else None,
            "total_issues": len(issues),
            "assignees": dict(assignee_counts),
            "types": dict(type_counts),
            "priorities": dict(priority_counts),
        })

    return metrics, all_issue_records


def compute_wip_history(active_issues, metrics):
    """Compute current WIP and aging from active issues."""
    now = datetime.now(timezone.utc)
    ages = []
    type_wip = defaultdict(int)
    assignee_wip = defaultdict(int)
    for issue in active_issues:
        fields = issue.get("fields", {})
        created = parse_date(fields.get("created"))
        if created:
            age_days = (now - created).total_seconds() / 86400
            ages.append(age_days)
        assignee = fields.get("assignee")
        assignee_name = assignee["displayName"] if assignee else "Sin asignar"
        issuetype = fields.get("issuetype", {}).get("name", "Unknown")
        type_wip[issuetype] += 1
        assignee_wip[assignee_name] += 1

    return {
        "total_wip": len(active_issues),
        "ages": ages,
        "type_wip": dict(type_wip),
        "assignee_wip": dict(assignee_wip),
    }


# ─── Chart Generator (Plotly) ────────────────────────────────────────────────

import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.io as pio

COLORS = ["#2563eb", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16"]
PLOTLY_TEMPLATE = "plotly_white"

CHART_HEIGHT = 700
CHART_WIDTH = 1800

def save_chart(fig, name):
    """Save chart as interactive HTML + static PNG."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    html_path = os.path.join(OUTPUT_DIR, f"{name}.html")
    fig.update_layout(height=CHART_HEIGHT)
    fig.write_html(html_path, include_plotlyjs="cdn", full_html=False,
                   config={"responsive": True})
    png_path = os.path.join(OUTPUT_DIR, f"{name}.png")
    try:
        fig.write_image(png_path, width=CHART_WIDTH * 2, height=CHART_HEIGHT * 2, scale=1)
    except Exception:
        pass
    print(f"  Chart saved: {name}.html + {name}.png")
    return html_path, png_path

def chart_velocity_throughput(metrics):
    names = [m["sprint"] for m in metrics]
    throughput = [m["completed"] for m in metrics]
    velocity = [m["velocity"] or 0 for m in metrics]
    x = list(range(len(names)))

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=names, y=throughput, name="Throughput (issues)",
        marker_color=COLORS[0], opacity=0.75,
        hovertemplate="Sprint: %{x}<br>Issues: %{y}<extra>Throughput</extra>"
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=names, y=velocity, name="Velocity (story points)",
        marker_color=COLORS[1], line=dict(width=3), mode="lines+markers",
        marker=dict(size=10),
        hovertemplate="Sprint: %{x}<br>Story Points: %{y}<extra>Velocity</extra>"
    ), secondary_y=True)

    if len(names) > 1:
        z = np.polyfit(x, velocity, 1)
        p = np.poly1d(z)
        fig.add_trace(go.Scatter(
            x=names, y=p(x), name="Tendencia velocity",
            line=dict(dash="dash", width=1.5, color=COLORS[1]),
            opacity=0.5, showlegend=False,
            hovertemplate="%{y:.1f}<extra>Tendencia</extra>"
        ), secondary_y=True)

    fig.update_yaxes(title_text="Issues completadas", secondary_y=False, color=COLORS[0])
    fig.update_yaxes(title_text="Story Points", secondary_y=True, color=COLORS[1])
    fig.update_layout(
        title=dict(text="<b>Velocidad y Throughput por Sprint</b>", x=0.5),
        template=PLOTLY_TEMPLATE, hovermode="x unified", height=CHART_HEIGHT,
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
        xaxis=dict(tickangle=-30)
    )
    return save_chart(fig, "01_velocity_throughput")


def chart_lead_cycle_time(metrics):
    names = [m["sprint"] for m in metrics]
    lt = [m["lead_time_avg"] or 0 for m in metrics]
    ct = [m["cycle_time_avg"] or 0 for m in metrics]

    has_data = any(v > 0 for v in lt)
    fig = go.Figure()

    if not has_data:
        fig.add_annotation(
            text="Sin datos de lead/cycle time<br>(no hay issues completadas en este periodo)",
            showarrow=False, font=dict(size=14, color="#888"),
            xref="paper", yref="paper", x=0.5, y=0.5
        )
    else:
        fig.add_trace(go.Scatter(
            x=names, y=lt, name="Lead Time (dias)",
            marker_color=COLORS[2], line=dict(width=3), mode="lines+markers",
            marker=dict(symbol="square", size=10),
            hovertemplate="Sprint: %{x}<br>Lead Time: %{y:.1f} dias<extra></extra>"
        ))
        fig.add_trace(go.Scatter(
            x=names, y=ct, name="Cycle Time (dias)",
            marker_color=COLORS[3], line=dict(width=3), mode="lines+markers",
            marker=dict(symbol="diamond", size=10),
            hovertemplate="Sprint: %{x}<br>Cycle Time: %{y:.1f} dias<extra></extra>"
        ))

        x = list(range(len(names)))
        if len(names) > 1:
            z_lt = np.polyfit(x, lt, 1)
            fig.add_trace(go.Scatter(
                x=names, y=np.poly1d(z_lt)(x),
                line=dict(dash="dash", width=1.5, color=COLORS[2]),
                opacity=0.4, showlegend=False, name=""
            ))
            z_ct = np.polyfit(x, ct, 1)
            fig.add_trace(go.Scatter(
                x=names, y=np.poly1d(z_ct)(x),
                line=dict(dash="dash", width=1.5, color=COLORS[3]),
                opacity=0.4, showlegend=False, name=""
            ))

    fig.update_layout(
        title=dict(text="<b>Lead Time y Cycle Time (promedio por sprint)</b>", x=0.5),
        template=PLOTLY_TEMPLATE, hovermode="x unified", height=CHART_HEIGHT,
        yaxis=dict(title="Dias"),
        xaxis=dict(tickangle=-30),
        legend=dict(orientation="h", y=1.08, x=0.5, xanchor="center"),
    )
    return save_chart(fig, "02_lead_cycle_time")


def chart_assignee_load(metrics):
    all_assignees = set()
    for m in metrics:
        all_assignees.update(m["assignees"].keys())
    sorted_assignees = sorted(all_assignees)
    names = [m["sprint"] for m in metrics]

    fig = go.Figure()
    for i, a in enumerate(sorted_assignees):
        vals = [m["assignees"].get(a, 0) for m in metrics]
        if sum(vals) == 0:
            continue
        fig.add_trace(go.Bar(
            name=a, x=names, y=vals,
            marker_color=COLORS[i % len(COLORS)],
            hovertemplate="Sprint: %{x}<br>%{fullData.name}: %{y}<extra></extra>"
        ))

    fig.update_layout(
        barmode="stack",
        title=dict(text="<b>Carga por Persona por Sprint</b>", x=0.5),
        template=PLOTLY_TEMPLATE, hovermode="x unified", height=CHART_HEIGHT,
        yaxis=dict(title="Issues"),
        xaxis=dict(tickangle=-30),
        legend=dict(orientation="h", y=1.08, font=dict(size=10)),
    )
    return save_chart(fig, "03_assignee_load")


def chart_distribution(metrics, dimension="issuetype"):
    names = [m["sprint"] for m in metrics]
    all_keys = set()
    for m in metrics:
        source = m["types"] if dimension == "issuetype" else m["priorities"]
        all_keys.update(source.keys())
    sorted_keys = sorted(all_keys)
    title_label = "Tipo" if dimension == "issuetype" else "Prioridad"
    suffix = "type" if dimension == "issuetype" else "priority"

    # Totals for pie
    totals = defaultdict(int)
    for m in metrics:
        source = m["types"] if dimension == "issuetype" else m["priorities"]
        for k, v in source.items():
            totals[k] += v

    fig = make_subplots(
        rows=1, cols=2,
        column_widths=[0.6, 0.4],
        specs=[[{"type": "bar"}, {"type": "pie"}]],
        subplot_titles=(f"Distribucion por {title_label}", f"Total 6M – {title_label}")
    )

    for i, k in enumerate(sorted_keys):
        vals = []
        for m in metrics:
            source = m["types"] if dimension == "issuetype" else m["priorities"]
            vals.append(source.get(k, 0))
        if sum(vals) == 0:
            continue
        fig.add_trace(go.Bar(
            name=k, x=names, y=vals,
            marker_color=COLORS[i % len(COLORS)],
            hovertemplate="Sprint: %{x}<br>%{fullData.name}: %{y}<extra></extra>"
        ), row=1, col=1)

    fig.add_trace(go.Pie(
        labels=list(totals.keys()),
        values=list(totals.values()),
        textinfo="label+percent",
        hole=0.4,
        marker=dict(colors=COLORS[:len(totals)]),
        hovertemplate="%{label}: %{value} (%{percent})<extra></extra>"
    ), row=1, col=2)

    fig.update_layout(
        barmode="stack",
        title=dict(text=f"<b>Distribucion por {title_label}</b>", x=0.5),
        template=PLOTLY_TEMPLATE, hovermode="x unified", height=CHART_HEIGHT,
        xaxis=dict(tickangle=-30),
        legend=dict(orientation="h", y=1.08, font=dict(size=9)),
        showlegend=True,
    )
    return save_chart(fig, f"04_distribution_{suffix}")


def chart_wip_aging(wip_data):
    fig = make_subplots(rows=1, cols=2, column_widths=[0.45, 0.55],
                        subplot_titles=(f"WIP Actual ({wip_data['total_wip']} issues)",
                                        "Distribucion de Edad (Aging)"))

    types = sorted(wip_data["type_wip"].keys(), key=lambda k: wip_data["type_wip"][k], reverse=True)
    values = [wip_data["type_wip"][t] for t in types]

    fig.add_trace(go.Bar(
        y=types, x=values, orientation="h",
        marker_color=COLORS[:len(types)],
        hovertemplate="%{y}: %{x}<extra>WIP</extra>"
    ), row=1, col=1)

    ages = wip_data["ages"]
    if ages:
        fig.add_trace(go.Histogram(
            x=ages, nbinsx=15,
            marker_color=COLORS[0], opacity=0.75,
            hovertemplate="Edad: %{x:.0f} dias<br>Cantidad: %{y}<extra></extra>",
            name="Issues"
        ), row=1, col=2)
        mean_age = np.mean(ages)
        fig.add_vline(x=mean_age, line_dash="dash", line_color=COLORS[3],
                      line_width=2, row=1, col=2,
                      annotation_text=f"Promedio: {mean_age:.0f}d",
                      annotation_position="top right")
        fig.update_xaxes(title_text="Dias desde creacion", row=1, col=2)
        fig.update_yaxes(title_text="Cantidad de issues", row=1, col=2)
        if ages:
            fig.update_xaxes(range=[0, max(ages) * 1.1], row=1, col=2)

    fig.update_xaxes(title_text="Issues activas", row=1, col=1)
    fig.update_layout(
        title=dict(text="<b>WIP y Aging</b>", x=0.5),
        template=PLOTLY_TEMPLATE, height=CHART_HEIGHT,
        hovermode="x unified",
    )
    return save_chart(fig, "05_wip_aging")


# ─── HTML Report Generator ───────────────────────────────────────────────────

def generate_interactive_report(metrics, wip_data, chart_html_files):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    last_sprint = metrics[-1]["sprint"] if metrics else "N/A"
    completed_total = sum(m["completed"] for m in metrics)
    velocity_total = sum(m["velocity"] or 0 for m in metrics)

    lt_avgs = [m["lead_time_avg"] for m in metrics if m["lead_time_avg"]]
    ct_avgs = [m["cycle_time_avg"] for m in metrics if m["cycle_time_avg"]]
    lt_avg = round(np.mean(lt_avgs), 1) if lt_avgs else "N/A"
    ct_avg = round(np.mean(ct_avgs), 1) if ct_avgs else "N/A"
    lt_trend = "↗️" if len(lt_avgs) > 2 and lt_avgs[-1] > lt_avgs[0] else "↘️" if len(lt_avgs) > 2 else "➡️"
    ct_trend = "↗️" if len(ct_avgs) > 2 and ct_avgs[-1] > ct_avgs[0] else "↘️" if len(ct_avgs) > 2 else "➡️"

    rows = ""
    for m in metrics:
        lt = f"{m['lead_time_avg']}d" if m['lead_time_avg'] else "-"
        ct = f"{m['cycle_time_avg']}d" if m['cycle_time_avg'] else "-"
        rows += f"""<tr>
            <td>{m['sprint']}</td>
            <td>{m['total_issues']}</td>
            <td><strong>{m['completed']}</strong></td>
            <td>{m['velocity'] or '-'}</td>
            <td>{lt}</td>
            <td>{ct}</td>
        </tr>"""

    chart_embeds = []
    for html_file in chart_html_files:
        rel = os.path.basename(html_file)
        chart_embeds.append(f'<iframe src="{rel}" frameborder="0" scrolling="no" style="width:100%;height:640px;border:1px solid #e0e0e0;border-radius:10px;background:white;"></iframe>')

    # Layout: 1 chart per row
    chart_grid = ""
    for embed in chart_embeds:
        chart_grid += f'<div class="chart-row"><div class="chart-cell">{embed}</div></div>'

    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="utf-8"/>
<title>OLP – Informe de Tendencias (Interactivo)</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f0f2f5; margin: 0; padding: 20px; color: #172b4d; }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .header {{ background: linear-gradient(135deg, #1a73e8, #0d47a1);
             color: white; padding: 30px 40px; border-radius: 12px; margin-bottom: 24px; }}
  .header h1 {{ margin: 0; font-size: 28px; }}
  .header p {{ margin: 8px 0 0; opacity: 0.9; }}
  .header .hint {{ margin-top: 12px; font-size: 13px; opacity: 0.8; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
               gap: 16px; margin-bottom: 24px; }}
  .kpi {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.12);
          text-align: center; transition: transform .1s; }}
  .kpi:hover {{ transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,.15); }}
  .kpi .value {{ font-size: 32px; font-weight: 700; color: #1a73e8; }}
  .kpi .label {{ font-size: 13px; color: #5e6c84; margin-top: 4px; }}
  .kpi .trend {{ font-size: 18px; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px;
           overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.12); margin-bottom: 24px; }}
  th {{ background: #1a73e8; color: white; padding: 12px 16px; text-align: left; font-weight: 600; }}
  td {{ padding: 10px 16px; border-bottom: 1px solid #eee; }}
  tr:last-child td {{ border-bottom: none; }}
  tr:hover td {{ background: #f5f8ff; }}
  .section-title {{ font-size: 20px; font-weight: 600; margin: 32px 0 16px;
                     color: #172b4d; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
  .chart-row {{ display: flex; gap: 16px; margin-bottom: 16px; }}
  .chart-cell {{ flex: 1; min-width: 0; }}
  @media (max-width: 900px) {{ .chart-row {{ flex-direction: column; }} }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 OLP – Informe de Tendencias</h1>
    <p>Ultimos 6 meses · Generado: {now}</p>
    <div class="hint">🖱 Pasa el mouse sobre los graficos para ver los valores detallados</div>
  </div>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="value">{last_sprint}</div>
      <div class="label">Ultimo Sprint</div>
    </div>
    <div class="kpi">
      <div class="value">{completed_total}</div>
      <div class="label">Issues completadas (6M)</div>
    </div>
    <div class="kpi">
      <div class="value">{velocity_total}</div>
      <div class="label">Story Points (6M)</div>
    </div>
    <div class="kpi">
      <div class="value">{lt_avg}</div>
      <div class="label">Lead Time prom. (dias)</div>
      <div class="trend">{lt_trend}</div>
    </div>
    <div class="kpi">
      <div class="value">{ct_avg}</div>
      <div class="label">Cycle Time prom. (dias)</div>
      <div class="trend">{ct_trend}</div>
    </div>
    <div class="kpi">
      <div class="value">{wip_data['total_wip']}</div>
      <div class="label">WIP actual</div>
    </div>
  </div>

  <h2 class="section-title">📈 Desglose por Sprint</h2>
  <table>
    <tr>
      <th>Sprint</th>
      <th>Total Issues</th>
      <th>Completadas</th>
      <th>Story Points</th>
      <th>Lead Time (avg)</th>
      <th>Cycle Time (avg)</th>
    </tr>
    {rows}
  </table>

  <h2 class="section-title">📊 Visualizaciones Interactivas</h2>
  <p style="color:#5e6c84;margin-top:-8px;margin-bottom:16px;">
    Pasa el cursor sobre los graficos para ver valores, haz clic en la leyenda para ocultar/mostrar series.
  </p>
  {chart_grid}

  <p style="text-align:center;color:#5e6c84;margin-top:40px;font-size:12px;">
    Informe generado automaticamente · OLP – Proyecto Olimpo ·
    <a href="https://aurusjoyeria.atlassian.net/jira/dashboards/10572">Dashboard OLP – Tendencias 6M</a>
  </p>
</div>
</body>
</html>"""
    path = os.path.join(OUTPUT_DIR, "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Interactive report: {path}")
    return path


# ─── Confluence Publisher ────────────────────────────────────────────────────

def confluence_publish(chart_paths, html_path, metrics, wip_data, page_id=None):
    """Create or update a Confluence page with the report."""
    auth = (ATLASSIAN_EMAIL, ATLASSIAN_TOKEN)
    base = f"{ATLASSIAN_SITE}/wiki/rest/api"

    now = datetime.now().strftime("%d %B %Y").replace("May", "mayo").replace("June", "junio")
    last_sprint = metrics[-1]["sprint"] if metrics else "N/A"
    completed_total = sum(m["completed"] for m in metrics)
    velocity_total = sum(m["velocity"] or 0 for m in metrics)
    lt_avgs = [m["lead_time_avg"] for m in metrics if m["lead_time_avg"]]
    ct_avgs = [m["cycle_time_avg"] for m in metrics if m["cycle_time_avg"]]
    lt_avg = round(np.mean(lt_avgs), 1) if lt_avgs else "N/A"
    ct_avg = round(np.mean(ct_avgs), 1) if ct_avgs else "N/A"

    # Build table rows for Confluence
    table_rows = ""
    for m in metrics:
        lt = f"{m['lead_time_avg']}" if m['lead_time_avg'] else "-"
        ct = f"{m['cycle_time_avg']}" if m['cycle_time_avg'] else "-"
        table_rows += f"""<tr>
            <td><strong>{m['sprint']}</strong></td>
            <td>{m['total_issues']}</td>
            <td>{m['completed']}</td>
            <td>{m['velocity'] or '-'}</td>
            <td>{lt}</td>
            <td>{ct}</td>
        </tr>"""

    lt_trend = "▲" if len(lt_avgs) > 2 and lt_avgs[-1] > lt_avgs[0] else "▼" if len(lt_avgs) > 2 else "–"
    ct_trend = "▲" if len(ct_avgs) > 2 and ct_avgs[-1] > ct_avgs[0] else "▼" if len(ct_avgs) > 2 else "–"

    def make_body(img_tags=""):
        return f"""<h1>📊 OLP – Informe de Tendencias</h1>
<p><em>Ultimos 6 meses · Actualizado: {now} · Datos procesados desde Jira API</em></p>

<ac:structured-macro ac:name="info">
  <ac:parameter ac:name="title">Resumen Ejecutivo</ac:parameter>
  <ac:rich-text-body>
    <p>Este reporte presenta las metricas clave del proyecto <strong>OLP (Olimpo)</strong> durante los ultimos 6 meses,
    abarcando {len(metrics)} sprints y un total de <strong>{completed_total} issues completadas</strong>
    ({velocity_total} story points).</p>
    <table>
      <tr>
        <td><strong>📈 Ultimo Sprint:</strong> {last_sprint}</td>
        <td><strong>⏱ Lead Time prom:</strong> {lt_avg} dias {lt_trend}</td>
      </tr>
      <tr>
        <td><strong>📊 Throughput total:</strong> {completed_total} issues</td>
        <td><strong>🔄 Cycle Time prom:</strong> {ct_avg} dias {ct_trend}</td>
      </tr>
    </table>
  </ac:rich-text-body>
</ac:structured-macro>

<h2>📈 Desglose por Sprint</h2>
<table>
  <tr>
    <th>Sprint</th>
    <th>Issues totales</th>
    <th>Completadas</th>
    <th>Story Points</th>
    <th>Lead Time (avg)</th>
    <th>Cycle Time (avg)</th>
  </tr>
  {table_rows}
</table>

<h2>📊 Visualizaciones</h2>
<table>
  {img_tags}
</table>

<hr/>
<p style="text-align:center;color:#5e6c84;font-size:12px;">
  Informe generado automaticamente · <a href="https://aurusjoyeria.atlassian.net/jira/dashboards/10572">Dashboard OLP – Tendencias 6M</a>
</p>"""

    # Step 1: Create or get page
    if page_id:
        print(f"  Actualizando pagina existente (ID: {page_id})...")
        confluence_update_page(page_id, make_body(), auth, base)
    else:
        print("  Creando pagina nueva en Confluence...")
        page_id = confluence_create_page(make_body(), auth, base)
        if not page_id:
            return None

    # Step 2: Upload attachments
    for path in sorted(chart_paths):
        filename = os.path.basename(path)
        with open(path, "rb") as f:
            data = f.read()
        attach_url = f"{base}/content/{page_id}/child/attachment"
        r = requests.post(attach_url, auth=auth,
                        files={"file": (filename, data, "image/png")},
                        headers={"X-Atlassian-Token": "nocheck"})
        if r.status_code in (200, 201):
            print(f"    Uploaded {filename}")
        else:
            # May already exist, try update
            existing_id = get_attachment_id(page_id, filename, auth, base)
            if existing_id:
                upd_url = f"{base}/content/{page_id}/child/attachment/{existing_id}/data"
                r2 = requests.post(upd_url, auth=auth,
                                   files={"file": (filename, data, "image/png")},
                                   headers={"X-Atlassian-Token": "nocheck"})
                if r2.status_code in (200, 201):
                    print(f"    Updated {filename}")
                else:
                    print(f"    Failed to upload {filename}: {r2.status_code}")
            else:
                print(f"    Failed to upload {filename}: {r.status_code} {r.text[:200]}")

    # Step 3: Build image layout and update page (1 chart per row, full width)
    img_tags = ""
    for path in sorted(chart_paths):
        filename = os.path.basename(path)
        img_tags += f"""<tr>
    <td><ac:image ac:width="1400px"><ri:attachment ri:filename="{filename}"/></ac:image></td>
</tr>"""

    confluence_update_page(page_id, make_body(img_tags), auth, base)
    page_url = f"{ATLASSIAN_SITE}/wiki/spaces/{CONFLUENCE_SPACE_KEY}/pages/{page_id}"
    print(f"\n  ✅ Reporte publicado: {page_url}")
    return page_id


def get_attachment_id(page_id, filename, auth, base):
    r = requests.get(f"{base}/content/{page_id}/child/attachment",
                     auth=auth, headers={"Accept": "application/json"},
                     params={"filename": filename})
    if r.status_code == 200:
        data = r.json()
        results = data.get("results", [])
        if results:
            return results[0]["id"]
    return None


def confluence_create_page(body, auth, base):
    payload = {
        "type": "page",
        "title": "📊 OLP – Informe de Tendencias (6 Meses)",
        "space": {"key": CONFLUENCE_SPACE_KEY},
        "ancestors": [{"id": CONFLUENCE_PARENT_ID}],
        "body": {
            "storage": {
                "value": body,
                "representation": "storage"
            }
        }
    }
    r = requests.post(f"{base}/content", auth=auth,
                      headers={"Accept": "application/json", "Content-Type": "application/json"},
                      json=payload)
    if r.status_code == 200:
        result = r.json()
        page_id = result["id"]
        page_url = f"{ATLASSIAN_SITE}/wiki{result['_links']['webui']}"
        print(f"\n  ✅ Pagina creada en Confluence:")
        print(f"     ID: {page_id}")
        print(f"     URL: {page_url}")
        return page_id
    else:
        print(f"  ❌ Error creando pagina: {r.status_code} {r.text[:300]}")
        return None


def confluence_update_page(page_id, body, auth, base):
    # Get current version
    r = requests.get(f"{base}/content/{page_id}",
                     auth=auth, headers={"Accept": "application/json"},
                     params={"expand": "version"})
    if r.status_code != 200:
        print(f"  ❌ Error obteniendo pagina: {r.status_code}")
        return page_id
    data = r.json()
    version = data["version"]["number"]

    payload = {
        "id": page_id,
        "type": "page",
        "title": "📊 OLP – Informe de Tendencias (6 Meses)",
        "space": {"key": CONFLUENCE_SPACE_KEY},
        "version": {"number": version + 1},
        "body": {
            "storage": {
                "value": body,
                "representation": "storage"
            }
        }
    }
    r = requests.put(f"{base}/content/{page_id}", auth=auth,
                     headers={"Accept": "application/json", "Content-Type": "application/json"},
                     json=payload)
    if r.status_code == 200:
        result = r.json()
        page_url = f"{ATLASSIAN_SITE}/wiki{result['_links']['webui']}"
        print(f"\n  ✅ Pagina actualizada: {page_url}")
    else:
        print(f"  ❌ Error actualizando pagina: {r.status_code} {r.text[:300]}")
    return page_id


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OLP Trends Report")
    parser.add_argument("--publish", action="store_true", help="Publicar en Confluence")
    parser.add_argument("--page-id", type=str, help="ID de pagina de Confluence a actualizar")
    args = parser.parse_args()

    print("=" * 60)
    print("  OLP – Informe de Tendencias (6 Meses)")
    print("=" * 60)

    jira = JiraClient()

    # Step 1: Fetch data
    print("\n📡 Obteniendo sprints...")
    sprints = jira.get_sprints()
    print(f"  Sprints encontrados: {len(sprints)}")
    for s in sprints:
        print(f"    {s['id']}: {s['name']} ({s['state']})")

    print("\n📡 Obteniendo issues de cada sprint...")
    metrics, all_issues = compute_metrics(jira, sprints)

    print("\n📡 Obteniendo issues activas (WIP)...")
    active_issues = jira.get_active_issues()
    wip_data = compute_wip_history(active_issues, metrics)
    print(f"  WIP actual: {wip_data['total_wip']} issues")

    # Step 2: Generate charts
    print("\n🎨 Generando charts interactivos...")
    chart_results = []
    chart_results.append(chart_velocity_throughput(metrics))
    chart_results.append(chart_lead_cycle_time(metrics))
    chart_results.append(chart_assignee_load(metrics))
    chart_results.append(chart_distribution(metrics, "issuetype"))
    chart_results.append(chart_distribution(metrics, "priority"))
    chart_results.append(chart_wip_aging(wip_data))

    html_charts = [r[0] for r in chart_results]
    png_charts = [r[1] for r in chart_results]

    # Step 3: Generate interactive HTML report
    print("\n📄 Generando reporte HTML interactivo...")
    html_path = generate_interactive_report(metrics, wip_data, html_charts)
    print(f"   Abre {html_path} en tu navegador para ver graficos interactivos")

    print(f"\n📁 Reporte generado en: {OUTPUT_DIR}/")

    # Step 4: Publish to Confluence
    if args.publish:
        print("\n📤 Publicando en Confluence...")
        new_page_id = confluence_publish(png_charts, html_path, metrics, wip_data, args.page_id)
        if new_page_id:
            print(f"\n  ✅ Publicado exitosamente. page-id: {new_page_id}")
    else:
        print("\n  (Usa --publish para publicar en Confluence)")

    print("\n" + "=" * 60)
    print("  Reporte completo.")
    print("=" * 60)


if __name__ == "__main__":
    main()
