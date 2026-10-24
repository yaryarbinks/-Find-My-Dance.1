from types import SimpleNamespace
from unittest.mock import Mock
from pathlib import Path

import cv2
import numpy as np
import pytest

from festival_finder import drive
from festival_finder.feedback import Feedback, candidate_score


def vector(index=0):
    result = np.zeros(128, dtype=np.float32)
    result[index] = 1
    return result


def test_feedback_persists_corrects_and_undoes(tmp_path):
    path = tmp_path / 'feedback.sqlite3'
    bank = Feedback(path)
    bank.set('face1', 'me', vector())
    assert Feedback(path).labels() == {'face1': 'me'}
    assert bank.examples('me').shape == (1, 128)
    bank.set('face1', 'not_me', vector())
    assert bank.examples('me').shape == (0, 128)
    assert bank.examples('not_me').shape == (1, 128)
    bank.undo('face1')
    assert bank.labels() == {}
    with pytest.raises(ValueError):
        bank.set('face2', 'me', [0, 0])


def test_negative_examples_veto_similar_false_matches():
    query = vector()
    reference = vector() * .6 + vector(1) * .8
    assert candidate_score(query, reference.reshape(1, -1), None, .4)[1]
    assert not candidate_score(query, reference.reshape(1, -1), query.reshape(1, -1), .4)[1]
    # A confirmed exact positive is not vetoed by a weaker negative.
    assert candidate_score(query, query.reshape(1, -1), reference.reshape(1, -1), .4)[1]


def test_reference_photos_survive_restart_and_deduplicate(tmp_path):
    path = tmp_path / 'feedback.sqlite3'
    bank = Feedback(path)
    identifier = bank.save_reference('me.jpg', b'original image bytes', b'face crop bytes', vector())
    bank.save_reference('me-again.jpg', b'original image bytes', b'face crop bytes', vector())
    restored = Feedback(path)
    assert len(restored.references()) == 1
    assert restored.references()[0]['crop'] == b'face crop bytes'
    assert np.array_equal(restored.reference_examples(), vector().reshape(1, -1))
    with restored.connection() as db:
        assert db.execute('SELECT original FROM reference_photos').fetchone()[0] == b'original image bytes'
    restored.remove_reference(identifier)
    assert Feedback(path).references() == []
    assert restored.reference_examples().shape == (0, 128)


def test_thumbnail_never_requests_original():
    files = Mock()
    files.get.return_value.execute.return_value = {'thumbnailLink': 'https://lh3.googleusercontent.com/preview'}
    http = Mock()
    http.request.return_value = (type('Response', (dict,), {'status': 200})({'content-type': 'image/jpeg'}), b'preview')
    service = SimpleNamespace(files=lambda: files, _http=http)
    assert drive.thumbnail(service, {'id': 'test'}) == b'preview'
    files.get_media.assert_not_called()


def test_thumbnail_retries_google_rate_limit_without_original(tmp_path, monkeypatch):
    files, http = Mock(), Mock()
    files.get.return_value.execute.return_value = {'thumbnailLink': 'https://lh3.googleusercontent.com/preview'}
    response = lambda status: type('Response', (dict,), {'status': status})({'content-type': 'image/jpeg'})
    http.request.side_effect = [(response(429), b''), (response(200), b'preview')]
    monkeypatch.setattr(drive.time, 'sleep', Mock())
    assert drive.thumbnail(SimpleNamespace(files=lambda: files, _http=http), {'id': 'test'}) == b'preview'
    assert http.request.call_count == 2
    files.get_media.assert_not_called()
    files.get.return_value.execute.return_value = {}
    with pytest.raises(ValueError, match='no original|No accessible'):
        drive.thumbnail(SimpleNamespace(files=lambda: files, _http=http), {'id': 'test'})
    files.get_media.assert_not_called()


