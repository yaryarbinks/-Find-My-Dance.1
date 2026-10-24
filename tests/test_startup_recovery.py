import base64
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from festival_finder.feedback import Feedback
from festival_finder.projects import Projects, sample_id


@pytest.fixture
def recovered_app(tmp_path, monkeypatch):
    from festival_finder import panel
    monkeypatch.setattr(panel,'ensure_panel_server',lambda *args:'http://127.0.0.1:8503/')
    monkeypatch.setenv('FIND_MY_DANCE_DATA',str(tmp_path))
    feedback=Feedback(tmp_path/'feedback.sqlite3')
    projects=Projects(feedback.path)
    projects.register({'id':'festival','name':'Saved festival'})
    projects.save_folders('festival',[{'id':'folder','parent':None,'name':'Saved folder','path':'Festival / Saved folder'}])
    preview=tmp_path/'preview.png'
    preview.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII='))
    item={'id':'saved-photo','name':'Saved photo.png','video':False,'url':'',
          'hits':[{'timestamp':None,'score':.8,'preview':str(preview),
                   'faces':[{'box':[1,2,3,4],'candidate':True}]}]}
    report={'matches':[item],'processed':1,'total_discovered':1,'errors':[],'finished':True}
    projects.archive('festival','folder',report)
    feedback.set(sample_id(item,item['hits'][0],item['hits'][0]['faces'][0]),'me',np.eye(1,128,dtype=np.float32)[0])
    return feedback,projects


@pytest.mark.parametrize('page',['folders','confirmed','nearby','how'])
def test_recovered_saved_result_pages_open_without_network_or_scanning(recovered_app,page):
    feedback,projects=recovered_app
    before=feedback.labels()
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py')
    app.query_params['page']=page
    app.run(timeout=20)
    assert not app.exception
    assert feedback.labels()==before
    assert len(projects.confirmed(projects.report('festival','folder'),before))==1
    assert not any(b.label=='Find my photos and videos' for b in app.button)


def test_manual_review_keeps_historical_face_decisions(recovered_app):
    feedback,projects=recovered_app
    before=feedback.labels()
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py')
    app.query_params['page']='confirmed'
    app.run(timeout=20)
    next(b for b in app.button if b.label=='Not in this photo').click().run()
    assert not app.exception
    assert projects.photo_labels('festival','folder')=={'saved-photo':'not_me'}
    assert feedback.labels()==before
    assert len(projects.confirmed(projects.report('festival','folder'),before))==0
