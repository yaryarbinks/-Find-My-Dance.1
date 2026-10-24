from pathlib import Path

import numpy as np

from festival_finder.feedback import Feedback
from festival_finder.projects import Projects, sample_id, confirmed_photos
from festival_finder.tree import folder_tree_html


def fixture_report():
    return {'total_discovered': 700, 'processed': 700, 'errors': [], 'finished': True,
            'matches': [{'id': 'photo1', 'hits': [{'timestamp': None, 'faces': [{'box': [1, 2, 3, 4]}, {'box': [5, 6, 7, 8]}]}]}]}


def test_festival_counts_come_from_reviews_and_survive_restart(tmp_path):
    db = tmp_path / 'feedback.sqlite3'
    reviews = Feedback(db)
    projects = Projects(db)
    for festival in ['festival1', 'festival2']:
        projects.register({'id': festival, 'name': festival})
        projects.save_folders(festival, [{'id': 'bob', 'name': 'BOB', 'path': 'Day / BOB', 'parent': None}])
    report = fixture_report()
    projects.archive('festival1', 'bob', report)
    row = projects.checklist('festival1')[0]
    assert row['files_checked'] == 700 and row['status'] == 'Completed'
    assert row['confirmed_photos'] == 0
    feature = np.eye(1, 128, dtype=np.float32)[0]
    item = report['matches'][0]
    hit = item['hits'][0]
    for face in hit['faces']:
        reviews.set(sample_id(item, hit, face), 'me', feature)
    assert len(confirmed_photos(report, reviews.labels())) == 1
    assert Projects(db).checklist('festival1')[0]['confirmed_photos'] == 1
    assert projects.checklist('festival2')[0]['status'] == 'Not scanned'
    assert projects.checklist('festival2')[0]['confirmed_photos'] == 0
    for face in hit['faces']:
        reviews.undo(sample_id(item, hit, face))
    assert projects.checklist('festival1')[0]['confirmed_photos'] == 0
    assert projects.report('festival1', 'bob')['processed'] == 700


def test_tree_is_clickable_and_escapes_folder_names():
    rows = [{'id': 'root', 'parent': None, 'name': '<Festival>', 'status': 'Not scanned', 'files_checked': 0, 'files_total': None, 'confirmed_photos': 0},
            {'id': 'bob', 'parent': 'root', 'name': 'BOB', 'status': 'Completed', 'files_checked': 700, 'files_total': 700, 'confirmed_photos': 5}]
    html = folder_tree_html('root', rows, 'bob')
    assert '&lt;Festival&gt;' in html
    assert '700 / 700 checked · 5 confirmed photos' in html
    assert 'folder=bob' in html and 'folder-node selected' in html


def test_branch_completion_is_derived_from_child_scans(tmp_path):
    path = tmp_path / 'feedback.sqlite3'
    Feedback(path)
    p = Projects(path)
    p.register({'id': 'festival', 'name': 'Festival'})
    p.save_folders('festival', [
        {'id': 'root', 'parent': None, 'name': 'Thursday', 'path': 'Thursday'},
        {'id': 'bob', 'parent': 'root', 'name': 'BOB', 'path': 'Thursday / BOB'},
        {'id': 'next', 'parent': 'root', 'name': 'Next', 'path': 'Thursday / Next'}])
    p.archive('festival', 'bob', fixture_report())
    root = next(row for row in p.checklist('festival') if row['id'] == 'root')
    assert root['direct_subfolders'] == 2
    assert root['leaf_completed'] == 1 and root['leaf_folders'] == 2
    assert root['completion_percent'] == 50


def test_native_tree_selects_without_navigation_links():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from festival_finder.tree import render_folder_tree
rows = [dict(id='root', parent=None, name='Festival', status='Not scanned',
             leaf_completed=0, leaf_folders=1, completion_percent=0),
        dict(id='bob', parent='root', name='BOB', status='Completed',
             files_checked=700, files_total=700, confirmed_photos=7)]
def choose(fid):
    st.session_state['chosen'] = fid
render_folder_tree(st, 'festival', rows, st.session_state.get('chosen', 'root'), choose)
''').run()
    assert not app.exception
    app.button(key='tree-select-festival-bob').click().run()
    assert not app.exception
    assert app.session_state['chosen'] == 'bob'
    assert app.button(key='tree-select-festival-bob').proto.type == 'primary'
    assert 'Selected' in app.button(key='tree-select-festival-bob').label
    assert all('href=' not in node.value for node in app.markdown)


def test_green_folder_state_requires_actual_completion():
    from festival_finder.tree import folder_complete
    row = dict(status='Not scanned', leaf_folders=160, leaf_completed=159, completion_percent=100)
    assert not folder_complete(row, branch=True)
    row['leaf_completed'] = 160
    assert folder_complete(row, branch=True)
    row['status'] = 'Needs attention'
    assert not folder_complete(row, branch=True)
    assert not folder_complete(row)
    row['status'] = 'Completed'
    assert folder_complete(row)
