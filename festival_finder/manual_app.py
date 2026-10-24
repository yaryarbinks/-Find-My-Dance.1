"""Restore saved festival results, manual review, and original downloads."""
import os
from pathlib import Path

import streamlit as st

from festival_finder.feedback import Feedback
from festival_finder.panel import ensure_panel_server
from festival_finder.photo_review import render_photo_page
from festival_finder.projects import Projects
from festival_finder.toolbar import render_scan_toolbar
from festival_finder.tree import render_folder_tree
from festival_finder.detection_jobs import current_detection, start_detection
from festival_finder.detection_ui import render_detection_page


def run():
    root = Path(__file__).resolve().parents[1]
    data = Path(os.environ.get('FIND_MY_DANCE_DATA', str(root / 'data')))
    feedback = Feedback(data / 'feedback.sqlite3')
    projects = Projects(feedback.path)
    st.set_page_config(page_title='Find My Dance', page_icon='🪩', layout='wide')
    render_scan_toolbar(st, ensure_panel_server(root, data))
    st.title('🪩 Find My Dance')
    routes = {'folders': 'Search and folders', 'nearby': 'Nearby photos',
              'confirmed': 'Confirmed photos', 'detect': 'Face detection', 'how': 'How it works'}
    pages = list(routes.values())
    def navigate():
        st.query_params['page'] = next(key for key,value in routes.items() if value == st.session_state['app-page'])
    page = st.radio('Pages', pages, index=pages.index(routes.get(st.query_params.get('page'), pages[0])),
                    horizontal=True, key='app-page', on_change=navigate)
    if page in {'Nearby photos', 'Confirmed photos'}:
        render_photo_page(st, projects, feedback, data, root, page)
        return
    if page == 'Face detection':
        render_detection_page(st,projects,feedback,data)
        return
    if page == 'How it works':
        st.header('How it works')
        st.graphviz_chart('''digraph workflow {
            graph [rankdir=TB, bgcolor="transparent"];
            node [shape=box, style="rounded,filled", fillcolor="#163047", fontcolor="white", color="#5A9CC8"];
            edge [color="#7FAAC5"];
            folders [label="Open a saved festival folder"];
            photos [label="View saved photo previews and results"];
            review [label="You confirm photos manually or mark Not me"];
            saved [label="Your decisions stay in the local database"];
            collection [label="Confirmed photos and nearby-photo review"];
            download [label="Request original-quality downloads when ready"];
            folders -> photos -> review -> saved -> collection -> download;
        }''', width='stretch')
        st.write('This restored interface opens saved results and lets you review photos manually. It does not start new face-matching scans. Historical reports and decisions remain stored unchanged.')
        st.write('Original photos are loaded only after an explicit download request. Photographer download permissions apply. Reviewing saved photos does not use an OpenAI API.')
        return

    st.caption('Saved folder results and manual photo review. Opening a folder does not start a new scan.')
    festivals = projects.festivals()
    if not festivals:
        st.info('No saved festival projects were found in the local database.')
        return
    ids = [f['id'] for f in festivals]
    active = st.query_params.get('festival')
    festival = st.selectbox('Saved festival', ids, index=ids.index(active) if active in ids else 0,
                            format_func=lambda fid: next(f['name'] for f in festivals if f['id'] == fid))
    reports = projects.reports(festival)
    labels = feedback.labels()
    confirmed = {item['id'] for report in reports for item in projects.confirmed(report, labels) if not item.get('video')}
    a,b,c = st.columns(3)
    a.metric('Saved folder reports', len(reports))
    b.metric('Photos confirmed by you', len(confirmed))
    c.metric('Saved previews', sum(len(report.get('matches', [])) for report in reports))
    nodes = projects.folders(festival)
    selected = st.query_params.get('folder') or festival
    node=next((n for n in nodes if n['id']==selected),None)
    if node:
        st.subheader('Selected folder')
        st.write(node['path'])
        st.caption('Detection checks photo previews directly inside this folder. It locates faces only; it does not compare identities. Videos and subfolders are excluded.')
        state=current_detection(data)
        def detect_selected():
            try:
                start_detection(root,data,festival,node)
                st.session_state['app-page']='Face detection'
                st.query_params['page']='detect'
            except Exception as exc:
                st.session_state['detection-start-error']=str(exc)
        st.button('Detect faces in this folder',type='primary',on_click=detect_selected,
                  disabled=bool(state and state['status'] in {'starting','running'}))
        if error:=st.session_state.pop('detection-start-error',None):
            st.error(error)
    def select_folder(fid):
        st.query_params['festival'] = festival
        st.query_params['folder'] = fid
        st.session_state['manual_review_folder'] = fid
        st.session_state.pop('saved-review-folder', None)
    with st.expander('Festival folder tree', expanded=True):
        st.caption('Green folders have completed saved reports. Expand a branch or select a folder to view existing work.')
        render_folder_tree(st, festival, projects.checklist(festival), selected, select_folder)
    if not reports:
        st.info('This festival has no saved reports.')
        return
    render_photo_page(st, projects, feedback, data, root, 'Folder review')
