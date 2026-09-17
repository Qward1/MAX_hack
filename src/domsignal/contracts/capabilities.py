from typing import Literal

from domsignal.contracts.common import ContractModel


class CapabilityFlags(ContractModel):
    test_auth: bool
    report_create: bool = True
    incident_board: bool = True
    incident_detail: bool = True
    max_live: bool = False
    group_mode: bool = False
    routes: bool = False
    appeals: bool = False
    reminders: bool = False
    media: bool = False


class CapabilitiesResponse(ContractModel):
    contract_version: Literal["c0"] = "c0"
    environment: Literal["local", "test", "production"]
    features: CapabilityFlags
