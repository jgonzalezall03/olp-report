from types import SimpleNamespace

from api import tasks


def test_sync_project_persists_assignee_metrics(monkeypatch):
    session = SimpleNamespace()
    project = SimpleNamespace(key="OLP")

    calls = {}

    def fake_fetch_metrics(project_obj):
        calls["project"] = project_obj
        return ([{"sprint": "S1"}], [{"assignee": "Ana", "period": "S1"}])

    def fake_save_metrics(project_obj, metrics, session_obj):
        calls["save_metrics"] = (project_obj, metrics, session_obj)

    def fake_save_assignee_metrics(project_obj, assignee_metrics, session_obj):
        calls["save_assignee_metrics"] = (project_obj, assignee_metrics, session_obj)

    session.query = lambda *args, **kwargs: SimpleNamespace(
        filter=lambda *a, **k: SimpleNamespace(first=lambda: project)
    )

    monkeypatch.setattr(tasks, "_fetch_metrics", fake_fetch_metrics)
    monkeypatch.setattr(tasks, "_save_metrics", fake_save_metrics)
    monkeypatch.setattr(tasks, "_save_assignee_metrics", fake_save_assignee_metrics)

    result = tasks._sync_project("OLP", session)

    assert result == "Synced 1 buckets for OLP"
    assert calls["project"] is project
    assert calls["save_metrics"][0] is project
    assert calls["save_assignee_metrics"][0] is project
    assert calls["save_assignee_metrics"][1] == [{"assignee": "Ana", "period": "S1"}]
