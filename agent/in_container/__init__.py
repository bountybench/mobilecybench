"""Shared in-container code baked into every BYO reference image.

Sits beside per-image directories (``agent/codex/``, ``agent/claude_code/``,
…) and is COPY'd into every image's ``/opt/agent/in_container/``. Future BYO
ref-images opt in by importing ``agent.in_container.runner.run``.
"""
