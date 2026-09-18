"""Small product access policy. Platform privilege never grants resident reads."""


class AccessPolicy:
    @staticmethod
    def permissions(
        *,
        organization_role: str | None,
        assignment_role: str | None,
        resident: bool,
    ) -> frozenset[str]:
        employee = organization_role == "company_admin" or (
            organization_role == "operator" and assignment_role in {"responsible", "operator"}
        )
        if resident or employee:
            return frozenset({"incident.read", "report.create"})
        return frozenset()
