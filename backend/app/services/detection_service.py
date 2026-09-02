"""
Floorplan detection pipeline.

Image -> grayscale -> binarize (thickness-filtered) -> line segments (Hough)
-> merge into walls, tracking real gaps (openings) along the way
-> classify each opening as a door or a window -> Wall/Door/Window dicts

This is deliberately "classical CV", not ML. It works well on clean,
high-contrast architectural plans (straight black lines on white background,
real gaps at doorways/windows - the standard convention). It will do a
mediocre job on hand-drawn or noisy scans, and door/window classification
is a heuristic (see _classify_opening) that can get fooled by unusual
symbol styles - that's expected for a first version. The frontend 2D
editor is the fallback for fixing whatever this gets wrong.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field

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


@dataclass
class MergedWall:
    """A final, merged wall segment plus the real gaps found along its own
    length while merging - each gap is a candidate door/window opening,
    recorded as (gap_start_px, gap_end_px) in the same pixel "along the
    wall" coordinate as the segment itself."""
    segment: Segment
    gaps: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class DetectionResult:
    walls: list[dict]
    doors: list[dict]
    windows: list[dict]


def _binarize(gray: np.ndarray, min_wall_thickness_px: int = 8) -> np.ndarray:
    """Turn a grayscale floorplan image into a clean black/white line image
    containing only wall-thickness strokes.

    Real walls are drawn as thick, solid lines. Room labels, titles,
    dimension text, and door/window symbols (arcs, tick marks) are all
    much thinner strokes - without filtering those out, Hough happily fits
    tiny "wall" segments to individual letters or symbol lines, producing
    phantom wall fragments scattered across the plan.

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

    _, binary = cv2.threshold(
        blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )

    open_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (min_wall_thickness_px, min_wall_thickness_px)
    )
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, open_kernel)

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, close_kernel, iterations=2)

    return closed


def _binarize_raw(gray: np.ndarray) -> np.ndarray:
    """A second, much gentler binarization used ONLY for classifying what's
    inside a candidate door/window opening - never for wall detection.

    Door swing arcs and window tick marks are deliberately drawn as thin,
    often lighter-gray strokes so they don't get mistaken for walls (see
    `_binarize` above). That means we can't reuse the wall-detection binary
    here - its thickness filter would strip those symbols out too, which
    is exactly what we need to look AT for classification. A fixed
    threshold (rather than Otsu) is used here on purpose: Otsu's threshold
    is computed from the whole image and can land anywhere depending on
    how much wall/background area there is, which occasionally sets it too
    low to catch a lighter-gray symbol. A fixed cutoff reliably catches
    anything reasonably dark - both the symbols and stray text alike;
    `_classify_opening` below is what filters out the text.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(blurred, 200, 255, cv2.THRESH_BINARY_INV)
    return binary


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

    lines = lines.reshape(-1, 4)

    return [Segment(float(x1), float(y1), float(x2), float(y2)) for x1, y1, x2, y2 in lines]


