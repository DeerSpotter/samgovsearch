"""Deterministic public-source ingestion for Contract Brain."""

from .extractor import PARSER_VERSION, ExtractionResult, LogicalRow, extract_payload

__all__ = ["PARSER_VERSION", "ExtractionResult", "LogicalRow", "extract_payload"]
