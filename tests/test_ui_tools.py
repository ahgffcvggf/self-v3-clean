import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from pyrogram import ContinuePropagation
from app.features import tools, clock, activity
from app.ui import panel
from app import config


def message(text):
    return NS(text=text, id=4, chat=NS(id=9), reply_to_message=NS(from_user=NS(id=2), copy=AsyncMock()), edit_text=AsyncMock(), delete=AsyncMock())


class UIToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_without_reply_is_bounded_and_own_only(self):
        async def history(*args, **kwargs):
            yield NS(id=3, from_user=NS(is_self=True))
            yield NS(id=2, from_user=NS(is_self=False))
        c = NS(me=NS(id=1), get_chat_history=Mock(side_effect=history), delete_messages=AsyncMock())
        m = message('حذف 2'); m.reply_to_message = None
        await tools.reply_based_controller(c, m)
        c.get_chat_history.assert_called_once_with(9, limit=2, offset_id=4)
        c.delete_messages.assert_awaited_once_with(9, [3])
        m.delete.assert_awaited_once()

    async def test_unknown_reply_propagates(self):
        with self.assertRaises(ContinuePropagation):
            await tools.reply_based_controller(NS(me=NS(id=1)), message('.ویس hello'))

    async def test_invalid_counts_report_error_without_operations(self):
        for command in ['حذف 0', 'حذف -1', 'حذف 1001', 'تکرار 0', 'تکرار 21', 'تکرار bad']:
            m = message(command)
            c = NS(me=NS(id=1), get_chat_history=Mock())
            await tools.reply_based_controller(c, m)
            c.get_chat_history.assert_not_called()
            m.reply_to_message.copy.assert_not_called()
            m.delete.assert_not_called()
            self.assertTrue(m.edit_text.called, command)

    async def test_clock_restores_exact_numeric_surname(self):
        c = NS(me=NS(id=91), get_me=AsyncMock(return_value=NS(last_name='Family 123')), update_profile=AsyncMock())
        clock.CLOCK_STATUS[91] = True
        with patch.object(clock, 'data_manager', Mock()):
            await clock.perform_clock_update_now(c, 91)
            c.get_me.return_value.last_name = c.update_profile.call_args.kwargs['last_name']
            await clock.lastname_time_toggle_handler(c, message('ساعت خاموش'))
        self.assertEqual(c.update_profile.call_args.kwargs['last_name'], 'Family 123')

    async def test_ai_panel_is_not_live_connection_claim(self):
        with patch.object(panel, 'AI_API_KEY', 'test'):
            text, _ = panel.generate_panel_view(1, 'ai')
        self.assertNotIn('متصل', text)

    async def test_unknown_panel_values_are_safe(self):
        panel.BIO_DATE_FORMAT[1] = 'invalid'
        panel.USER_FONT_CHOICES[1] = 'invalid'
        self.assertIsNotNone(panel.generate_category_menu(1, 'time'))

    async def test_no_document_advertising(self):
        self.assertNotIn('ساخت ورد', str(panel.HELP_SECTIONS))
        self.assertNotIn('ساخت پی دی اف', config.COMMAND_REGEX)

    async def test_tehran_today(self):
        m = message('تاریخ امروز')
        with patch.object(tools, 'datetime') as dt:
            dt.now.return_value.strftime.return_value = 'today'
            await tools.send_gregorian_date_handler(None, m)
            dt.now.assert_called_once_with(config.TEHRAN_TIMEZONE)

    async def test_discussion_raw_peer_is_not_positive_user_id(self):
        from pyrogram.raw.types import PeerChannel
        c = NS(me=NS(id=96), resolve_peer=AsyncMock(), invoke=AsyncMock(return_value=NS(messages=[NS(id=7, peer_id=PeerChannel(channel_id=123))])), get_chat=AsyncMock(return_value=NS(id=-1000000000123)), send_message=AsyncMock())
        tools.COMMENT_MODE_STATUS[96] = True
        m = message('post'); m.chat.type = tools.ChatType.CHANNEL
        await tools.auto_comment_handler(c, m)
        c.send_message.assert_awaited_once_with(-1000000000123, tools.COMMENT_TEXT.get(96, 'کامنت تنظیم نشده'), reply_to_message_id=7)
        c.get_chat.assert_not_called()

    async def test_discussion_uses_high_level_chat_id(self):
        c = NS(me=NS(id=1), get_discussion_message=AsyncMock(return_value=NS(id=7, chat=NS(id=-100123))), send_message=AsyncMock())
        tools.COMMENT_MODE_STATUS[1] = True
        m = message('post'); m.chat.type = tools.ChatType.CHANNEL
        await tools.auto_comment_handler(c, m)
        self.assertEqual(c.send_message.call_args.args[0], -100123)

    async def test_panel_clock_off_restores_surname(self):
        manager = Mock()
        handlers = {}
        manager.on_inline_query.return_value = lambda fn: fn
        manager.on_callback_query.return_value = lambda fn: handlers.setdefault('callback', fn)
        panel.register_manager_panel_handlers(manager)
        c = NS(get_me=AsyncMock(return_value=NS(last_name='Name 12:34')), update_profile=AsyncMock())
        panel.ACTIVE_BOTS[92] = (c, [])
        panel.CLOCK_STATUS[92] = True
        clock._CLOCK_ORIGINAL_LASTNAMES[92] = 'Name'
        cb = NS(data='toggle_clock_92', from_user=NS(id=92), edit_message_text=AsyncMock(), answer=AsyncMock())
        with patch.object(panel, 'data_manager', Mock()):
            await handlers['callback'](None, cb)
        c.update_profile.assert_awaited_once_with(last_name='Name')
        cb.data = 'cycle_dateformat_92'
        panel.BIO_DATE_FORMAT[92] = 'broken'
        with patch.object(panel, 'data_manager', Mock()):
            await handlers['callback'](None, cb)
        self.assertIn(panel.BIO_DATE_FORMAT[92], ['jalali', 'gregorian', None])

    async def test_copy_profile_backup_survives_repeat_and_restore_without_reply(self):
        tools.ORIGINAL_PROFILE_DATA.pop(94, None)
        tools.COPY_MODE_STATUS.pop(94, None)
        own = NS(first_name='Original', last_name='Surname', bio='Original bio')
        other = NS(first_name='Other', last_name='Other surname', bio='Other bio')
        c = NS(me=NS(id=94), get_chat=AsyncMock(side_effect=lambda who: own if who == 'me' else other), update_profile=AsyncMock())
        with patch.object(tools, 'data_manager', Mock()):
            await tools.reply_based_controller(c, message('کپی روشن'))
            own.first_name = 'Other'
            await tools.reply_based_controller(c, message('کپی روشن'))
            self.assertEqual(tools.ORIGINAL_PROFILE_DATA[94]['first_name'], 'Original')
            m = message('کپی خاموش'); m.reply_to_message = None
            await tools.reply_based_controller(c, m)
        self.assertEqual(c.update_profile.call_args.kwargs, {'first_name': 'Original', 'last_name': 'Surname', 'bio': 'Original bio'})
        self.assertFalse(tools.COPY_MODE_STATUS[94])

    async def test_copy_failure_does_not_claim_success_or_enable_mode(self):
        tools.ORIGINAL_PROFILE_DATA.pop(95, None)
        tools.COPY_MODE_STATUS.pop(95, None)
        c = NS(me=NS(id=95), get_chat=AsyncMock(return_value=NS(first_name='Name', last_name='', bio='')), update_profile=AsyncMock(side_effect=RuntimeError('unavailable')))
        m = message('کپی روشن')
        with patch.object(tools, 'data_manager', Mock()):
            await tools.reply_based_controller(c, m)
        self.assertFalse(tools.COPY_MODE_STATUS.get(95, False))
        self.assertIn('❌', m.edit_text.call_args.args[0])

    async def test_activity_command_targets_current_chat_only(self):
        m = message('تایپینگ روشن')
        with patch.object(activity, 'data_manager', Mock()):
            await activity.activity_mode_toggle_handler(NS(me=NS(id=93)), m)
        self.assertEqual(list(activity.ACTIVITY_CHAT_TARGETS[93]), [9])

    async def test_activity_never_enumerates_other_chats(self):
        c = NS(get_dialogs=Mock())
        activity.ACTIVE_BOTS[99] = (c, [])
        activity.TYPING_MODE_STATUS[99] = True
        async def stop(*args):
            activity.ACTIVE_BOTS.pop(99, None)
        with patch.object(activity.asyncio, 'sleep', stop):
            await activity.status_action_task(c, 99)
        c.get_dialogs.assert_not_called()
