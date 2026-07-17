from pathlib import Path

from pptx import Presentation


def extract_slide_texts(pptx_path: Path) -> list[str]:
    presentation = Presentation(pptx_path)
    texts = []
    for slide in presentation.slides:
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                parts.append(shape.text_frame.text)
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            parts.append(slide.notes_slide.notes_text_frame.text)
        texts.append("\n".join(p for p in parts if p.strip()))
    return texts


def chunk_slide_texts(slide_texts: list[str], chunk_size: int = 25) -> list[list[str]]:
    return [slide_texts[i:i + chunk_size] for i in range(0, len(slide_texts), chunk_size)]
