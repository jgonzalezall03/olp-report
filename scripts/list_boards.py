import json
from api.services.jira_service import JiraClient

client = JiraClient()
data = client._get(client.agile_base + "/board")
print("TOTAL:", data.get("total"), "IS_LAST:", data.get("isLast"))
for b in sorted(data.get("values", []), key=lambda x: x.get("location", {}).get("projectKey", "")):
    loc = b.get("location", {})
    print(f"{b['id']} | {b['name']} | {loc.get('projectKey', 'N/A')}")
