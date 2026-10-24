"""Stable read-only live panel; the browser updates values without Streamlit reruns."""
import os
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from festival_finder.panel import ensure_panel_server

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('FIND_MY_DANCE_DATA', str(ROOT / 'data')))
st.set_page_config(page_title='Find My Dance · Live scan', page_icon='🪩', layout='wide')
st.title('Live scan: possible matches')
st.caption('The scan runs in the background. Numbers update in place; this page does not reload itself.')
components.iframe(ensure_panel_server(ROOT, DATA), height=800, scrolling=True)
