from streamlit.testing.v1 import AppTest


def test_saved_results_stay_open_until_all_faces_reviewed_then_undo_reopens():
    app = AppTest.from_string('''
import streamlit as st
from festival_finder.results_ui import saved_review_card
from festival_finder.projects import sample_id
item={'id':'photo', 'name':'group.jpg', 'hits':[{'timestamp':None, 'faces':[
    {'box':[1,2,3,4], 'embedding':[]}, {'box':[5,6,7,8], 'embedding':[]},
    {'box':[9,10,11,12], 'embedding':[]}]}]}
samples=[sample_id(item,item['hits'][0],face) for face in item['hits'][0]['faces']]
if 'labels' not in st.session_state:
    st.session_state['labels']={samples[0]:'not_me',samples[1]:'not_me'}
class Bank:
    def undo(self,sample): st.session_state['labels'].pop(sample,None)
with saved_review_card(st,item,st.session_state['labels'],Bank()):
    st.write('Full photo and individual review controls')
    if st.button('Review remaining face'):
        st.session_state['labels'][samples[2]]='me'
        st.rerun()
''').run()
    assert not app.exception
    assert app.expander[0].proto.expanded
    assert not any(button.key == 'compact-undo-photo' for button in app.button)
    app.button[0].click().run()
    assert not app.exception
    assert not app.expander[0].proto.expanded
    app.button(key='compact-undo-photo').click().run()
    assert not app.exception
    assert len(app.session_state['labels']) == 2
    assert list(app.session_state['labels'].values()).count('me') == 1
    assert app.expander[0].proto.expanded
