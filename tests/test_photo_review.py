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


def test_confirmed_neighbors_expand_review_but_rejected_neighbors_do_not():
    photos = [{'id': str(i), 'name': f'{i}.jpg'} for i in range(13)]
    report = {'matches': photos}

    first_review = nearby_review_rows(report, [photos[4]], {})
    assert {row['item']['id'] for row in first_review} == {'2', '3', '5', '6'}

    expanded_review = nearby_review_rows(report, [photos[4], photos[6]], {'6': 'me'})
    assert {row['item']['id'] for row in expanded_review} == {'2', '3', '5', '6', '7', '8'}

    after_rejection = nearby_review_rows(
        report, [photos[4], photos[6]], {'6': 'me', '8': 'not_me'})
    assert {row['item']['id'] for row in after_rejection} == {'2', '3', '5', '6', '7', '8'}
    assert not {'9', '10'} & {row['item']['id'] for row in after_rejection}


def test_folder_review_defaults_to_all_scanned_folders_and_can_filter(tmp_path):
    from streamlit.testing.v1 import AppTest

    database = tmp_path / 'feedback.sqlite3'
    feedback = Feedback(database)
    projects = Projects(database)
    projects.register({'id': 'festival', 'name': 'Test festival'})
    projects.save_folders('festival', [
        {'id': 'festival', 'parent': None, 'name': 'Festival', 'path': 'Festival'},
        {'id': 'folder-a', 'parent': 'festival', 'name': 'Folder A', 'path': 'Festival / Folder A'},
        {'id': 'folder-b', 'parent': 'festival', 'name': 'Folder B', 'path': 'Festival / Folder B'},
    ])
    for folder, photo, video in [
        ('folder-a', {'id': 'photo-a', 'name': 'photo-a.jpg',
                      'hits': [{'timestamp': None, 'faces': [
                          {'candidate': True, 'score': 0.71, 'box': [0, 0, 10, 10]}]}]}, None),
        ('folder-b', {'id': 'photo-b', 'name': 'photo-b.jpg',
                      'hits': [{'timestamp': None, 'faces': [
                          {'candidate': False, 'score': 0.35, 'box': [0, 0, 10, 10]}]}]},
         {'id': 'video-b', 'name': 'video-b.mp4', 'video': True, 'hits': []}),
    ]:
        items = [photo] + ([video] if video else [])
        projects.archive('festival', folder, {
            'matches': items, 'processed': len(items), 'total_discovered': len(items),
            'errors': [], 'finished': True,
        })
    script = f'''
from pathlib import Path
import streamlit as st
from festival_finder.feedback import Feedback
from festival_finder.projects import Projects
from festival_finder.photo_review import render_photo_page
data = Path({str(tmp_path)!r})
feedback = Feedback(data / 'feedback.sqlite3')
render_photo_page(st, Projects(feedback.path), feedback, data, data, 'Folder review')
'''
    app = AppTest.from_string(script).run()

    assert not app.exception
    assert app.multiselect(key='review-folders').value == ['folder-a', 'folder-b']
    assert app.radio(key='folder-review-view-v2').value == 'Saved suggestions'
    assert {item.value for item in app.subheader} == {'photo-a.jpg'}
    assert any('1 recognition suggestions' in item.value for item in app.caption)
    assert any('similarity 0.71 (not a probability)' in item.value for item in app.caption)
    assert any('1 item(s) in this view · 1 review page(s)' in item.value for item in app.caption)

    app.radio(key='folder-review-view-v2').set_value('All saved media').run()
    assert not app.exception
    assert {item.value for item in app.subheader} >= {'photo-a.jpg', 'photo-b.jpg', 'video-b.mp4'}
    assert any('2 of 2 scanned folders selected · 3 / 3 files checked · 3 saved previews' in item.value
               for item in app.caption)

    app.multiselect(key='review-folders').set_value(['folder-b']).run()
    app.radio(key='folder-review-view-v2').set_value('All saved media').run()
    assert not app.exception
    assert {item.value for item in app.subheader} >= {'photo-b.jpg', 'video-b.mp4'}
    assert 'photo-a.jpg' not in {item.value for item in app.subheader}


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
    assert any(expander.label == 'Reopen confirmed photo' for expander in app.expander)
    assert app.button(key=f'{prefix}-compact-undo').label == 'Undo'
    assert any('Saved: 0.jpg' in notice.value for notice in app.success)
    assert projects.photo_labels('festival', 'bob')['0'] == 'me'
    app.button(key=f'{prefix}-compact-undo').click().run()
    assert not app.exception
    assert '0' not in projects.photo_labels('festival', 'bob')
    assert not app.button(key=f'{prefix}-me').disabled
    app.button(key=f'{prefix}-me').click().run()
    assert not app.exception
    app.button(key=f'{prefix}-correct-not_me').click().run()
    assert not app.exception
    assert projects.photo_labels('festival', 'bob')['0'] == 'not_me'
    assert any(expander.label == 'Reopen rejected photo' for expander in app.expander)
    assert any('Saved: not in this photo' in caption.value for caption in app.caption)
    assert not any(button.key == f'{prefix}-me' for button in app.button)
    app.button(key=f'{prefix}-compact-undo').click().run()
    assert not app.exception
    assert '0' not in projects.photo_labels('festival', 'bob')
    assert not app.button(key=f'{prefix}-me').disabled
