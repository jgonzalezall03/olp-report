from fastapi import status

from api import routes


class DummyTask:
    def __init__(self, task_id: str):
        self.id = task_id


def test_get_projects_returns_empty_list(client):
    response = client.get("/api/projects/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_sync_all_endpoint_queues_task(client, monkeypatch):
    monkeypatch.setattr(routes.fetch_all_projects_metrics, "delay", lambda: DummyTask("dummy-task-id"))

    response = client.post("/api/sync/")
    assert response.status_code == status.HTTP_200_OK
    json_data = response.json()
    assert json_data["status"] == "queued"
    assert "dummy-task-id" in json_data["detail"]
