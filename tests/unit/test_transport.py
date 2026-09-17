from domsignal.bot.transport import OffTransport, OutboundNotification


async def test_off_transport_has_no_external_delivery() -> None:
    result = await OffTransport().send(
        OutboundNotification(destination="test", text="must remain offline")
    )
    assert result is None
