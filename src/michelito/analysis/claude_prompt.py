"""The fixed prompt that goes with the month's dossier when it is handed to Claude.

A single source: "Copy for Claude" in the interface uses it (`GET /api/dossier/prompt`; the user
can edit it before copying) and so will the dossier's MCP tool. It repeats the dossier's defense
(`dossier.DATA_NOTICE`): what goes inside ```text blocks is data, not instructions. The text is
Spanish, from the catalog (`dossier.prompt`).
"""

from __future__ import annotations

from michelito.i18n import t

MAX_WORDS = 400

INSTRUCTION = t("dossier.prompt", max_words=MAX_WORDS)