def test_gallery_review_and_no_original_download(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from festival_finder import engine, feedback, jobs, panel
    from festival_finder.projects import Projects
    import json
    monkeypatch.setattr(panel, 'ensure_panel_server', lambda *args: 'http://127.0.0.1:8503/')

    bank = Feedback(tmp_path / 'feedback.sqlite3')
    saved_crop = cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes()
    bank.save_reference('saved-me.jpg', saved_crop, saved_crop, vector())
    monkeypatch.setattr(feedback, 'Feedback', lambda path: bank)
    fake_engine = SimpleNamespace(faces=lambda image: [(np.array([0, 0, 32, 32]), vector(), image)])
    monkeypatch.setattr(engine, 'FaceEngine', lambda path: fake_engine)
    monkeypatch.setattr(drive, 'connect', lambda *args: object())
    monkeypatch.setattr(drive, 'browse_folder', lambda *args: ({'id': 'festivalfolder123', 'name': 'Festival'}, [], None))
    recursive = Mock(side_effect=AssertionError('Recursive discovery is forbidden'))
    monkeypatch.setattr(drive, 'list_media', recursive)
    monkeypatch.setattr(drive, 'media_batch', lambda *args: ([
        {'id': f'test_file_id{index}', 'name': f'Test photo {index}', 'mimeType': 'image/jpeg',
         'folder': 'Festival', 'webViewLink': 'https://drive.google.com/file/d/test_file_id123/view',
         'modifiedTime': str(tmp_path), 'size': '99999999'} for index in range(30)], None))
    raw = cv2.imencode('.jpg', np.zeros((64, 64, 3), dtype=np.uint8))[1].tobytes()
    monkeypatch.setattr(drive, 'thumbnail', lambda *args: raw)
    original = Mock(side_effect=AssertionError('Original download is forbidden'))
    monkeypatch.setattr(drive, 'download', original)
    monkeypatch.setenv('FIND_MY_DANCE_DATA', str(tmp_path / 'app-data'))
    def finish_fake_job(root, data, config):
        # Exercise the gallery with a completed worker result; never launch a real OAuth worker.
        data = Path(data)
        directory = data / 'jobs' / 'test'
        directory.mkdir(parents=True, exist_ok=True)
        matches = []
        matrix = np.asarray(config['references'], dtype=np.float32)
        negatives = np.asarray(config['negatives'], dtype=np.float32).reshape(-1, 128)
        for item in config['items']:
            hits = engine.scan_preview(fake_engine, raw, matrix, negatives, .4, directory / item['id'])
            matches.append({**item, 'url': item['webViewLink'], 'local_path': '', 'video': False,
                            'review_key': item['id'], 'hits': hits})
        report = {'preview_only': True, 'preview_bytes': 0, 'processed': len(matches), 'total_discovered': len(matches),
                  'limit': len(matches), 'finished': True, 'errors': [], 'skipped': [], 'matches': matches,
                  'reference_count': len(matrix), 'threshold': .4, 'interval': 1.,
                  'selected_folder': 'Festival', 'scan_scope': 'whole_selected_folder'}
        Projects(bank.path).archive(config['festival_id'], config['folder_id'], report)
        (directory / 'report.json').write_text(json.dumps(report))
        return {'status': 'finished', 'directory': str(directory)}
    monkeypatch.setattr(jobs, 'start_job', finish_fake_job)
    monkeypatch.setattr(jobs, 'current_job', lambda data: None)
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py').run(timeout=20)
    next(b for b in app.button if b.label == 'Open festival folder').click().run(timeout=20)
    next(b for b in app.button if b.label == 'Find my photos and videos').click().run(timeout=20)
    assert not app.exception, app.exception
    assert app.session_state['report']['preview_only'] is True
    assert app.session_state['report']['processed'] == 30
    assert app.session_state['report']['finished'] is True
    rescan = Mock(side_effect=AssertionError('A completed folder must open saved results instead of rescanning'))
    monkeypatch.setattr(drive, 'folder_media', rescan)
    next(b for b in app.button if b.label == 'Find my photos and videos').click().run(timeout=20)
    assert not app.exception, app.exception
    assert app.session_state['report']['processed'] == 30
    rescan.assert_not_called()
    next(b for b in app.button if b.label == "That's me").click().run(timeout=20)
    assert not app.exception, app.exception
    assert len(bank.labels()) == 1
    next(b for b in app.button if b.label == 'Not me').click().run(timeout=20)
    assert len(bank.examples('not_me')) == 1
    assert next(metric for metric in app.metric if metric.label == 'Confirmed: not me').value == '1'
    assert next(metric for metric in app.metric if metric.label == 'Confirmed: me').value == '0'
    assert next(metric for metric in app.metric if metric.label == 'Saved reference photos').value == '1'
    next(b for b in app.button if b.label == 'Undo').click().run(timeout=20)
    assert bank.labels() == {}
    assert next(metric for metric in app.metric if metric.label == 'Confirmed: not me').value == '0'
    original.assert_not_called()
    recursive.assert_not_called()


def test_folder_browser_and_batch_do_not_recurse():
    files = Mock()
    files.get.return_value.execute.return_value = {'id': 'festivalfolder123', 'name': 'Festival', 'mimeType': drive.FOLDER}
    files.list.return_value.execute.side_effect = [
        {'files': [{'id': 'dayfolder123', 'name': 'Friday'}], 'nextPageToken': 'more-folders'},
        {'files': [{'id': 'photo123', 'name': 'Photo', 'mimeType': 'image/jpeg'}], 'nextPageToken': 'next-batch'}]
    service = SimpleNamespace(files=lambda: files)
    _, children, token = drive.browse_folder(service, 'festivalfolder123')
    assert children[0]['name'] == 'Friday' and token == 'more-folders'
    items, token = drive.media_batch(service, 'dayfolder123', 25, 'previous-batch', 'Festival / Friday')
    assert token == 'next-batch' and items[0]['folder'] == 'Festival / Friday'
    assert files.list.call_count == 2
    call = files.list.call_args.kwargs
    assert call['pageSize'] == 25 and call['pageToken'] == 'previous-batch'
    assert "'dayfolder123' in parents" in call['q']
    with pytest.raises(ValueError):
        drive.media_batch(service, 'dayfolder123', 1000)


def test_whole_folder_follows_all_pages_without_descendants(monkeypatch):
    page = Mock(side_effect=[
        ([{'id': str(i)} for i in range(100)], 'page2'),
        ([{'id': '100'}, {'id': '0'}], None)])
    monkeypatch.setattr(drive, 'media_batch', page)
    items = drive.folder_media(object(), 'camerafolder123', 'Thursday / BOB')
    assert len(items) == 101
    assert page.call_count == 2
    assert all(call.args[1] == 'camerafolder123' for call in page.call_args_list)
    assert page.call_args_list[1].args[3] == 'page2'
