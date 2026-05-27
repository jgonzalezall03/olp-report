import os
from datetime import datetime, timedelta, timezone
from collections import defaultdict

import requests


def parse_date(date_string):
    if not date_string:
        return None
    return datetime.fromisoformat(date_string.replace("Z", "+00:00"))


class JiraClient:
    def __init__(self, site=None, email=None, token=None):
        self.site = site or os.getenv("ATLASSIAN_SITE")
        self.email = email or os.getenv("ATLASSIAN_EMAIL")
        self.token = token or self._load_token()
        if not self.site or not self.email or not self.token:
            raise ValueError("ATLASSIAN_SITE, ATLASSIAN_EMAIL and ATLASSIAN_TOKEN or token file are required")

        self.session = requests.Session()
        self.session.auth = (self.email, self.token)
        self.session.headers.update({"Accept": "application/json"})
        self.base = f"{self.site}/rest/api/3"
        self.agile_base = f"{self.site}/rest/agile/1.0"
        self.status_map = None

    def _load_token(self):
        token_file = os.getenv("ATLASSIAN_TOKEN_FILE", "~/.config/opencode/atlassian-token.txt")
        token_path = os.path.expanduser(token_file)
        if os.path.exists(token_path):
            with open(token_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        return os.getenv("ATLASSIAN_TOKEN")

    def _get(self, url, params=None):
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def _get_all(self, url, params=None, key="values"):
        params = params.copy() if params else {}
        results = []
        while True:
            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get(key, []))
            if data.get("isLast") is False and data.get("startAt") is not None:
                params["startAt"] = data.get("startAt", 0) + len(data.get(key, []))
                continue
            if data.get("nextPageToken") and data.get("isLast") is False:
                params["nextPageToken"] = data["nextPageToken"]
                continue
            break
        return results

    def get_status_map(self):
        if self.status_map is not None:
            return self.status_map
        self.status_map = {}
        resp = self._get(f"{self.base}/status")
        for status in resp:
            self.status_map[status["name"]] = status["id"]
        return self.status_map

    def get_project_sprints(self, board_id, months_back=6):
        url = f"{self.agile_base}/board/{board_id}/sprint"
        params = {"state": "closed,active", "maxResults": 200}
        try:
            all_sprints = self._get_all(url, params)
        except Exception:
            return []  # Kanban boards o boards sin sprints
        cutoff = datetime.now(timezone.utc) - timedelta(days=months_back * 30 + 15)
        recent_sprints = [s for s in all_sprints if parse_date(s.get("startDate")) and parse_date(s.get("startDate")) > cutoff]
        return recent_sprints[-12:]

    def search_issues(self, jql, fields, max_results=200):
        params = {"jql": jql, "fields": ",".join(fields), "maxResults": max_results}
        return self._get_all(f"{self.base}/search/jql", params, key="issues")

    def get_sprint_issues(self, project_key, sprint_id, story_points_field, sprint_field):
        jql = f"project = {project_key} AND Sprint = {sprint_id}"
        fields = [
            "summary",
            "status",
            "assignee",
            "issuetype",
            "priority",
            "created",
            "resolutiondate",
            story_points_field,
            sprint_field,
        ]
        return self.search_issues(jql, fields)

    def get_completed_with_changelogs(self, project_key, sprint_id):
        jql = f"project = {project_key} AND Sprint = {sprint_id} AND status IN (DONE, Terminado, Finalizada, Closed)"
        params = {
            "jql": jql,
            "fields": "key,resolutiondate,status",
            "expand": "changelog",
            "maxResults": 200,
        }
        return {issue["key"]: issue.get("changelog", {}).get("histories", []) for issue in self._get_all(f"{self.base}/search/jql", params, key="issues")}

    def get_active_issues(self, project_key, story_points_field, sprint_field):
        jql = f"project = {project_key} AND status NOT IN (DONE, Finalizada, Closed)"
        fields = [
            "summary",
            "status",
            "assignee",
            "issuetype",
            "priority",
            "created",
            "updated",
            story_points_field,
            sprint_field,
        ]
        return self.search_issues(jql, fields)

    def get_first_in_progress(self, histories):
        """Retorna la fecha de la primera transición a un estado de categoría 'En curso' / 'In Progress'."""
        IN_PROGRESS_CATS = {"In Progress", "En curso"}
        first = None
        for entry in histories:
            for item in entry.get("items", []):
                if item.get("field") == "status":
                    # El changelog incluye toStatusCategory en algunos casos,
                    # pero no siempre. Usamos el status_map para obtener la categoría.
                    to_status = item.get("toString", "")
                    status_map = self.get_status_map()
                    to_id = status_map.get(to_status)
                    if to_id and to_id in self._in_progress_ids:
                        candidate = parse_date(entry.get("created"))
                        if candidate and (first is None or candidate < first):
                            first = candidate
        return first

    @property
    def _in_progress_ids(self):
        """IDs de estados cuya categoría es In Progress / En curso."""
        if hasattr(self, '_cached_ip_ids'):
            return self._cached_ip_ids
        resp = self._get(f"{self.base}/status")
        self._cached_ip_ids = {
            s["id"] for s in resp
            if s.get("statusCategory", {}).get("name") in {"In Progress", "En curso"}
        }
        return self._cached_ip_ids

    def compute_kanban_metrics(self, project_key, story_points_field, months_back=12):
        """Agrupa issues resueltas por mes para proyectos Kanban (sin sprints)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=months_back * 30 + 15)
        cutoff_str = cutoff.strftime("%Y-%m-%d")

        # Traer todas las issues con changelog para calcular cycle time
        DONE_STATUSES = {"Done", "Terminado", "Finalizada", "Closed", "Cerrado", "Resuelto", "Resolved"}
        params = {
            "jql": f"project = {project_key} AND status in ({','.join(repr(s) for s in DONE_STATUSES)}) AND updated >= '{cutoff_str}' ORDER BY updated ASC",
            "fields": f"created,resolutiondate,status,updated,assignee,issuetype,{story_points_field}",
            "expand": "changelog",
            "maxResults": 200,
        }
        issues = self._get_all(f"{self.base}/search/jql", params, key="issues")

        by_month = defaultdict(lambda: {"completed": 0, "velocity": 0, "lead_times": [], "cycle_times": [], "total": 0})
        by_assignee_month = defaultdict(lambda: defaultdict(lambda: {"completed": 0, "lead_times": [], "cycle_times": [], "bugs": 0}))

        for issue in issues:
            fields = issue.get("fields", {})
            created = parse_date(fields.get("created"))
            resolutiondate = parse_date(fields.get("resolutiondate"))
            story_points = fields.get(story_points_field) or 0
            assignee = fields.get("assignee")
            assignee_name = assignee.get("displayName") if assignee else "Sin asignar"
            is_bug = fields.get("issuetype", {}).get("name", "") in {"Error", "Bug", "Defect", "Defecto"}

            closed_date = resolutiondate
            if not closed_date:
                for entry in reversed(issue.get("changelog", {}).get("histories", [])):
                    for item in entry.get("items", []):
                        if item.get("field") == "status" and item.get("toString", "") in DONE_STATUSES:
                            closed_date = parse_date(entry.get("created"))
                            break
                    if closed_date:
                        break
            if not closed_date:
                closed_date = parse_date(fields.get("updated"))

            if not closed_date or closed_date < cutoff:
                continue

            month_key = closed_date.strftime("%Y-%m")
            bucket = by_month[month_key]
            bucket["total"] += 1
            bucket["completed"] += 1
            bucket["velocity"] += story_points

            lead = None
            if created and closed_date:
                lead = (closed_date - created).total_seconds() / 86400
                if lead >= 0:
                    bucket["lead_times"].append(lead)
                first_ip = self.get_first_in_progress(issue.get("changelog", {}).get("histories", []))
                if first_ip and first_ip < closed_date:
                    ct = (closed_date - first_ip).total_seconds() / 86400
                    bucket["cycle_times"].append(ct)
                    by_assignee_month[assignee_name][month_key]["cycle_times"].append(ct)

            ab = by_assignee_month[assignee_name][month_key]
            ab["completed"] += 1
            if lead is not None and lead >= 0:
                ab["lead_times"].append(lead)
            if is_bug:
                ab["bugs"] += 1

        metrics = []
        for month_key in sorted(by_month.keys()):
            b = by_month[month_key]
            lead_times = b["lead_times"]
            cycle_times = b["cycle_times"]
            metrics.append({
                "sprint": month_key,
                "sprint_id": None,
                "start": f"{month_key}-01T00:00:00+00:00",
                "end": None,
                "completed": b["completed"],
                "velocity": b["velocity"],
                "lead_time_avg": round(sum(lead_times) / len(lead_times), 1) if lead_times else None,
                "lead_time_med": round(sorted(lead_times)[len(lead_times) // 2], 1) if lead_times else None,
                "cycle_time_avg": round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else None,
                "cycle_time_med": round(sorted(cycle_times)[len(cycle_times) // 2], 1) if cycle_times else None,
                "total_issues": b["total"],
            })

        assignee_metrics = [
            {
                "assignee": name,
                "period": month_key,
                "start": f"{month_key}-01T00:00:00+00:00",
                "completed": ab["completed"],
                "lead_time_avg": round(sum(ab["lead_times"]) / len(ab["lead_times"]), 1) if ab["lead_times"] else None,
                "cycle_time_avg": round(sum(ab["cycle_times"]) / len(ab["cycle_times"]), 1) if ab["cycle_times"] else None,
                "bugs_count": ab["bugs"],
            }
            for name, months in by_assignee_month.items()
            for month_key, ab in months.items()
        ]
        return metrics, {"total_wip": 0, "issues": []}, assignee_metrics

    def compute_metrics(self, project_key, board_id, story_points_field, sprint_field, months_back=6):
        sprints = self.get_project_sprints(board_id, months_back)
        metrics = []
        active_issues = []

        by_assignee_sprint = defaultdict(lambda: defaultdict(lambda: {"completed": 0, "lead_times": [], "cycle_times": [], "bugs": 0}))

        for sprint in sprints:
            sprint_id = sprint["id"]
            sprint_name = sprint.get("name")
            sprint_start = sprint.get("startDate")
            issues = self.get_sprint_issues(project_key, sprint_id, story_points_field, sprint_field)
            changelogs = self.get_completed_with_changelogs(project_key, sprint_id)

            completed_issues = []
            completed_points = 0
            lead_times = []
            cycle_times = []

            for issue in issues:
                fields = issue.get("fields", {})
                key = issue.get("key")
                created = parse_date(fields.get("created"))
                resolutiondate = parse_date(fields.get("resolutiondate"))
                status_name = fields.get("status", {}).get("name", "")
                story_points = fields.get(story_points_field) or 0
                assignee = fields.get("assignee")
                assignee_name = assignee.get("displayName") if assignee else "Sin asignar"
                issuetype = fields.get("issuetype", {}).get("name", "Unknown")
                is_done = resolutiondate is not None or status_name in {"Done", "Terminado", "Finalizada", "Closed"}
                is_bug = issuetype in {"Error", "Bug", "Defect", "Defecto"}

                if is_done:
                    completed_issues.append(key)
                    completed_points += story_points
                    ab = by_assignee_sprint[assignee_name][sprint_name]
                    ab["completed"] += 1
                    ab["start"] = sprint_start
                    if is_bug:
                        ab["bugs"] += 1
                    if created and resolutiondate:
                        lead = (resolutiondate - created).total_seconds() / 86400
                        lead_times.append(lead)
                        ab["lead_times"].append(lead)
                        first_ip = self.get_first_in_progress(changelogs.get(key, []))
                        if first_ip and first_ip < resolutiondate:
                            ct = (resolutiondate - first_ip).total_seconds() / 86400
                            cycle_times.append(ct)
                            ab["cycle_times"].append(ct)

            metrics.append({
                "sprint": sprint_name,
                "sprint_id": sprint_id,
                "start": sprint_start,
                "end": sprint.get("endDate"),
                "completed": len(completed_issues),
                "velocity": completed_points,
                "lead_time_avg": round(sum(lead_times) / len(lead_times), 1) if lead_times else None,
                "lead_time_med": round(sorted(lead_times)[len(lead_times) // 2], 1) if lead_times else None,
                "cycle_time_avg": round(sum(cycle_times) / len(cycle_times), 1) if cycle_times else None,
                "cycle_time_med": round(sorted(cycle_times)[len(cycle_times) // 2], 1) if cycle_times else None,
                "total_issues": len(issues),
                "bugs": sum(1 for i in issues if i.get('fields',{}).get('issuetype',{}).get('name','') in {'Error','Bug','Defect','Defecto'}),
            })

        active_issues = self.get_active_issues(project_key, story_points_field, sprint_field)
        wip_data = {"total_wip": len(active_issues), "issues": active_issues}

        assignee_metrics = [
            {
                "assignee": name,
                "period": sprint_name,
                "start": ab.get("start"),
                "completed": ab["completed"],
                "lead_time_avg": round(sum(ab["lead_times"]) / len(ab["lead_times"]), 1) if ab["lead_times"] else None,
                "cycle_time_avg": round(sum(ab["cycle_times"]) / len(ab["cycle_times"]), 1) if ab["cycle_times"] else None,
                "bugs_count": ab["bugs"],
            }
            for name, sprints_map in by_assignee_sprint.items()
            for sprint_name, ab in sprints_map.items()
        ]
        return metrics, wip_data, assignee_metrics
