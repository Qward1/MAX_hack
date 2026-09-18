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
        permissions = {"incident.read", "report.create"} if resident or employee else set()
        if employee:
            permissions.update({"ticket.read", "ticket.work"})
        if resident:
            permissions.update({"work.read", "work.observe"})
        if organization_role == "company_admin" or (
            organization_role == "operator" and assignment_role == "responsible"
        ):
            permissions.add("chat.connect")
            permissions.add("ticket.manage")
        return frozenset(permissions)
