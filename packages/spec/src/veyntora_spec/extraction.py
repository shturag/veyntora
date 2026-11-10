"""How a data source's documents are read into text (ADR 0040).

Set per source: a scanned archive and a wiki need different readers. Chunking, embeddings
and search stay in each chatbot's pipeline. A source without its own setting is read as the
pipeline of each chatbot it is attached to says (sources from before ADR 0040, "My files").
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from veyntora_spec.pipeline import IngestionSpec


class ExtractionMethod(StrEnum):
    # Per file: PDFs with a text layer are read directly, scans and other formats by the parser.
    AUTO = "auto"
    # The text layer of PDFs only (fast, no layout, no OCR); other formats by the parser.
    TEXT = "text"
    # The document parser (Docling): headings, tables, reading order, OCR for scans.
    LAYOUT = "layout"
    # A vision-language model transcribes every PDF and image page (ADR 0037).
    VISION = "vision"


class ExtractionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: ExtractionMethod = ExtractionMethod.AUTO
    # The document parser (Docling); every method needs it for formats other than PDF.
    parser_instance_id: UUID | None = None
    ocr: bool = True
    extract_tables: bool = True
    describe_images: bool = False
    # The vision model: reads pages (method "vision") and describes pictures.
    vision_instance_id: UUID | None = None

    @model_validator(mode="after")
    def _vision_needs_model(self) -> ExtractionSpec:
        if self.method is ExtractionMethod.VISION and self.vision_instance_id is None:
            raise ValueError("reading pages with a vision model needs a vision model")
        return self

    @classmethod
    def of_pipeline(cls, ing: IngestionSpec) -> ExtractionSpec:
        """How a pipeline's ingestion settings read documents (before ADR 0040)."""
        return cls.model_construct(
            method=ExtractionMethod.VISION if ing.vision_pages else ExtractionMethod.LAYOUT,
            parser_instance_id=ing.parser_instance_id,
            ocr=ing.ocr,
            extract_tables=ing.extract_tables,
            describe_images=ing.describe_images,
            vision_instance_id=ing.vision_instance_id,
        )


class FileFilters(BaseModel):
    """Which of a source's files are read; the others are skipped (and removed if indexed)."""

    model_config = ConfigDict(extra="forbid")

    # File extensions without the dot ("pdf", "docx"); empty: every supported type.
    file_types: list[str] = Field(default_factory=list, max_length=30)
    # Files above this size are skipped; None: the platform's upload limit.
    max_file_mb: int | None = Field(None, ge=1, le=2048)
    # Glob patterns on the path ("/policies/*", "*.pdf"); empty: everything.
    include: list[str] = Field(default_factory=list, max_length=50)
    # Glob patterns to skip ("*/archive/*", "*.tmp"); checked after include.
    exclude: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _clean(self) -> FileFilters:
        self.file_types = sorted(
            {t.strip().lower().lstrip(".") for t in self.file_types if t.strip()}
        )
        for p in [*self.include, *self.exclude]:
            if not p.strip() or len(p) > 512:
                raise ValueError(
                    "patterns are paths like /policies/* or *.pdf (up to 512 characters)"
                )
        return self


class SourceReading(BaseModel):
    """A source's reading settings, stored in its config under "reading"."""

    model_config = ConfigDict(extra="forbid")

    # None: as each attached chatbot's pipeline says (sources from before ADR 0040).
    extraction: ExtractionSpec | None = None
    filters: FileFilters = Field(default_factory=FileFilters)
