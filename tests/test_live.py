import json
from pathlib import Path

import numpy as np

from festival_finder.feedback import Feedback
from festival_finder.live import live_stats, possible_matches, read_snapshot
from festival_finder.projects import sample_id


def face(candidate=True, score=.8):
    return {'candidate': candidate, 'score': score, 'box': [1, 2, 3, 4]}


def photo(identifier, faces):
    return {'id': identifier, 'name': identifier + '.jpg', 'hits': [
        {'timestamp': None, 'score': .8, 'faces': faces, 'preview': ''}]}


def test_candidates_are_files_not_faces_and_do_not_become_confirmed():
    one = photo('one', [face(), face()])
    report = {'processed': 100, 'total_discovered': 418, 'threshold': .4,
              'matches': [one, photo('two', [face()]), photo('rejected', [face(False)]),
                          photo('no_faces', []), one]}
    result = live_stats(report, {})
    assert result['possible_files'] == 2
    assert result['confirmed_files'] == 0
    assert result['processed'] == 100 and result['total'] == 418
    labels = {sample_id(one, one['hits'][0], one['hits'][0]['faces'][0]): 'me'}
    assert live_stats(report, labels)['confirmed_files'] == 1
    assert live_stats(report, labels)['possible_files'] == 2
    labels[next(iter(labels))] = 'not_me'
    assert live_stats(report, labels)['confirmed_files'] == 0


def test_legacy_scores_and_incremental_candidate_arrival():
    report = {'threshold': .4, 'matches': []}
    assert possible_matches(report) == []
    item = photo('first', [{'score': .39}, {'score': .41}])
    report['matches'].append(item)
    assert len(possible_matches(report)) == 1
    report['matches'].append(photo('second', [face(False, .99)]))
    assert len(possible_matches(report)) == 1
    report['matches'].append(photo('third', [face()]))
    assert len(possible_matches(report)) == 2


def test_snapshot_viewer_is_read_only_and_shows_saved_progress(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from festival_finder import panel
    from festival_finder.progress_server import snapshot
    monkeypatch.setattr(panel, 'ensure_panel_server', lambda *args: 'http://127.0.0.1:8503/')
    bank = Feedback(tmp_path / 'feedback.sqlite3')
    item = photo('candidate', [face()])
    bank.set(sample_id(item, item['hits'][0], item['hits'][0]['faces'][0]),
             'me', np.eye(1, 128, dtype=np.float32)[0])
    path = tmp_path / 'last-report.json'
    report = {'selected_folder': 'Camera', 'processed': 100, 'total_discovered': 418,
              'finished': False, 'matches': [item], 'errors': []}
    path.write_text(json.dumps(report), encoding='utf-8')
    original_report, original_db = path.read_bytes(), bank.path.read_bytes()
    result, labels = read_snapshot(tmp_path)
    assert live_stats(result, labels)['possible_files'] == 1
    monkeypatch.setenv('FIND_MY_DANCE_DATA', str(tmp_path))
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'live_scan.py').run(timeout=20)
    assert not app.exception, app.exception
    assert app.get('iframe')[0].proto.src == 'http://127.0.0.1:8503/'
    values, _ = snapshot(tmp_path)
    assert values['processed'] == 100 and values['total'] == 418
    assert values['possible'] == 1
    assert values['confirmed'] == 1
    assert not app.button  # No actions that can restart or label in the live monitor.
    assert path.read_bytes() == original_report
    assert bank.path.read_bytes() == original_db
    report['processed'] = 101
    report['matches'].append(photo('second', [face()]))
    path.write_text(json.dumps(report), encoding='utf-8')
    # New values are available without rerunning the Streamlit page at all.
    values, _ = snapshot(tmp_path)
    assert values['processed'] == 101
    assert values['possible'] == 2
    assert values['confirmed'] == 1
