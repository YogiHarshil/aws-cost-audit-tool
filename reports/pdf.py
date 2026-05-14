"""WeasyPrint HTML to PDF."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

from weasyprint import HTML

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def generate_pdf(html_content: str, output_path: PathLike) -> Path:
    """Write ``html_content`` to ``output_path`` as a PDF (Letter, embedded assets).

    Creates parent directories as needed. Returns the resolved ``Path``.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        HTML(string=html_content, base_url=str(path.parent)).write_pdf(path)
    except Exception as exc:
        logger.error("WeasyPrint PDF generation failed: %s", exc, exc_info=True)
        raise
    return path.resolve()
