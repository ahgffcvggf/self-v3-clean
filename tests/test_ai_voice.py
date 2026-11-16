import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from app.features import ai, diagnostics, identity, voice


class AIVoiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ai._rate_history.clear()
        ai._account_semaphores.clear()

    def _message(self, text, reply=None):
        return NS(
            text=text, id=10, chat=NS(id=20), reply_to_message=reply,
            edit_text=AsyncMock(), reply_text=AsyncMock(return_value=NS(id=99)),
            delete=AsyncMock(),
        )

    async def test_ai_input_bounds_do_not_call_provider(self):
        with patch.object(ai, "AI_API_KEY", "key"), patch.object(ai, "AI_API_URL", "https://example.test/v1"), patch.object(ai, "AI_MODEL", "model"), patch.object(ai.aiohttp, "ClientSession") as session:
            self.assertIsNone(await ai.get_ai_reply(""))
            self.assertIsNone(await ai.get_ai_reply("x" * (ai.MAX_AI_INPUT_CHARS + 1)))
        session.assert_not_called()

    async def test_ai_rate_limit_rejects_after_window_quota(self):
        with patch.object(ai, "AI_API_KEY", "key"), patch.object(ai, "AI_API_URL", "https://example.test/v1"), patch.object(ai, "AI_MODEL", "model"), patch.object(ai, "_extract_response", return_value="ok"), patch.object(ai.aiohttp, "ClientSession") as session:
            # Replace the network session with a provider-boundary fake.
            class FakeResponse:
                status = 200
                headers = {}
                async def text(self): return '{}'
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
            class FakeSession:
                async def __aenter__(self): return self
                async def __aexit__(self, *args): pass
                def post(self, *args, **kwargs): return FakeResponse()
            session.side_effect = lambda: FakeSession()
            results = [await ai.get_ai_reply("hello", account_id=7) for _ in range(ai.AI_MAX_REQUESTS_PER_WINDOW + 1)]
        self.assertEqual(results.count("ok"), ai.AI_MAX_REQUESTS_PER_WINDOW)
        self.assertIsNone(results[-1])

    async def test_ai_handler_sends_split_reply_and_persists_only_after_all_delivery(self):
        answer = "a" * (ai.TELEGRAM_TEXT_LIMIT + 10)
        sent = [NS(id=1), NS(id=2)]
        msg = self._message(".ربات hello")
        client = NS(me=NS(id=3), send_chat_action=AsyncMock())
        msg.reply_text.side_effect = sent
        with patch.dict(ai.AI_ASSISTANT_STATUS, {3: True}), patch.object(ai, "get_ai_reply", AsyncMock(return_value=answer)), patch.object(ai, "data_manager", Mock()) as db:
            await ai.ai_robot_command_handler(client, msg)
        self.assertEqual([call.args[0] for call in msg.reply_text.await_args_list], ["a" * 4096, "a" * 10])
        self.assertEqual(db.save_chat_message.call_count, 2)
        self.assertEqual(db.save_chat_message.call_args_list[0].args[-1], "hello")

    async def test_ai_handler_does_not_persist_when_a_split_send_fails(self):
        answer = "a" * (ai.TELEGRAM_TEXT_LIMIT + 10)
        msg = self._message(".ربات hello")
        msg.reply_text.side_effect = [NS(id=1), None]
        client = NS(me=NS(id=3), send_chat_action=AsyncMock())
        with patch.dict(ai.AI_ASSISTANT_STATUS, {3: True}), patch.object(ai, "get_ai_reply", AsyncMock(return_value=answer)), patch.object(ai, "data_manager", Mock()) as db:
            await ai.ai_robot_command_handler(client, msg)
        db.save_chat_message.assert_not_called()

    async def test_voice_input_bounds_and_upload_failure_keep_command(self):
        client = NS(me=NS(id=4), send_chat_action=AsyncMock(), send_voice=AsyncMock(return_value=None))
        for text in (".ویس", ".ویس " + "x" * (voice.MAX_TTS_CHARS + 1)):
            msg = self._message(text)
            await voice.voice_command_handler(client, msg)
            self.assertTrue(msg.edit_text.called or msg.reply_text.called)
            msg.edit_text.reset_mock(); msg.reply_text.reset_mock()
        msg = self._message(".ویس hello")
        with patch.object(voice, "_synthesize_ogg_voice", AsyncMock()):
            await voice.voice_command_handler(client, msg)
        msg.delete.assert_not_awaited()
        msg.reply_text.assert_awaited_once()

    async def test_voice_ffmpeg_timeout_kills_and_waits_for_process(self):
        proc = NS(returncode=None, kill=Mock(), communicate=AsyncMock(side_effect=asyncio.TimeoutError()))
        await voice._stop_process(proc)
        proc.kill.assert_called_once()
        proc.communicate.assert_awaited_once()

    async def test_diagnostics_and_identity_escape_untrusted_values(self):
        self.assertEqual(diagnostics._format_uptime(90061), "1 روز و 1 ساعت و 1 دقیقه و 1 ثانیه")
        user = NS(first_name="<x>", last_name='"y"', username="u", id=8)
        msg = self._message(".id", reply=NS(from_user=user, sender_chat=None))
        await identity.id_command_handler(NS(), msg)
        rendered = msg.edit_text.call_args.args[0]
        self.assertIn("&lt;x&gt;", rendered)
        self.assertNotIn("<x>", rendered)


if __name__ == "__main__":
    unittest.main()
