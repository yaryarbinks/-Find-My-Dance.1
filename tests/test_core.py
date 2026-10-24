from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from festival_finder.drive import FOLDER, folder_id, list_media
from festival_finder.engine import cache_key, frames, normalize, scan_file


def test_folder_links():
    fid = '1CAT3tZLbqvIk7rtXb-j4sjbTXI3Mgmcv'
    assert folder_id(f'https://drive.google.com/drive/mobile/folders/{fid}?utm_source=ig') == fid
    assert folder_id(fid) == fid
    with pytest.raises(ValueError):
        folder_id(f'https://evil.example/folders/{fid}')


def test_recursive_pagination_and_deduplication():
    files = Mock()
    files.get.return_value.execute.return_value = {'id': 'rootfolder123', 'name': 'Festival', 'mimeType': FOLDER}
    files.list.return_value.execute.side_effect = [
        {'nextPageToken': 'page2', 'files': [{'id': 'nested', 'name': 'Camera', 'mimeType': FOLDER}]},
        {'files': [{'id': 'photo1', 'name': 'a.jpg', 'mimeType': 'image/jpeg'},
                   {'id': 'nested', 'name': 'Camera', 'mimeType': FOLDER}]},
        {'files': [{'id': 'photo1', 'name': 'a.jpg', 'mimeType': 'image/jpeg'},
                   {'id': 'video1', 'name': 'a.mp4', 'mimeType': 'video/mp4'},
                   {'id': 'doc1', 'name': 'note', 'mimeType': 'text/plain'}]},
    ]
    result = list_media(SimpleNamespace(files=lambda: files), ['rootfolder123', 'rootfolder123'])
    assert {item['id'] for item in result} == {'photo1', 'video1'}
    assert files.list.call_count == 3
    assert files.list.call_args_list[1].kwargs['pageToken'] == 'page2'


def test_normalization_and_cache_invalidation():
    refs = np.array([[1., 0.]])
    assert np.linalg.norm(normalize([3, 4])) == pytest.approx(1)
    with pytest.raises(ValueError):
        normalize([0, 0])
    base = cache_key({'id': 'a', 'modifiedTime': '1'}, refs, .4, 1)
    assert base != cache_key({'id': 'a', 'modifiedTime': '2'}, refs, .4, 1)
    assert base != cache_key({'id': 'a', 'modifiedTime': '1'}, refs, .3, 1)
    assert base != cache_key({'id': 'a', 'modifiedTime': '1'}, [[0., 1.]], .4, 1)


def test_video_sampling_and_preview(tmp_path):
    path = tmp_path / 'video.avi'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 64))
    assert writer.isOpened()
    for _ in range(30):
        writer.write(np.zeros((64, 64, 3), dtype=np.uint8))
    writer.release()
    sampled = list(frames(path, True, 1))
    assert [timestamp for timestamp, _ in sampled] == [0., 1., 2.]
    engine = SimpleNamespace(score_frame=lambda *args: [{'score': .9, 'box': [10, 10, 20, 20]}])
    hits = scan_file(engine, path, True, np.array([[1.]]), .4, 1, tmp_path / 'out')
    assert len(hits) == 3
    assert all(Path(hit['preview']).exists() for hit in hits)


def test_decode_error_is_not_silent(tmp_path):
    path = tmp_path / 'bad.jpg'
    path.write_bytes(b'not a photo')
    with pytest.raises(ValueError, match='unreadable'):
        list(frames(path, False, 1))


def test_report_save_retries_windows_sharing_violations(tmp_path, monkeypatch):
    from festival_finder.engine import save_report
    import json
    original = Path.replace
    attempts = []
    def flaky_replace(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError('Temporary file sharing violation')
        return original(source, destination)
    monkeypatch.setattr(Path, 'replace', flaky_replace)
    path = tmp_path / 'report.json'
    save_report(path, {'processed': 296})
    assert len(attempts) == 3
    assert json.loads(path.read_text()) == {'processed': 296}
    assert not list(tmp_path.glob('*.part'))
