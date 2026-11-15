"""Realtime Voice Agent v2 — MIT portfolio package (Acme Telco / Ava).

This module is the public import surface. Frame codec: ``rva.audiosocket``.
Band-limited resample: ``rva.resample``. Energy VAD: ``rva.vad``.
Call session barge-in: ``rva.session``. 20 ms TX pacing: ``rva.tx``.
STT/LLM/TTS mocks and factory: ``rva.pipeline``. HTTP clients land in a later issue.
"""

__all__ = ["__version__"]
__version__ = "0.2.0"
