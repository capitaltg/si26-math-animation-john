def check_text_card_compatibility(params) -> None:
    if not params.headline or not params.headline.strip():
        raise ValueError("Text card headline must be nonblank")
    if not params.lines:
        raise ValueError("Text card requires at least one line")
    if any(not line or not line.strip() for line in params.lines):
        raise ValueError("Text card lines must all be nonblank")
