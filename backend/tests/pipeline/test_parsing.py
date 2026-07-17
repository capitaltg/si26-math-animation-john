from pptx import Presentation


def _build_sample_pptx(path):
    presentation = Presentation()
    layout = presentation.slide_layouts[1]

    slide1 = presentation.slides.add_slide(layout)
    slide1.shapes.title.text = "Warm Up"
    slide1.placeholders[1].text = "Sarah has 4 apples and buys 3 more. How many now?"
    slide1.notes_slide.notes_text_frame.text = "Remind students this is simple addition."

    slide2 = presentation.slides.add_slide(layout)
    slide2.shapes.title.text = "Agenda"
    slide2.placeholders[1].text = "Standards: 3.OA.A.1"

    presentation.save(path)


def test_extract_slide_texts_includes_body_and_notes(tmp_path):
    from app.pipeline.parsing import extract_slide_texts

    pptx_path = tmp_path / "sample.pptx"
    _build_sample_pptx(pptx_path)

    texts = extract_slide_texts(pptx_path)

    assert len(texts) == 2
    assert "Sarah has 4 apples" in texts[0]
    assert "simple addition" in texts[0]
    assert "3.OA.A.1" in texts[1]


def test_chunk_slide_texts_splits_at_chunk_size():
    from app.pipeline.parsing import chunk_slide_texts

    slide_texts = [f"slide {i}" for i in range(50)]

    chunks = chunk_slide_texts(slide_texts, chunk_size=25)

    assert len(chunks) == 2
    assert len(chunks[0]) == 25
    assert len(chunks[1]) == 25
    assert chunks[0][0] == "slide 0"
    assert chunks[1][0] == "slide 25"
