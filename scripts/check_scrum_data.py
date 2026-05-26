import sys
from api.services.jira_service import JiraClient

client = JiraClient()

# 1. Ver tipos de issues en OLP (para detectar bugs)
data = client._get(client.base + "/search/jql", params={
    "jql": "project = OLP ORDER BY created DESC",
    "fields": "issuetype,priority,status,customfield_10016",
    "maxResults": 50,
})
from collections import Counter
issues = data.get("issues", [])
types = Counter(i["fields"]["issuetype"]["name"] for i in issues)
sys.stdout.write(f"\nOLP - Tipos de issue:\n")
for t, c in types.most_common():
    sys.stdout.write(f"  {t}: {c}\n")

# 2. Ver si hay Sprint Goal en los sprints
data2 = client._get(client.agile_base + "/board/2/sprint", params={"state": "closed", "maxResults": 3})
for s in data2.get("values", [])[:3]:
    sys.stdout.write(f"\nSprint: {s.get('name')}\n")
    sys.stdout.write(f"  goal: {s.get('goal', 'N/A')}\n")
    sys.stdout.write(f"  startDate: {s.get('startDate','')[:10]}\n")
    sys.stdout.write(f"  endDate: {s.get('endDate','')[:10]}\n")

# 3. Ver campos disponibles en una issue de OLP
data3 = client._get(client.base + "/search/jql", params={
    "jql": "project = OLP AND Sprint = 3226",
    "fields": "summary,status,issuetype,customfield_10016,customfield_10020,created,resolutiondate,priority",
    "maxResults": 3,
    "expand": "changelog",
})
for issue in data3.get("issues", [])[:2]:
    f = issue["fields"]
    sys.stdout.write(f"\n{issue['key']}: {f['issuetype']['name']} | {f['status']['name']} | pts={f.get('customfield_10016')}\n")

sys.stdout.flush()
