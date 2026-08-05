from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class Segment:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def angle_deg(self) -> float:
        return math.degrees(math.atan2(self.y2 - self.y1, self.x2 - self.x1)) % 180

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


def _binarize(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    return closed


def _detect_raw_segments(binary: np.narray) -> list[Segment]:
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi/180,
        threshold=60,
        minLineLength=30,
        maxLineGap=8,
    )
    if lines is None:
        return []

    lines = lines.reshape(-1, 4)

    return [Segment(float(x1), float(y1), float(x2), float(y2)) for x1, y1, x2, y2 in lines]


def _snap_to_axis(seg: Segment, tolerance_deg: float = 6.0) -> Segment:
    angle = seg.angle_deg
    if angle < tolerance_deg or angle > 180 - tolerance_deg:
        avg_y = (seg.y1 + seg.y2) / 2
        return Segment(seg.x1, avg_y, seg.x2, avg_y)
    if abs(angle - 90) < tolerance_deg:
        avg_x = (seg.x1 + seg.x2) / 2
        return Segment(avg_x, seg.y1, avg_x, seg.y2)
    return seg


def _merge_segments(
    segments: list[Segment],
    angle_tolerance_deg: float = 4.0,
    distance_tolerance_px: float = 12.0,
) -> list[Segment]:
    horizontals = [s for s in segments if s.angle_deg <
                   45 or s.angle_deg > 135]
    verticals = [s for s in segments if 45 <= s.angle_deg <= 135]

    def merge_group(group: list[Segment], is_horizontal: bool) -> list[Segment]:
        if not group:
            return []

        key = (lambda s: (s.y1 + s.y2) /
               2) if is_horizontal else (lambda s: (s.x1 + s.x2) / 2)

        group = sorted(group, key=key)
        clusters: list[list[Segment]] = []

        for seg in group:
            placed = False
            for cluster in clusters:
                if abs(key(seg) - key(cluster[0])) <= distance_tolerance_px:
                    cluster.append(seg)
                    placed = True
                    break
            if not placed:
                clusters.append([seg])

        merged: list[Segment] = []
        for cluster in clusters:
            if is_horizontal:
                xs = [s.x1 for s in cluster] + [s.x2 for s in cluster]
                avg_y = sum(key(s) for s in cluster) / len(cluster)
                merged.append(Segment(min(xs), avg_y, max(xs), avg_y))
            else:
                ys = [s.y1 for s in cluster] + [s.y2 for s in cluster]
                avg_x = sum(key(s) for s in cluster) / len(cluster)
                merged.append(Segment(avg_x, min(ys), avg_x, max(ys)))

        return merged

    return merge_group(horizontals, True) + merge_group(verticals, False)


def detect_walls(
    image: np.ndarray,
    scale_px_per_unit: float = 100.0,
    min_wall_length_px: float = 25.0,
    default_height: float = 2.7,
    default_thickness: float = 0.2,
) -> list[dict]:
    gray = cv2.cvtColor(
        image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    binary = _binarize(gray)
    raw_segments = _detect_raw_segments(binary)
    snapped = [_snap_to_axis(s) for s in raw_segments]
    merged = _merge_segments(snapped)
    merged = [s for s in merged if s.length >= min_wall_length_px]

    walls = []
    for seg in merged:
        walls.append(
            {
                "id": f"wall-{uuid.uuid4().hex[:8]}",
                "start": {
                    "x": round(seg.x1 / scale_px_per_unit, 3),
                    "y": round(seg.y1 / scale_px_per_unit, 3),
                },
                "end": {
                    "x": round(seg.x2 / scale_px_per_unit, 3),
                    "y": round(seg.y2 / scale_px_per_unit, 3),
                },
                "height": default_height,
                "thickness": default_thickness,
            }
        )

    return walls
