from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EmployeeLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=4096, repr=False)


class EmployeePassword(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=4096, repr=False)


class EmployeeCode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=64, repr=False)


class EmployeeSession(BaseModel):
    stage: Literal["login", "password_change", "mfa_enroll", "mfa_challenge", "authenticated"]
    csrf_token: str
    recovery_codes: list[str] = Field(default_factory=list)


class EmployeeEnrollment(BaseModel):
    secret: str
    otpauth_uri: str
    qr_svg: str
