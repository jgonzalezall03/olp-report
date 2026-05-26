from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ProjectSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    board_id: Optional[int]
    story_points_field: str
    sprint_field: str
    active: bool


class MetricsSnapshotSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sprint_name: str
    sprint_start_date: Optional[datetime]
    completed: int
    velocity: float
    lead_time_avg: Optional[float]
    lead_time_med: Optional[float]
    cycle_time_avg: Optional[float]
    cycle_time_med: Optional[float]
    total_issues: int


class SyncResponse(BaseModel):
    status: str
    detail: str


class DashboardContext(BaseModel):
    projects: List[ProjectSchema]
    selected_project: Optional[ProjectSchema]
    metrics: List[MetricsSnapshotSchema]