def _snap_to_axis(seg: Segment, tolerance_deg: float = 6.0) -> Segment:
    """Snap near-horizontal / near-vertical segments to be exactly axis-aligned."""
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
    distance_tolerance_px: float = 12.0,
    min_opening_gap_px: float = 15.0,
    max_opening_gap_px: float = 300.0,
) -> list[MergedWall]:
    """Merge near-collinear, nearby segments into single longer walls,
    while recording any real gap along the way as a candidate door/window
    opening.

    Hough typically returns many short overlapping fragments for what is
    really one continuous wall (including duplicate fragments along BOTH
    edges of a thick stroke). We group by orientation + offset from origin
    using CHAIN clustering: a segment joins a cluster if it's within
    `distance_tolerance_px` of the LAST segment added to that cluster (not
    the first) - this is what correctly merges both edges of one thick
    wall into a single wall instead of two.

    Within an offset cluster, consecutive fragments are joined into one
    wall as long as the gap between them is small. Three cases:
      - gap <= min_opening_gap_px: noise (broken scan line, a stray pixel,
        text briefly crossing the wall) - bridged silently, no opening
        recorded.
      - min_opening_gap_px < gap <= max_opening_gap_px: a real,
        door/window-sized gap - still bridged into one continuous wall
        (matching the app's data model, where a door/window is a property
        of a single wall it sits on), but recorded as a candidate opening
        for classification.
      - gap > max_opening_gap_px: too big to be a door or window - kept as
        two separate, disconnected walls instead.
    """
    horizontals = [s for s in segments if s.angle_deg < 45 or s.angle_deg > 135]
    verticals = [s for s in segments if 45 <= s.angle_deg <= 135]

    def merge_group(group: list[Segment], is_horizontal: bool) -> list[MergedWall]:
        if not group:
            return []

        offset_key = (lambda s: (s.y1 + s.y2) /
                      2) if is_horizontal else (lambda s: (s.x1 + s.x2) / 2)
        along_min = (lambda s: min(s.x1, s.x2)) if is_horizontal else (
            lambda s: min(s.y1, s.y2))
        along_max = (lambda s: max(s.x1, s.x2)) if is_horizontal else (
            lambda s: max(s.y1, s.y2))

        group = sorted(group, key=offset_key)
        offset_clusters: list[list[Segment]] = []

        for seg in group:
            placed = False
            for cluster in offset_clusters:
                if abs(offset_key(seg) - offset_key(cluster[-1])) <= distance_tolerance_px:
                    cluster.append(seg)
                    placed = True
                    break
            if not placed:
                offset_clusters.append([seg])

        merged: list[MergedWall] = []

        for cluster in offset_clusters:
            cluster = sorted(cluster, key=along_min)
            runs: list[list[Segment]] = []
            run_gaps: list[list[tuple[float, float]]] = []

            for seg in cluster:
                if runs:
                    prev_max = max(along_max(s) for s in runs[-1])
                    gap = along_min(seg) - prev_max
                    if gap <= max_opening_gap_px:
                        if gap > min_opening_gap_px:
                            run_gaps[-1].append((prev_max, along_min(seg)))
                        runs[-1].append(seg)
                        continue
                runs.append([seg])
                run_gaps.append([])

            for run, gaps in zip(runs, run_gaps):
                avg_offset = sum(offset_key(s) for s in run) / len(run)
                run_min = min(along_min(s) for s in run)
                run_max = max(along_max(s) for s in run)
                if is_horizontal:
                    seg = Segment(run_min, avg_offset, run_max, avg_offset)
                else:
                    seg = Segment(avg_offset, run_min, avg_offset, run_max)
                merged.append(MergedWall(segment=seg, gaps=gaps))

        return merged

    return merge_group(horizontals, True) + merge_group(verticals, False)


def _classify_opening(
    symbol_binary: np.ndarray,
    is_horizontal: bool,
    wall_offset: float,
    gap_start: float,
    gap_end: float,
    wall_thickness_px: float,
) -> tuple[str, float]:
    """Look at the strip of image spanning one candidate wall opening and
    decide whether it looks like a door (a swing arc/leaf reaching well
    away from the wall) or a window (tick marks that stay close to the
    wall line). Falls back to "door" if no symbol at all was found, since
    an unmarked gap is far more often a doorway than a window in practice.

    Only ink that actually TOUCHES the wall (its nearest point is within
    `wall_thickness_px * 2`) is considered - this is what stops unrelated
    nearby content (dimension text, a room label, a title sitting close to
    an exterior wall) from being mistaken for the opening's own symbol
    just because it happened to fall inside the search box.

    Returns (kind, max_perpendicular_reach_px) - the second value is
    mainly useful for debugging/tuning, not needed by callers.
    """
    search_radius = max(gap_end - gap_start, wall_thickness_px * 4)
    height, width = symbol_binary.shape

    if is_horizontal:
        y0 = max(0, int(wall_offset - search_radius))
        y1 = min(height, int(wall_offset + search_radius))
        x0 = max(0, int(gap_start))
        x1 = min(width, int(gap_end))
        roi = symbol_binary[y0:y1, x0:x1]
        local_wall_offset = wall_offset - y0
        perp_axis = 0
    else:
        x0 = max(0, int(wall_offset - search_radius))
        x1 = min(width, int(wall_offset + search_radius))
        y0 = max(0, int(gap_start))
        y1 = min(height, int(gap_end))
        roi = symbol_binary[y0:y1, x0:x1]
        local_wall_offset = wall_offset - x0
        perp_axis = 1

    if roi.size == 0 or roi.max() == 0:
        return "door", 0.0

    num_labels, labels = cv2.connectedComponents(roi.astype(np.uint8))
    touch_threshold = wall_thickness_px * 2
    max_perp = 0.0

    for label_id in range(1, num_labels):
        coords = np.nonzero(labels == label_id)
        perp_coords = coords[perp_axis]
        dist = np.abs(perp_coords - local_wall_offset)
        if dist.min() <= touch_threshold:
            max_perp = max(max_perp, float(dist.max()))

    if max_perp == 0.0:
        return "door", 0.0

    window_reach_px = wall_thickness_px * 1.5
    return ("window", max_perp) if max_perp <= window_reach_px else ("door", max_perp)


