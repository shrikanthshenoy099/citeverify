"""
verification/__init__.py – Public interface for the M3 verification module.

External callers (M4 orchestrator) import from here:

    from citeverify_core.verification import verify, reverify_for_reference
"""

from citeverify_core.verification.engine import reverify_for_reference, verify

__all__ = ["verify", "reverify_for_reference"]
