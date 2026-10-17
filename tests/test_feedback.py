from types import SimpleNamespace
from unittest.mock import AsyncMock

from apu import feedback, telegram_bot


async def test_vote_callback_is_owner_only_and_does_not_route_to_confirmation(monkeypatch):
    record = AsyncMock(return_value=True)
    monkeypatch.setattr(feedback, "record", record)
    query = SimpleNamespace(
        data="vote:daily:1:-1",
        message=SimpleNamespace(message_id=20),
        answer=AsyncMock(),
        edit_message_reply_markup=AsyncMock(),
    )
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=999), callback_query=query)
    await feedback.on_vote(update, None)
    record.assert_not_awaited()
    update.effective_chat.id = 1
    await feedback.on_vote(update, None)
    assert record.await_args.kwargs["message_id"] == 20
    assert query.edit_message_reply_markup.await_count == 1
    handlers = []
    telegram_bot.build(SimpleNamespace(add_handler=handlers.append))
    callbacks = [h for h in handlers if h.__class__.__name__ == "CallbackQueryHandler"]
    assert callbacks[0].pattern.match(query.data)
    assert not callbacks[1].pattern.match(query.data)
