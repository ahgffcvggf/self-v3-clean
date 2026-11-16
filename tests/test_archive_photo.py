from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path
import pytest
from app.features import archive as a

@pytest.mark.asyncio
async def test_photo_download_has_valid_extension_and_failure_preserves_pending(tmp_path):
    message=NS(id=10,chat=NS(id=20),from_user=NS(id=30,first_name='A',last_name='',username=''),text='',caption='',poll=None,contact=None,location=None)
    paths=[]
    async def download(message,file_name):
        paths.append(Path(file_name)); Path(file_name).write_bytes(b'\xff\xd8\xfftest'); return file_name
    c=NS(me=NS(id=1),download_media=download,send_photo=AsyncMock(side_effect=OSError('offline')),send_message=AsyncMock())
    db=Mock()
    with patch.object(a,'PRIVATE_CACHE_DIR',str(tmp_path)),patch.dict(a.ANTI_DELETE_STATUS,{1:True}),patch.object(a,'_is_valid_pv_message',return_value=True),patch.object(a,'_detect_media_info',return_value=('عکس تایم‌دار',object(),8,True)),patch.object(a,'data_manager',db):
        await a.pv_archive_incoming_handler(c,message)
    assert paths[0].suffix=='.jpg'
    assert paths[0].exists()
    assert db.upsert_pv_cache.call_args.args[-1]=='PENDING'
    db.mark_archive_success.assert_not_called()
