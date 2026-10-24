"""Find My Dance: reference faces, background folder scans, and manual review."""
import json
import os
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from festival_finder import drive, engine, feedback, jobs, panel
from festival_finder.explainer import render_explainer
from festival_finder.photo_review import render_photo_page
from festival_finder.projects import Projects, sample_id
from festival_finder.results_ui import saved_review_card
from festival_finder.toolbar import render_scan_toolbar
from festival_finder.tree import render_folder_tree

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('FIND_MY_DANCE_DATA', str(ROOT / 'data')))
PAGE_SIZE = 12

st.set_page_config(page_title='Find My Dance', page_icon='🪩', layout='wide')
bank = feedback.Feedback(DATA / 'feedback.sqlite3')
projects = Projects(bank.path)
state = st.session_state
render_scan_toolbar(st, panel.ensure_panel_server(ROOT, DATA))
st.title('🪩 Find My Dance')

routes = {'folders': 'Search and folders', 'review': 'Folder review', 'nearby': 'Nearby photos',
          'confirmed': 'Confirmed photos', 'how': 'How it works'}
pages = list(routes.values())


def navigate():
    st.query_params['page'] = next(key for key, value in routes.items() if value == state['app-page'])


page = st.radio('Pages', pages, index=pages.index(routes.get(st.query_params.get('page'), pages[0])),
                horizontal=True, key='app-page', on_change=navigate, label_visibility='collapsed')

with st.sidebar:
    st.header('Your reference photos')
    uploads = st.file_uploader('Clear photos showing only your face', type=['jpg', 'jpeg', 'png', 'webp'],
                               accept_multiple_files=True, key=f"uploads-{state.get('upload-round', 0)}")
    if uploads and st.button('Save reference photos', type='primary'):
        try:
            with st.spinner('Reading faces locally…'):
                face_engine = engine.FaceEngine(ROOT / 'models')
                for upload in uploads:
                    raw = upload.getvalue()
                    try:
                        feature, crop = face_engine.enroll(raw)
                    except ValueError as exc:
                        st.warning(f'{upload.name}: {exc}')
                        continue
                    ok, encoded = cv2.imencode('.jpg', crop)
                    if ok:
                        bank.save_reference(upload.name, raw, encoded.tobytes(), feature)
            state['upload-round'] = state.get('upload-round', 0) + 1
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    references = bank.references()
    for reference in references:
        image, remove = st.columns([1, 2])
        image.image(reference['crop'], width=64)
        remove.caption(reference['name'])
        remove.button('Remove', key=f"remove-{reference['id']}", on_click=bank.remove_reference, args=(reference['id'],))
    labels = bank.labels()
    st.metric('Saved reference photos', len(references))
    me, not_me = st.columns(2)
    me.metric('Confirmed: me', sum(label == 'me' for label in labels.values()))
    not_me.metric('Confirmed: not me', sum(label == 'not_me' for label in labels.values()))
    st.header('Scan settings')
    st.slider('Similarity cutoff', .20, .80, .40, .01, key='threshold',
              help='Faces at or above this similarity become suggestions. It is not a probability.')
    st.checkbox('Rescan completed files', key='rescan',
                help='Ignore saved results and cached previews for the selected folder.')

if page in {'Folder review', 'Nearby photos', 'Confirmed photos'}:
    render_photo_page(st, projects, bank, DATA, ROOT, page)
    st.stop()
if page == 'How it works':
    render_explainer(st)
    st.stop()


def select_festival(festival_id):
    state.update(festival=festival_id, folder=festival_id)
    state.pop('report', None)


def select_folder(folder_id):
    state['folder'] = folder_id
    state.pop('report', None)


def load_saved(festival_id, folder_id):
    saved = projects.report(festival_id, folder_id)
    if saved and saved.get('mode') != 'face_detection_only':
        return saved
    return None


def find_photos(festival_id, folder):
    saved = load_saved(festival_id, folder['id'])
    if saved and saved.get('finished') and not saved.get('errors') and not state.get('rescan'):
        state['report'] = saved
        state['notice'] = 'Opened saved results for this folder. Enable Rescan completed files to scan again.'
        return
    positives = np.vstack([bank.reference_examples(), bank.examples('me')])
    if not len(positives):
        raise ValueError('Add at least one reference photo of yourself in the sidebar first.')
    service = drive.connect(ROOT / 'credentials.json', DATA / 'token.json')
    items = drive.folder_media(service, folder['id'], folder['path'])
    if not items:
        raise ValueError('This folder has no photos or videos directly inside it. Choose a subfolder.')
    job = jobs.start_job(ROOT, DATA, {
        'items': items, 'references': positives.tolist(), 'negatives': bank.examples('not_me').tolist(),
        'threshold': float(state['threshold']), 'interval': 1.0, 'source': 'drive',
        'folder_name': folder['path'], 'festival_id': festival_id, 'folder_id': folder['id'],
        'force': bool(state.get('rescan'))})
    if job and job['status'] == 'finished':
        state['report'] = load_saved(festival_id, folder['id'])
    else:
        state['pending'] = (festival_id, folder['id'])


def job_report(job):
    path = Path(job['directory']) / 'report.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


