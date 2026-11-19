"""
citeverify_core.doc_intel – M1 Document Intelligence module.

Public API
----------
parse_document(file_path, raw_text, doc_id) -> ParsedDocument
"""

from citeverify_core.doc_intel.parser import parse_document

__all__ = ["parse_document"]