def detect_floorplan_elements(
    image: np.ndarray,
    scale_px_per_unit: float = 100.0,
    min_wall_length_px: float = 25.0,
    default_height: float = 2.7,
    default_thickness: float = 0.2,
    min_wall_thickness_px: int = 8,
    max_opening_width_units: float = 3.0,
) -> DetectionResult:
    """
    Detect walls, doors, and windows in a floorplan image.

    Args:
        image: BGR or grayscale image (as read by cv2.imread / decoded upload)
        scale_px_per_unit: how many pixels correspond to one unit (e.g. one
            meter). This is the piece we CANNOT know automatically without
            either a calibration step (user marks a known dimension) or a
            trained model. 100 px/m is a reasonable placeholder for now.
        min_wall_length_px: discard wall fragments shorter than this (noise)
        default_height / default_thickness: 2D plans give no info on wall
            height, so we assume a standard interior wall until the user
            edits it in the 2D editor.
        min_wall_thickness_px: strokes thinner than this (in the rendered
            image) are discarded before line detection even runs - this is
            what keeps room labels, titles, dimension text, and door/window
            symbols from being mistaken for walls themselves.
        max_opening_width_units: gaps in a wall wider than this (in the
            same real-world units as scale_px_per_unit implies, e.g.
            meters) are assumed to be something other than a door/window
            (an intentional break, a missing wall) and are left as two
            separate walls instead of being treated as an opening.

    Returns:
        DetectionResult(walls, doors, windows) - dicts matching the
        frontend Wall/Door/Window types. Doors/windows reference their
        wall via wallId and use the same default width/height the 2D
        editor uses for manually-added ones (0.9x2.1m doors, 1.2x1.2m
        windows with a 0.9m sill) since real height isn't visible in a 2D
        plan any more than wall height is.
    """
    gray = cv2.cvtColor(
        image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

    binary = _binarize(gray, min_wall_thickness_px=min_wall_thickness_px)
    raw_segments = _detect_raw_segments(binary)
    snapped = [_snap_to_axis(s) for s in raw_segments]

    max_opening_gap_px = scale_px_per_unit * max_opening_width_units
    merged_walls = _merge_segments(snapped, max_opening_gap_px=max_opening_gap_px)
    merged_walls = [mw for mw in merged_walls if mw.segment.length >= min_wall_length_px]

    symbol_binary = _binarize_raw(gray)
    wall_thickness_px = max(default_thickness * scale_px_per_unit, 6.0)

    walls: list[dict] = []
    doors: list[dict] = []
    windows: list[dict] = []

    for mw in merged_walls:
        seg = mw.segment
        wall_id = f"wall-{uuid.uuid4().hex[:8]}"

        walls.append(
            {
                "id": wall_id,
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

        # After _merge_segments, a horizontal wall always has y1 == y2 and
        # a vertical wall always has x1 == x2 - the "start" coordinate
        # (x1 for horizontal, y1 for vertical) is always the smaller one,
        # matching the wall dict's "start" above, so offsets computed here
        # line up with it directly.
        is_horizontal = seg.y1 == seg.y2
        wall_start_along = seg.x1 if is_horizontal else seg.y1
        wall_offset = seg.y1 if is_horizontal else seg.x1

        for gap_start, gap_end in mw.gaps:
            kind, _ = _classify_opening(
                symbol_binary, is_horizontal, wall_offset, gap_start, gap_end, wall_thickness_px
            )
            offset_units = ((gap_start + gap_end) / 2 - wall_start_along) / scale_px_per_unit
            width_units = (gap_end - gap_start) / scale_px_per_unit

            if kind == "door":
                doors.append(
                    {
                        "id": f"door-{uuid.uuid4().hex[:8]}",
                        "wallId": wall_id,
                        "offset": round(max(offset_units, 0.0), 3),
                        "width": round(max(width_units, 0.1), 3),
                        "height": 2.1,
                    }
                )
            else:
                windows.append(
                    {
                        "id": f"window-{uuid.uuid4().hex[:8]}",
                        "wallId": wall_id,
                        "offset": round(max(offset_units, 0.0), 3),
                        "width": round(max(width_units, 0.1), 3),
                        "height": 1.2,
                        "sillHeight": 0.9,
                    }
                )

    return DetectionResult(walls=walls, doors=doors, windows=windows)