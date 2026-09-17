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
    photo_analysis: bool = False
    voice: bool = False
    admin: bool = False
    routes: bool = False
    appeals: bool = False
    reminders: bool = False
    media: bool = False


class CapabilitiesResponse(ContractModel):
    contract_version: Literal["c0.1"] = "c0.1"
    environment: Literal["local", "test", "production"]
    features: CapabilityFlags
