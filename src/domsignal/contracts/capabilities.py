from typing import Literal

from domsignal.contracts.common import ContractModel


class CapabilityFlags(ContractModel):
    test_auth: bool
    report_create: bool = True
    incident_board: bool = True
    incident_detail: bool = True
    max_live: bool = False
    group_mode: bool = False
    miniapp: bool = True
    # Внешний провайдер разбора подключён. Правила работают всегда, поэтому
    # false не скрывает явный путь, а только уточнение моделью.
    ai_analysis: bool = False
    photo_analysis: bool = False
    voice: bool = False
    admin: bool = False
    routes: bool = False
    appeals: bool = False
    # Глобальный выключатель пассивного чтения чатов (`PASSIVE_CAPTURE_ENABLED`).
    # Выключен — чтение отдельного чата включить нельзя.
    passive_capture: bool = False
    # Модель разбирает окна пассивного чтения: провайдер подключён и
    # `PASSIVE_LLM_ENABLED` не выключен. false — окна разбирают только правила;
    # явный путь (`/report`, форма) от флага не зависит (`ai_analysis`).
    passive_ai_analysis: bool = False
    reminders: bool = False
    media: bool = False


class CapabilitiesResponse(ContractModel):
    contract_version: Literal["c0.1"] = "c0.1"
    environment: Literal["local", "test", "production"]
    features: CapabilityFlags
