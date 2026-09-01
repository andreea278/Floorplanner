"""
Wall detection pipeline.

Image -> grayscale -> binarize (thickness-filtered) -> line segments (Hough) -> merge into walls

This is deliberately "classical CV", not ML. It works well on clean,
high-contrast architectural plans (straight black lines on white background).
It will do a mediocre job on hand-drawn or noisy scans - that's expected
for a first version. The frontend 2D editor is the fallback for fixing
whatever this gets wrong.
"""
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


def _binarize(gray: np.ndarray, min_wall_thickness_px: int = 8) -> np.ndarray:
    """Turn a grayscale floorplan image into a clean black/white line image
    containing only wall-thickness strokes.

    Real walls are drawn as thick, solid lines. Room labels, titles,
    dimension text, and door/window symbols (arcs, tick marks) are all
    much thinner strokes - without filtering those out, Hough happily fits
    tiny "wall" segments to individual letters or symbol lines, which is
    exactly what produced the phantom floating wall fragments seen above
    real plans and inside rooms (room-label text, mostly).

    We remove anything thinner than `min_wall_thickness_px` with a
    morphological opening (erode then dilate) BEFORE closing gaps, so thin
    content disappears entirely instead of surviving and then being
    bridged into something that reads as wall-like. A blob only survives
    the opening if it's at least `min_wall_thickness_px` wide in every
    direction - text strokes and 1-2pt annotation lines are nowhere close
    to that at typical scan/render resolutions (100-300 DPI), while walls
    drawn several points thick comfortably are.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    # Otsu's threshold works well for plans that are basically black lines on
    # a white/light background (typical PDF export or scanned blueprint).
    _, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (min_wall_thickness_px, min_wall_thickness_px)
    )
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_kernel)

    # Close small gaps in wall lines (broken by hatching, minor scan noise,
    # etc.) so Hough sees continuous segments. This runs AFTER the opening
    # step above, so it can only bridge gaps within already wall-thick
    # strokes - it can't resurrect the thin text/symbols just removed.
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    return closed


def _detect_raw_segments(binary: np.ndarray) -> list[Segment]:
    lines = cv2.HoughLinesP(
        binary,
        rho=1,
        theta=np.pi / 180,
        threshold=60,
        minLineLength=30,
        maxLineGap=8,
    )

    if lines is None:
        return []

    # OpenCV 4.x returns shape (N, 1, 4); OpenCV 5.x returns shape (N, 4)
    # directly. Reshape defensively to (N, 4) so this works either way,
    # instead of assuming one specific shape.
    lines = lines.reshape(-1, 4)

    return [Segment(float(x1), float(y1), float(x2), float(y2)) for x1, y1, x2, y2 in lines]


def _snap_to_axis(seg: Segment, tolerance_deg: float = 6.0) -> Segment:
    """Snap near-horizontal / near-vertical segments to be exactly axis-aligned.

    Architectural plans are almost always drawn with orthogonal walls, and
    Hough output is noisy by a few pixels, so this removes a lot of the
    jitter that would otherwise show up as slightly-tilted walls.
    """
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
    max_bridge_gap_px: float = 20.0,
) -> list[Segment]:
    """Merge near-collinear, nearby segments into single longer walls -
    but preserve real gaps (doorways) instead of always bridging straight
    across a cluster's full extent.

    Hough typically returns many short overlapping fragments for what is
    really one continuous wall. We group by orientation + offset from
    origin, then, within each offset-group, segments are only joined
    together if the gap *along the wall's own length* between them is
    small (max_bridge_gap_px) - a small gap is assumed to be noise (text
    crossing the wall, a broken scan line) and gets bridged; a larger gap
    is assumed to be a real opening (a doorway) and is kept as two
    separate walls instead of being silently erased.

    The offset-grouping itself uses CHAIN clustering: a new segment joins
    a cluster if it's within `distance_tolerance_px` of the *last* segment
    added to that cluster, not the first. A single thick wall stroke
    produces Hough lines along BOTH of its edges (plus jitter between
    them) - e.g. offsets 943, 944, ..., 958 for one ~15px-thick wall. Each
    consecutive step in that chain is small, but the total span (943 to
    958) can exceed the tolerance. Comparing only to the first element
    would then split that single wall into two ("top edge" / "bottom
    edge") - which is exactly the double-wall bug this fixes. Comparing to
    the last element lets the whole chain merge into one wall instead.
    """
    horizontals = [s for s in segments if s.angle_deg < 45 or s.angle_deg > 135]
    verticals = [s for s in segments if 45 <= s.angle_deg <= 135]

    def merge_group(group: list[Segment], is_horizontal: bool) -> list[Segment]:
        if not group:
            return []

        # offset key: y for horizontal walls, x for vertical walls
        offset_key = (lambda s: (s.y1 + s.y2) /
                      2) if is_horizontal else (lambda s: (s.x1 + s.x2) / 2)
        # position-along-the-wall key: x for horizontal, y for vertical -
        # this is the axis we check gap size along, before bridging.
        along_min = (lambda s: min(s.x1, s.x2)) if is_horizontal else (
            lambda s: min(s.y1, s.y2))
        along_max = (lambda s: max(s.x1, s.x2)) if is_horizontal else (
            lambda s: max(s.y1, s.y2))

        group = sorted(group, key=offset_key)
        offset_clusters: list[list[Segment]] = []

        for seg in group:
            placed = False
            for cluster in offset_clusters:
                # Compare to the LAST segment added to this cluster (chain
                # clustering), not the first - see the docstring above.
                if abs(offset_key(seg) - offset_key(cluster[-1])) <= distance_tolerance_px:
                    cluster.append(seg)
                    placed = True
                    break
            if not placed:
                offset_clusters.append([seg])

        merged: list[Segment] = []

        for cluster in offset_clusters:
            # Within this same-offset cluster (e.g. "all segments between
            # roughly y=943 and y=958"), sort by position along the wall,
            # then walk through and only bridge consecutive segments whose
            # gap is small. A gap bigger than max_bridge_gap_px starts a
            # new, separate wall run instead of being absorbed.
            cluster = sorted(cluster, key=along_min)
            runs: list[list[Segment]] = []

            for seg in cluster:
                if runs and along_min(seg) - max(along_max(s) for s in runs[-1]) <= max_bridge_gap_px:
                    runs[-1].append(seg)
                else:
                    runs.append([seg])

            for run in runs:
                avg_offset = sum(offset_key(s) for s in run) / len(run)
                run_min = min(along_min(s) for s in run)
                run_max = max(along_max(s) for s in run)
                if is_horizontal:
                    merged.append(
                        Segment(run_min, avg_offset, run_max, avg_offset))
                else:
                    merged.append(
                        Segment(avg_offset, run_min, avg_offset, run_max))

        return merged

    return merge_group(horizontals, True) + merge_group(verticals, False)


def detect_walls(
    image: np.ndarray,
    scale_px_per_unit: float = 100.0,
    min_wall_length_px: float = 25.0,
    default_height: float = 2.7,
    default_thickness: float = 0.2,
    min_wall_thickness_px: int = 8,
) -> list[dict]:
    """
    Detect walls in a floorplan image.

    Args:
        image: BGR or grayscale image (as read by cv2.imread / decoded upload)
        scale_px_per_unit: how many pixels correspond to one unit (e.g. one
            meter). This is the piece we CANNOT know automatically without
            either a calibration step (user marks a known dimension) or a
            trained model. 100 px/m is a reasonable placeholder for now.
        min_wall_length_px: discard fragments shorter than this (noise)
        default_height / default_thickness: 2D plans give no info on wall
            height, so we assume a standard interior wall until the user
            edits it in the 2D editor.
        min_wall_thickness_px: strokes thinner than this (in the rendered
            image) are discarded before line detection even runs - this is
            what keeps room labels, titles, dimension text, and door/window
            symbols from being mistaken for walls. Raise it if thin real
            walls are getting eaten; lower it if bold/large text is still
            leaking through as phantom walls.

    Returns:
        list of dicts matching the frontend `Wall` type
        ({id, start:{x,y}, end:{x,y}, height, thickness})
    """
    gray = cv2.cvtColor(
        image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    binary = _binarize(gray, min_wall_thickness_px=min_wall_thickness_px)
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