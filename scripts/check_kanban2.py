from api.services.jira_service import JiraClient

client = JiraClient()

# Issues resueltas con changelog para calcular lead/cycle time
data = client._get(client.base + "/search/jql", params={
    "jql": "project = DCX AND status IN (Done, Terminado, Finalizada, Closed) ORDER BY resolutiondate DESC",
    "fields": "summary,status,created,resolutiondate,customfield_10016,assignee",
    "maxResults": 5,
    "expand": "changelog",
})
issues = data.get("issues", [])
print("RESUELTAS:", len(issues))
for issue in issues:
    f = issue["fields"]
    print(issue["key"], "|", f.get("created","")[:10], "->", (f.get("resolutiondate") or "")[:10], "|", f["status"]["name"])

# Total por mes (issues resueltas)
from collections import defaultdict
data2 = client._get_all(client.base + "/search/jql", {
    "jql": "project = DCX AND resolutiondate >= -180d ORDER BY resolutiondate ASC",
    "fields": "created,resolutiondate,customfield_10016",
    "maxResults": 200,
}, key="issues")
print("\nTOTAL resueltas últimos 6 meses:", len(data2))
by_month = defaultdict(int)
for i in data2:
    rd = i["fields"].get("resolutiondate","")
    if rd:
        by_month[rd[:7]] += 1
for k in sorted(by_month):
    print(k, "->", by_month[k], "issues")