st.caption('Pick a festival folder, then scan the photos directly inside it. Matching runs on this computer using small Drive previews.')
festivals = projects.festivals()
if festivals:
    saved_column, open_column = st.columns([3, 1], vertical_alignment='bottom')
    chosen = saved_column.selectbox('Saved festival', [f['id'] for f in festivals],
                                    format_func=lambda fid: next(f['name'] for f in festivals if f['id'] == fid))
    open_column.button('Open saved festival', on_click=select_festival, args=(chosen,))
with st.expander('Add a festival / refresh its folder tree', expanded=not festivals):
    st.text_input('Google Drive folder link', key='festival-link', placeholder='https://drive.google.com/drive/folders/…')
    if st.button('Open festival folder'):
        try:
            with st.spinner('Reading folder names from Google Drive…'):
                service = drive.connect(ROOT / 'credentials.json', DATA / 'token.json')
                root, nodes = drive.folder_tree(service, state.get('festival-link', ''))
                projects.register(root)
                projects.save_folders(root['id'], nodes)
            select_festival(root['id'])
            st.rerun()
        except Exception as exc:
            st.error(str(exc))

job = jobs.current_job(DATA)
running = bool(job and job['status'] in {'starting', 'running'})
if state.get('pending') and job and not running:
    festival_id, folder_id = state.pop('pending')
    if job['status'] == 'finished':
        state['report'] = load_saved(festival_id, folder_id)
    else:
        state['report'] = job_report(job)
        st.error(job.get('error') or 'The background scan stopped. Completed files remain cached; scan again to continue.')

if running:
    @st.fragment(run_every=5)
    def scan_progress():
        current = jobs.current_job(DATA)
        if not current or current['status'] not in {'starting', 'running'}:
            st.rerun(scope='app')
        live = job_report(current) or {}
        total, done = live.get('total_discovered', 0), live.get('processed', 0)
        st.info(f"Scanning {current.get('folder', 'folder')} in the background — {done} / {total} files checked. "
                'You can browse other pages or close this tab.')
        st.progress(done / total if total else 0.)
        if live.get('matches') and st.button('Show results so far'):
            state['report'] = live
    scan_progress()

festival_id = state.get('festival')
if festival_id not in {f['id'] for f in festivals}:
    st.stop()
nodes = {node['id']: node for node in projects.folders(festival_id)}
folder = nodes.get(state.get('folder')) or nodes.get(festival_id)
with st.expander('Festival folder tree', expanded=True):
    st.caption('Green folders have completed scans. Select a folder to scan the photos directly inside it.')
    render_folder_tree(st, festival_id, projects.checklist(festival_id), folder and folder['id'], select_folder)
if not folder:
    st.stop()
st.subheader(folder['path'])
st.caption('Only photos and videos directly inside this folder are checked; subfolders are not included. Videos use their cover thumbnail.')
if st.button('Find my photos and videos', type='primary', disabled=running):
    try:
        with st.spinner('Listing files and starting the background scan…'):
            find_photos(festival_id, folder)
        st.rerun()
    except Exception as exc:
        st.error(str(exc))
if notice := state.pop('notice', None):
    st.success(notice)

report = state.get('report')
if not report:
    st.stop()
st.header('Possible matches')
st.caption(f"{report.get('processed', 0)} of {report.get('total_discovered', 0)} files checked · "
           f"{len(report.get('errors', []))} errors. Scores are similarity, not probability.")
for error in report.get('errors', [])[:20]:
    st.warning(f"{error['name']}: {error['reason']}")
view = st.radio('Show', ['Possible matches', 'All photos with faces'], horizontal=True, key='face-view')
items = [item for item in report.get('matches', []) if view == 'All photos with faces' or any(
    face.get('candidate') for hit in item.get('hits', []) for face in hit.get('faces', []))]
if not items:
    st.info('No suggestions in this folder. Try All photos with faces, a lower cutoff, or more reference photos.')
    st.stop()
number = st.number_input(f'Page ({PAGE_SIZE} files per page)', 1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
labels = bank.labels()
for item in items[(number - 1) * PAGE_SIZE:number * PAGE_SIZE]:
    with saved_review_card(st, item, labels, bank, video_cover=item.get('video', False)):
        preview = next((hit['preview'] for hit in item.get('hits', []) if Path(hit.get('preview', '')).is_file()), None)
        if preview:
            st.image(preview, width=480)
        if item.get('url'):
            st.link_button('Open in Drive', item['url'])
        for hit in item.get('hits', []):
            for index, face in enumerate(hit.get('faces', []), 1):
                if 'embedding' not in face:
                    continue
                sample = sample_id(item, hit, face)
                label = labels.get(sample)
                crop, details, yes, no, undo = st.columns([1, 2, 1, 1, 1], vertical_alignment='center')
                if Path(face.get('crop', '')).is_file():
                    crop.image(face['crop'], width=72)
                details.write(f"Face {index} · similarity {face['score']:.2f}")
                details.caption({'me': '✓ Saved: me', 'not_me': '✓ Saved: not me'}.get(
                    label, 'Suggested match' if face.get('candidate') else 'Below cutoff'))
                yes.button("That's me", key=f'{sample}-me', on_click=bank.set, args=(sample, 'me', face['embedding']),
                           type='primary' if label == 'me' else 'secondary')
                no.button('Not me', key=f'{sample}-not', on_click=bank.set, args=(sample, 'not_me', face['embedding']),
                          type='primary' if label == 'not_me' else 'secondary')
                undo.button('Undo', key=f'{sample}-undo', on_click=bank.undo, args=(sample,), disabled=label is None)
