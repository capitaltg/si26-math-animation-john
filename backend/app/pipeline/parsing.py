from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


def _extract_shape_text(shape) -> list[str]:
    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [
            text
            for child in shape.shapes
            for text in _extract_shape_text(child)
        ]
    if shape.has_table:
        return [cell.text for row in shape.table.rows for cell in row.cells]
    if shape.has_text_frame:
        return [shape.text_frame.text]
    return []


def extract_slide_texts(pptx_path: Path) -> list[str]:
    presentation = Presentation(pptx_path)
    texts = []
    for slide in presentation.slides:
        parts = []
        for shape in slide.shapes:
            parts.extend(_extract_shape_text(shape))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            parts.append(slide.notes_slide.notes_text_frame.text)
        texts.append("\n".join(p for p in parts if p.strip()))
    return texts


def chunk_slide_texts(slide_texts: list[str], chunk_size: int = 25) -> list[list[str]]:
    return [slide_texts[i:i + chunk_size] for i in range(0, len(slide_texts), chunk_size)]
