import sys
from api.services.jira_service import JiraClient
from collections import defaultdict

client = JiraClient()

# Ver todos los estados disponibles con sus IDs y categorías
statuses = client._get(client.base + "/status")
sys.stdout.write("Todos los estados:\n")
for s in statuses:
    cat = s.get("statusCategory", {}).get("name", "?")
    sys.stdout.write(f"  id={s['id']} | {s['name']} | cat={cat}\n")

# Ver changelogs de DCV para entender transiciones reales
sys.stdout.write("\nTransiciones de estado en DCV (últimas 5 issues resueltas):\n")
data = client._get(client.base + "/search/jql", params={
    "jql": "project = DCV AND statusCategory = Done ORDER BY updated DESC",
    "fields": "summary,status",
    "expand": "changelog",
    "maxResults": 3,
})
for issue in data.get("issues", []):
    sys.stdout.write(f"\n  {issue['key']}:\n")
    for entry in issue.get("changelog", {}).get("histories", []):
        for item in entry.get("items", []):
            if item.get("field") == "status":
                sys.stdout.write(f"    {item.get('fromString')} -> {item.get('toString')} (toId={item.get('to')})\n")

sys.stdout.flush()
