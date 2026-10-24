import json
import shutil
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

from festival_finder.detection_only import FaceLocator
from festival_finder.detection_worker import process_photos
from festival_finder.feedback import Feedback
from festival_finder.projects import Projects,sample_id
from festival_finder.detection_jobs import write_json,detection_snapshot


def test_real_detector_works_without_a_recognition_model(tmp_path,monkeypatch):
    root=Path(__file__).resolve().parents[1]
    models=tmp_path/'models';models.mkdir()
    shutil.copy2(root/'models/face_detection_yunet_2023mar.onnx',models)
    class NoRecognition:
        @staticmethod
        def create(*args):
            raise AssertionError('Identity recognizer must not load')
    monkeypatch.setattr(cv2,'FaceRecognizerSF',NoRecognition)
    locator=FaceLocator(models)
    result=locator.locate((root/'data/test-fixtures/lena.jpg').read_bytes(),tmp_path/'preview')
    assert result['boxes']
    assert set(result)=={'boxes','preview','boxed_preview'}
    assert Path(result['boxed_preview']).is_file()
    blank=cv2.imencode('.jpg',np.zeros((100,100,3),dtype=np.uint8))[1].tobytes()
    assert not locator.locate(blank,tmp_path/'blank')['boxes']


def test_pipeline_detects_photos_only_reuses_cache_and_records_no_features(tmp_path,monkeypatch):
    from festival_finder import drive
    items=[{'id':'photo','name':'Photo.jpg','mimeType':'image/jpeg'},
           {'id':'video','name':'Video.mp4','mimeType':'video/mp4'}]
    thumbnail=Mock(return_value=b'preview')
    monkeypatch.setattr(drive,'thumbnail',thumbnail)
    monkeypatch.setattr(drive,'download',Mock(side_effect=AssertionError('No originals')))
    def locate(raw,directory):
        directory.mkdir(parents=True,exist_ok=True)
        p=directory/'p.jpg';p.write_bytes(b'preview')
        return {'preview':str(p),'boxed_preview':str(p),'boxes':[[1,2,3,4]]}
    locator=Mock();locator.locate.side_effect=locate
    config={'festival':'festival','folder':'folder','path':'Festival / Folder'}
    report=process_photos(object(),items,locator,tmp_path,config)
    assert report['processed']==1 and report['total_discovered']==1
    assert report['with_faces']==1 and report['faces']==1
    item=report['matches'][0]
    assert item['hits'][0]['faces']==[] and 'embedding' not in json.dumps(item)
    process_photos(object(),items,locator,tmp_path,config)
    assert thumbnail.call_count==1 and locator.locate.call_count==1


def test_detection_reports_preserve_old_human_confirmations(tmp_path):
    feedback=Feedback(tmp_path/'feedback.sqlite3');projects=Projects(feedback.path)
    item={'id':'photo','name':'photo.jpg','hits':[{'timestamp':None,'preview':'old','faces':[{'box':[1,2,3,4]}]}]}
    report={'processed':1,'total_discovered':1,'finished':True,'errors':[],'matches':[item]}
    projects.archive('festival','folder',report)
    feedback.set(sample_id(item,item['hits'][0],item['hits'][0]['faces'][0]),'me',np.eye(1,128,dtype=np.float32)[0])
    before=feedback.labels()
    detected={**report,'matches':[{'id':'photo','name':'photo.jpg','detected_faces':[[2,3,4,5]],'hits':[{'timestamp':None,'preview':'new','faces':[]}]}]}
    projects.archive_detection('festival','folder',detected)
    assert len(projects.confirmed(projects.report('festival','folder'),feedback.labels()))==1
    assert feedback.labels()==before
    assert projects.detection_report('festival','folder')['matches'][0]['hits'][0]['faces']==[]
    with projects.connection() as db:
        assert json.loads(db.execute('SELECT report FROM folder_scans').fetchone()[0])==report


def test_detection_progress_is_labeled_as_locations_not_identity_matches(tmp_path):
    Feedback(tmp_path/'feedback.sqlite3');Projects(tmp_path/'feedback.sqlite3')
    directory=tmp_path/'face-detection/job';directory.mkdir(parents=True)
    write_json(directory.parent/'active.json',{'job':'job'})
    write_json(directory/'state.json',{'festival':'festival','folder':'folder','path':'Folder','status':'finished',
               'started':'2026-10-24T00:00:00+00:00','processed':3,'total':3,'with_faces':2,'faces':4})
    result=detection_snapshot(tmp_path)
    assert result['possible_label']=='Photos with faces'
    assert result['possible']==2 and result['confirmed']==0
    assert result['finished']
