"""Small explicit cues for status announcements; model handles the rest."""
from __future__ import annotations

import re

RESOLVED = re.compile(
    r"\b(?:заработал\w*|починил\w*|устранил\w*|отремонтировал\w*|"
    r"включил\w*|восстановил\w*|появил\w*сь|перестал\w* течь|"
    r"дали (?:воду|свет|отопление)|вода пошла)\b",
    re.I,
)
PLANNED = re.compile(
    r"планов\w* (?:отключен|работ|проверк)|"
    r"(?:завтра|по графику) отключ\w*|проверка (?:пожарн\w* )?сигнализац",
    re.I,
)


def utterance_of(text: str, model_label: str) -> str:
    low = text.lower()
    if RESOLVED.search(low):
        if "?" in low or "когда" in low or "если" in low:
            return "status_inquiry"
        return "resolved_notice"
    if PLANNED.search(low):
        return "planned_outage_info"
    return model_label
