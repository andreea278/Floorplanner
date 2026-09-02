from __future__ import annotations

import uuid

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.models.floorplan import FloorPlan
from app.services.detection_service import detect_floorplan_elements
from app.services.pdf_service import pdf_bytes_to_image

router = APIRouter(prefix="/api/floorplan", tags=["floorplan"])

PDF_CONTENT_TYPES = {"application/pdf"}
IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.post("/detect", response_model=FloorPlan)
async def detect_floorplan(
    file: UploadFile = File(...),
    scale_px_per_unit: float = 100.0,
    default_wall_height: float = 2.7,
    default_wall_thickness: float = 0.2,
    page_number: int = 0,
    min_wall_thickness_px: int = 8,
    max_opening_width_units: float = 3.0,
) -> FloorPlan:
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    content_type = file.content_type or ""

    if content_type in PDF_CONTENT_TYPES or (file.filename or "").lower().endswith(".pdf"):
        try:
            image = pdf_bytes_to_image(content, page_number=page_number)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not read PDF: {exc}") from exc
    elif content_type in IMAGE_CONTENT_TYPES or _looks_like_image(file.filename):
        image_array = np.frombuffer(content, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            raise HTTPException(
                status_code=400, detail="Could not decode image file")
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {content_type or 'unknown'}. "
            "Upload a PDF, PNG, or JPEG.",
        )

    result = detect_floorplan_elements(
        image,
        scale_px_per_unit=scale_px_per_unit,
        default_height=default_wall_height,
        default_thickness=default_wall_thickness,
        min_wall_thickness_px=min_wall_thickness_px,
        max_opening_width_units=max_opening_width_units,
    )

    return FloorPlan(
        id=f"floorplan-{uuid.uuid4().hex[:8]}",
        name=file.filename or "Detected Floor Plan",
        unit="meters",
        walls=result.walls,
        doors=result.doors,
        windows=result.windows,
    )


def _looks_like_image(filename: str | None) -> bool:
    if not filename:
        return False
    return filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))