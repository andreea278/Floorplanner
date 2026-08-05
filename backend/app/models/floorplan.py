from __future__ import annotations
from pydantic import BaseModel, Field


class Point2D(BaseModel):
    x: float
    y: float


class Wall(BaseModel):
    id: str
    start: Point2D
    end: Point2D
    height: float
    thickness: float


class FloorPlan(BaseModel):
    id: str
    name: str
    unit: str = "meters"
    walls: list[Wall]


class DetectionOptions(BaseModel):
    scale_px_per_unit: float = Field(default=100.0, gt=0)
    default_wall_height: float = Field(default=2.7, gt=0)
    default_wall_thickness: float = Field(default=0.2, gt=0)
    page_number: int = Field(default=0, gt=0)
