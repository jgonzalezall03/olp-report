from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship

from .db import Base


class JiraProject(Base):
    __tablename__ = "jira_projects"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(32), unique=True, nullable=False)
    name = Column(String(128), nullable=False)
    board_id = Column(Integer, nullable=True)
    story_points_field = Column(String(64), default="customfield_10016")
    sprint_field = Column(String(64), default="customfield_10020")
    active = Column(Boolean, default=True)
    is_kanban = Column(Boolean, default=False)

    sprints = relationship("JiraSprint", back_populates="project")
    metrics = relationship("MetricsSnapshot", back_populates="project")


class JiraSprint(Base):
    __tablename__ = "jira_sprints"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("jira_projects.id", ondelete="CASCADE"), nullable=False)
    jira_id = Column(Integer, nullable=False)
    name = Column(String(128), nullable=True)
    state = Column(String(32), nullable=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)

    project = relationship("JiraProject", back_populates="sprints")
    metrics = relationship("MetricsSnapshot", back_populates="sprint")


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("jira_projects.id", ondelete="CASCADE"), nullable=False)
    sprint_id = Column(Integer, ForeignKey("jira_sprints.id", ondelete="SET NULL"), nullable=True)
    sprint_name = Column(String(128), nullable=False)
    sprint_start_date = Column(DateTime, nullable=True)
    completed = Column(Integer, default=0)
    velocity = Column(Float, default=0)
    lead_time_avg = Column(Float, nullable=True)
    lead_time_med = Column(Float, nullable=True)
    cycle_time_avg = Column(Float, nullable=True)
    cycle_time_med = Column(Float, nullable=True)
    bugs_count = Column(Integer, default=0)
    total_issues = Column(Integer, default=0)

    project = relationship("JiraProject", back_populates="metrics")
    sprint = relationship("JiraSprint", back_populates="metrics")
