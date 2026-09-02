from __future__ import annotations
from typing import Literal
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
    color: str | None = None


class Door(BaseModel):
    id: str
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


class Furniture(BaseModel):
    id: str
    kind: Literal["sofa", "bed", "table", "chair", "toilet", "sink", "bathtub", "stove", "fridge"]
    x: float
    y: float
    rotation: float = 0.0
    color: str | None = None


class FloorPlan(BaseModel):
    id: str
    name: str
    unit: str = "meters"
    walls: list[Wall]
    doors: list[Door] = []
    windows: list[Window] = []
    furniture: list[Furniture] = []


class DetectionOptions(BaseModel):
    scale_px_per_unit: float = Field(default=100.0, gt=0)
    default_wall_height: float = Field(default=2.7, gt=0)
    default_wall_thickness: float = Field(default=0.2, gt=0)
    page_number: int = Field(default=0, ge=0)
    min_wall_thickness_px: int = Field(default=8, gt=0)