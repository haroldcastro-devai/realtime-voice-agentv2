"""Realtime Voice Agent v2 — MIT portfolio package (Acme Telco / Ava).

This module is the public import surface. Frame codec: ``rva.audiosocket``.
Band-limited resample: ``rva.resample``. Energy VAD: ``rva.vad``.
Call session barge-in: ``rva.session``. 20 ms TX pacing: ``rva.tx``.
Inference backends land in later issues.
"""

__all__ = ["__version__"]
__version__ = "0.2.0"
