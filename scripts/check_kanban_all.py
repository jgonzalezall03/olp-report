import sys
from api.services.jira_service import JiraClient

client = JiraClient()

KANBAN_PROJECTS = ["ADP", "AN", "DCX", "DT2", "DTECH", "DTI", "EN", "EXP", "N2025", "NT", "NXDAY", "OII", "OLI", "OP", "PC", "PCCD", "PI", "RC", "SAI", "SDMES", "SPG", "UA"]

for key in KANBAN_PROJECTS:
    try:
        data = client._get(client.base + "/search/jql", params={
            "jql": f"project = {key} AND resolutiondate >= -180d",
            "fields": "resolutiondate",
            "maxResults": 1,
        })
        total = data.get("total", 0) or 0
        sys.stdout.write(f"{key}: {total} issues resueltas\n")
        sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"{key}: ERROR {e}\n")
        sys.stdout.flush()
