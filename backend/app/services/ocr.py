"""OCR pipeline with pluggable engines.

Engines implement :class:`OcrEngine`. The default ``stub`` engine handles
plain-text and UTF-8 decodable uploads deterministically (used in tests and
development). The ``tesseract`` engine shells out to pytesseract when the
binary is installed (the production Docker image installs it).

Each page result carries an engine-reported confidence which propagates into
the Evidence Ledger for anything extracted from that page.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings


@dataclass
class OcrPage:
    page_number: int
    text: str
    confidence: float
    layout: dict | None = None


class OcrEngine(Protocol):
    name: str

    def process(self, path: Path, content_type: str) -> list[OcrPage]: ...


class StubOcrEngine:
    """Deterministic engine: reads text-like files directly.

    For binary images it returns an empty page with zero confidence so the
    document is flagged for manual transcription rather than silently
    producing garbage.
    """

    name = "stub"

    def process(self, path: Path, content_type: str) -> list[OcrPage]:
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return [OcrPage(page_number=1, text="", confidence=0.0)]
        # Form-feed separates pages in text documents.
        pages = text.split("\f")
        return [
            OcrPage(page_number=i + 1, text=page, confidence=0.98 if page.strip() else 0.0)
            for i, page in enumerate(pages)
        ]


class TesseractOcrEngine:
    name = "tesseract"

    def process(self, path: Path, content_type: str) -> list[OcrPage]:
        import pytesseract  # optional dependency, installed in the Docker image
        from PIL import Image

        image = Image.open(path)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        words = [w for w in data["text"] if w.strip()]
        confs = [int(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and str(c) != "-1"]
        text = " ".join(words)
        confidence = (sum(confs) / len(confs) / 100.0) if confs else 0.0
        return [OcrPage(page_number=1, text=text, confidence=round(confidence, 4))]


_ENGINES: dict[str, type] = {"stub": StubOcrEngine, "tesseract": TesseractOcrEngine}


def get_ocr_engine(name: str | None = None) -> OcrEngine:
    engine_name = name or get_settings().ocr_engine
    try:
        return _ENGINES[engine_name]()
    except KeyError:
        raise ValueError(f"Unknown OCR engine '{engine_name}'. Available: {sorted(_ENGINES)}")
