import sys
from api.services.jira_service import JiraClient
from collections import Counter

client = JiraClient()

# UA tiene 7 meses de datos - explorar WIP y aging
# 1. Issues activas (WIP actual)
data = client._get(client.base + "/search/jql", params={
    "jql": "project = UA AND statusCategory != Done ORDER BY created ASC",
    "fields": "summary,status,assignee,created,updated,issuetype",
    "maxResults": 50,
})
issues = data.get("issues", [])
sys.stdout.write(f"UA - WIP actual: {len(issues)} issues\n")
statuses = Counter(i["fields"]["status"]["name"] for i in issues)
for s, c in statuses.most_common():
    sys.stdout.write(f"  {s}: {c}\n")

# 2. Ver columnas del board Kanban UA (para aging por columna)
try:
    board = client._get(client.agile_base + "/board/283/configuration")
    cols = board.get("columnConfig", {}).get("columns", [])
    sys.stdout.write(f"\nUA - Columnas del board:\n")
    for col in cols:
        sys.stdout.write(f"  {col['name']}: {[s.get('id') for s in col.get('statuses', [])]}\n")
except Exception as e:
    sys.stdout.write(f"Board config error: {e}\n")

# 3. Throughput semanal UA
data2 = client._get_all(client.base + "/search/jql", {
    "jql": "project = UA AND statusCategory = Done AND updated >= -90d ORDER BY updated ASC",
    "fields": "resolutiondate,updated,status",
    "maxResults": 200,
}, key="issues")
from collections import defaultdict
by_week = defaultdict(int)
for i in data2:
    rd = i["fields"].get("resolutiondate") or i["fields"].get("updated","")
    if rd:
        from datetime import datetime
        d = datetime.fromisoformat(rd.replace("Z","+00:00"))
        week = f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}"
        by_week[week] += 1
sys.stdout.write(f"\nUA - Throughput semanal (últimas 13 semanas):\n")
for w in sorted(by_week)[-13:]:
    sys.stdout.write(f"  {w}: {by_week[w]}\n")

sys.stdout.flush()
