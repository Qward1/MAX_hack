from enum import StrEnum


class ReportCategory(StrEnum):
    ELEVATOR = "elevator"
    WATER = "water"
    LIGHTING = "lighting"
    WASTE = "waste"
    OTHER = "other"


class IncidentStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ClassificationMode(StrEnum):
    MANUAL = "manual"


CATEGORY_TITLES: dict[ReportCategory, str] = {
    ReportCategory.ELEVATOR: "Проблема с лифтом",
    ReportCategory.WATER: "Проблема с водой",
    ReportCategory.LIGHTING: "Проблема с освещением",
    ReportCategory.WASTE: "Проблема с отходами",
    ReportCategory.OTHER: "Другая проблема дома",
}
