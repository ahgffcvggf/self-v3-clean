import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import pytest

@pytest.mark.asyncio
async def test_start_failure_propagates_and_disconnects():
    bot = importlib.import_module('bot')
    fake = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError('no connection')), disconnect=AsyncMock(), is_connected=True)
    with patch.object(bot, 'Client', return_value=fake):
        with pytest.raises(RuntimeError):
            await bot.start_bot_instance('session', 'phone', 111)
    fake.disconnect.assert_awaited_once()

@pytest.mark.asyncio
async def test_start_rejects_identity_mismatch():
    bot = importlib.import_module('bot')
    fake = SimpleNamespace(start=AsyncMock(), get_me=AsyncMock(return_value=SimpleNamespace(id=222)), disconnect=AsyncMock(), stop=AsyncMock(), is_connected=True)
    with patch.object(bot, 'Client', return_value=fake):
        with pytest.raises(ValueError, match='identity'):
            await bot.start_bot_instance('session', 'phone', 111)

@pytest.mark.asyncio
async def test_finalization_failure_never_announces_success(monkeypatch):
    from app.manager import bot as manager
    user = SimpleNamespace(export_session_string=AsyncMock(return_value='session'), get_me=AsyncMock(return_value=SimpleNamespace(id=1,first_name='A',username='')), disconnect=AsyncMock(), is_connected=True)
    message = SimpleNamespace(chat=SimpleNamespace(id=1), reply_text=AsyncMock())
    monkeypatch.setattr(manager.data_manager, 'save_session', Mock())
    with pytest.raises(RuntimeError):
        await manager._finalize_login(message, user, '+1', AsyncMock(side_effect=RuntimeError('start failed')))
    message.reply_text.assert_not_awaited()

@pytest.mark.asyncio
async def test_main_starts_manager_before_accounts_and_cleans_up(monkeypatch):
    import bot
    events = []
    manager = SimpleNamespace(start=AsyncMock(side_effect=lambda: events.append('manager')), stop=AsyncMock(), is_connected=True)
    monkeypatch.setattr(bot, 'API_ID', 1)
    monkeypatch.setattr(bot, 'API_HASH', 'test')
    monkeypatch.setattr(bot, 'BOT_TOKEN', 'test')
    monkeypatch.setattr(bot, 'create_manager_bot', lambda: manager)
    monkeypatch.setattr(bot, 'register_manager_handlers', Mock())
    monkeypatch.setattr(bot, 'load_all_states', Mock())
    monkeypatch.setattr(bot.data_manager, 'get_all_sessions', lambda: [('phone', {'string':'session','user_id':1})])
    monkeypatch.setattr(bot, 'start_bot_instance', AsyncMock(side_effect=lambda *args: events.append('account')))
    monkeypatch.setattr(bot, 'idle', AsyncMock())
    await bot.main()
    assert events == ['manager', 'account']
    manager.stop.assert_awaited_once()
