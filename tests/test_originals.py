from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest

from festival_finder import drive
from festival_finder.originals import load_original, build_zip


def test_original_loading_respects_permissions_and_reuses_local_copy(tmp_path, monkeypatch):
    files = Mock()
    metadata = {'id': 'photo1', 'name': 'Photo.jpg', 'mimeType': 'image/jpeg', 'modifiedTime': 'v1', 'capabilities': {'canDownload': True}}
    files.get.return_value.execute.return_value = metadata
    service = SimpleNamespace(files=lambda: files)
    def download(service, item, directory):
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'photo1.jpg'
        path.write_bytes(b'original bytes')
        return path
    request = Mock(side_effect=download)
    monkeypatch.setattr(drive, 'download', request)
    path, _ = load_original(service, metadata, tmp_path)
    assert path.read_bytes() == b'original bytes'
    load_original(service, metadata, tmp_path)
    assert request.call_count == 1
    metadata['capabilities']['canDownload'] = False
    with pytest.raises(ValueError, match='disabled'):
        load_original(service, metadata, tmp_path)
    assert request.call_count == 1


def test_zip_includes_only_requested_confirmed_photos(tmp_path, monkeypatch):
    from festival_finder import originals
    source = tmp_path / 'photo.jpg'
    source.write_bytes(b'original photo')
    request = Mock(return_value=(source, '../unsafe/name.jpg'))
    monkeypatch.setattr(originals, 'load_original', request)
    items = [{'id': 'confirmed1', 'name': 'One'}]
    path, errors = build_zip(object(), items, tmp_path / 'exports')
    assert not errors
    with zipfile.ZipFile(path) as archive:
        assert archive.namelist() == ['confirmed1-name.jpg']
        assert archive.read(archive.namelist()[0]) == b'original photo'
    assert request.call_count == 1
