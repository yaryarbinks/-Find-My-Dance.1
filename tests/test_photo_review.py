from festival_finder.feedback import Feedback
from festival_finder.projects import Projects
from festival_finder.photo_review import nearby_photos, nearby_review_rows
from festival_finder.tree import folder_tree_html


def test_manual_photo_labels_persist_without_face_examples(tmp_path):
    path = tmp_path / 'feedback.sqlite3'
    feedback = Feedback(path)
    projects = Projects(path)
    projects.save_folders('festival', [{'id': 'bob', 'parent': None, 'name': 'BOB', 'path': 'BOB'}])
    report = {'matches': [{'id': 'back-view', 'hits': [{'timestamp': None, 'faces': []}]}],
              'total_discovered': 1, 'processed': 1, 'errors': [], 'finished': True}
    projects.archive('festival', 'bob', report)
    projects.review_photo('festival', 'bob', 'back-view', 'me')
    reopened = Projects(path)
    assert len(reopened.confirmed(report, feedback.labels())) == 1
    assert reopened.checklist('festival')[0]['confirmed_photos'] == 1
    assert feedback.labels() == {}
    assert reopened.photo_labels('another-festival', 'bob') == {}
    projects.review_photo('festival', 'bob', 'back-view', 'not_me')
    assert projects.confirmed(report, {}) == []
    projects.review_photo('festival', 'bob', 'back-view', None)
    assert projects.photo_labels('festival', 'bob') == {}


def test_neighbors_stay_within_report_skip_videos_and_deduplicate():
    photos = [{'id': str(i), 'name': f'photo{i}.jpg'} for i in range(1, 12)]
    report = {'matches': list(reversed(photos)) + [{'id': 'video', 'name': 'photo6.mp4', 'video': True}]}
    rows = nearby_photos(report, [photos[4], photos[6]])
    assert {row['item']['id'] for row in rows} == {'3', '4', '6', '8', '9'}
    assert len(next(row for row in rows if row['item']['id'] == '6')['near']) == 2
    assert {row['item']['id'] for row in nearby_photos(report, [photos[0]])} == {'2', '3'}


def test_tree_collapses_branches_but_retains_progress():
    rows = [{'id': str(i), 'parent': str(i-1) if i else None, 'name': str(i),
             'status': 'Completed', 'files_checked': 7, 'files_total': 7, 'confirmed_photos': 2} for i in range(3)]
    html = folder_tree_html('festival', rows)
    assert html.count('<details open>') == 1
    assert html.count('<details>') == 1
    assert '7 / 7 checked · 2 confirmed photos' in html
    assert folder_tree_html('festival', rows, '2').count('<details open>') == 2


def test_reviewed_neighbor_remains_visible_as_an_anchor():
    photos = [{'id': str(i), 'name': f'{i}.jpg'} for i in range(6)]
    report = {'matches': photos}
    rows = nearby_review_rows(report, [photos[2], photos[3]], {'3': 'me', '0': 'not_me'})
    assert [row['item']['id'] for row in rows] == ['0', '1', '3', '4', '5']


def test_review_buttons_show_saved_state_and_compact_rejection(tmp_path):
    from streamlit.testing.v1 import AppTest

    database = tmp_path / 'feedback.sqlite3'
    Feedback(database)
    projects = Projects(database)
    projects.register({'id': 'festival', 'name': 'Test festival'})
    projects.save_folders('festival', [{'id': 'bob', 'parent': None, 'name': 'BOB', 'path': 'BOB'}])
    report = {'matches': [{'id': str(i), 'name': f'{i}.jpg', 'hits': [], 'url': ''} for i in range(4)],
              'total_discovered': 4, 'processed': 4, 'errors': [], 'finished': True}
    projects.archive('festival', 'bob', report)
    projects.review_photo('festival', 'bob', '2', 'me')
    script = f'''
from pathlib import Path
import streamlit as st
from festival_finder.feedback import Feedback
from festival_finder.projects import Projects
from festival_finder.photo_review import render_photo_page
data = Path({str(tmp_path)!r})
feedback = Feedback(data / 'feedback.sqlite3')
render_photo_page(st, Projects(feedback.path), feedback, data, data, 'Nearby photos')
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    prefix = 'photo-Nearby photos-festival-bob-0'
    app.button(key=f'{prefix}-me').click().run()
    assert not app.exception
    assert app.button(key=f'{prefix}-me').label == '✓ Confirmed'
    assert app.button(key=f'{prefix}-me').disabled
    assert any('Saved: 0.jpg' in notice.value for notice in app.success)
    assert projects.photo_labels('festival', 'bob')['0'] == 'me'
    app.button(key=f'{prefix}-not_me').click().run()
    assert not app.exception
    assert any(expander.label == 'Reopen rejected photo' for expander in app.expander)
    assert any('Saved: not in this photo' in caption.value for caption in app.caption)
    assert not any(button.key == f'{prefix}-me' for button in app.button)
    app.button(key=f'{prefix}-compact-undo').click().run()
    assert not app.exception
    assert '0' not in projects.photo_labels('festival', 'bob')
    assert not app.button(key=f'{prefix}-me').disabled
