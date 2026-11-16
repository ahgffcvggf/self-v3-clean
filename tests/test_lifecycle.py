import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import state
from app.manager import bot as manager


class FakeClient:
    def __init__(self):
        self.stop = AsyncMock()
        self.disconnect = AsyncMock()


@pytest.mark.asyncio
async def test_stop_active_bot_cancels_all_runtime_tasks_and_stops_client():
    user_id = 7
    first = asyncio.create_task(asyncio.sleep(60))
    second = asyncio.create_task(asyncio.sleep(60))
    state.ACTIVE_BOTS[user_id] = (FakeClient(), [first])
    state.BIO_UPDATE_TASKS[user_id] = second

    await manager.stop_active_bot(user_id)

    assert first.cancelled()
    assert second.cancelled()
    assert user_id not in state.ACTIVE_BOTS
    assert user_id not in state.BIO_UPDATE_TASKS


@pytest.mark.asyncio
async def test_finalize_login_awaits_start_before_success(monkeypatch):
    events = []
    client = SimpleNamespace(
        export_session_string=AsyncMock(return_value="session"),
        get_me=AsyncMock(return_value=SimpleNamespace(id=42, first_name="A", username="a")),
        disconnect=AsyncMock(),
    )
    message = SimpleNamespace(chat=SimpleNamespace(id=99), reply_text=AsyncMock())
    manager.LOGIN_STATES[99] = {"client": client}
    monkeypatch.setattr(manager.data_manager, "save_session", lambda *args: events.append("saved"))

    async def start(*args):
        events.append("started")

    await manager._finalize_login(message, client, "+1", start)

    assert events == ["saved", "started"]
    message.reply_text.assert_awaited_once()
    assert 99 not in manager.LOGIN_STATES


def test_onboarding_fails_closed_without_allowlist(monkeypatch):
    monkeypatch.setattr(manager, "GOD_ADMIN_IDS", [])
    monkeypatch.setattr(manager, "ALLOWED_USER_IDS", [])
    assert manager.is_onboarding_allowed(1) is False


def test_onboarding_accepts_configured_user(monkeypatch):
    monkeypatch.setattr(manager, "GOD_ADMIN_IDS", [])
    monkeypatch.setattr(manager, "ALLOWED_USER_IDS", [11])
    assert manager.is_onboarding_allowed(11) is True


@pytest.mark.asyncio
async def test_cleanup_loop_invokes_cache_limit_enforcement():
    called = asyncio.Event()

    class Data:
        def enforce_cache_limits(self):
            called.set()

    task = asyncio.create_task(manager.cache_cleanup_loop(Data(), interval=0))
    await asyncio.wait_for(called.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
