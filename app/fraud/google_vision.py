from __future__ import annotations

import asyncio


def _extract_text_sync(image_bytes: bytes) -> str:
    from google.cloud import vision
    
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_bytes)
    response = client.annotate_image(
        {
            "image": image,
            "features": [{"type_": vision.Feature.Type.TEXT_DETECTION}],
        }
    )
    if response.error.message:
        return ""

    if response.full_text_annotation and response.full_text_annotation.text:
        return response.full_text_annotation.text

    if response.text_annotations:
        return response.text_annotations[0].description

    return ""


def _dominant_rgb_sync(image_bytes: bytes) -> tuple[int, int, int] | None:
    from google.cloud import vision
    
    client = vision.ImageAnnotatorClient()
    image = vision.Image(content=image_bytes)
    response = client.annotate_image(
        {
            "image": image,
            "features": [{"type_": vision.Feature.Type.IMAGE_PROPERTIES}],
        }
    )
    if response.error.message:
        return None

    colors = response.image_properties_annotation.dominant_colors.colors
    if not colors:
        return None

    top = max(colors, key=lambda c: c.pixel_fraction)
    return int(top.color.red), int(top.color.green), int(top.color.blue)


async def extract_text(image_bytes: bytes) -> str:
    try:
        return await asyncio.to_thread(_extract_text_sync, image_bytes)
    except Exception:
        return ""


async def dominant_rgb(image_bytes: bytes) -> tuple[int, int, int] | None:
    try:
        return await asyncio.to_thread(_dominant_rgb_sync, image_bytes)
    except Exception:
        return None
