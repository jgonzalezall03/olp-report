from api.services.jira_service import JiraClient
import json

client = JiraClient()

# Ver issues activas y resueltas de DCX
data = client._get(client.base + "/search/jql", params={
    "jql": "project = DCX ORDER BY created DESC",
    "fields": "summary,status,assignee,issuetype,priority,created,resolutiondate,customfield_10016",
    "maxResults": 5,
})
print("TOTAL ISSUES DCX:", data.get("total"))
for issue in data.get("issues", []):
    f = issue["fields"]
    print(issue["key"], "|", f["status"]["name"], "|", f.get("resolutiondate","—")[:10] if f.get("resolutiondate") else "—", "|", f.get("created","")[:10])
