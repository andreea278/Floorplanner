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


class Door(BaseModel):
    id: str
    # Deliberately camelCase (not snake_case) to match the JSON wire format
    # already used everywhere in this file (start/end/height/thickness),
    # without needing Pydantic field aliases.
    wallId: str
    offset: float = Field(ge=0)
    width: float = Field(default=0.9, gt=0)
    height: float = Field(default=2.1, gt=0)


class Window(BaseModel):
    id: str
    wallId: str
    offset: float = Field(ge=0)
    width: float = Field(default=1.2, gt=0)
    height: float = Field(default=1.2, gt=0)
    sillHeight: float = Field(default=0.9, ge=0)


class FloorPlan(BaseModel):
    id: str
    name: str
    unit: str = "meters"
    walls: list[Wall]
    doors: list[Door] = []
    windows: list[Window] = []


class DetectionOptions(BaseModel):
    scale_px_per_unit: float = Field(default=100.0, gt=0)
    default_wall_height: float = Field(default=2.7, gt=0)
    default_wall_thickness: float = Field(default=0.2, gt=0)
    page_number: int = Field(default=0, ge=0)
    min_wall_thickness_px: int = Field(default=8, gt=0)