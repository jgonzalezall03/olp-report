import sys
from api.services.jira_service import JiraClient
from collections import Counter

client = JiraClient()

for key in ["DTECH", "UA", "NT", "RC"]:
    data = client._get(client.base + "/search/jql", params={
        "jql": f"project = {key} ORDER BY updated DESC",
        "fields": "status,resolutiondate",
        "maxResults": 50,
    })
    issues = data.get("issues", [])
    statuses = Counter(i["fields"]["status"]["name"] for i in issues)
    has_res = sum(1 for i in issues if i["fields"].get("resolutiondate"))
    sys.stdout.write(f"\n{key} ({data.get('total')} total, {has_res}/50 con resolutiondate):\n")
    for s, c in statuses.most_common():
        sys.stdout.write(f"  {s}: {c}\n")
    sys.stdout.flush()
