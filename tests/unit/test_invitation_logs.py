import logging

from domsignal.api.errors import InvitationLogFilter


def test_invitation_token_is_redacted_from_uvicorn_access_record():
    token = "private-invitation-" + "x" * 40
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %s',
        ("127.0.0.1", "GET", f"/admin/invite/{token}", "1.1", 200),
        None,
    )
    assert InvitationLogFilter().filter(record)
    assert token not in record.getMessage()
    assert "/admin/invite/[redacted]" in record.getMessage()
