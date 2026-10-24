"""Read a folder's photo thumbnails and save face bounding boxes only."""
import hashlib
import json
import os
import sys
import traceback
from datetime import datetime,timezone
from pathlib import Path

from festival_finder import drive
from festival_finder.detection_jobs import write_json
from festival_finder.detection_only import FaceLocator
from festival_finder.projects import Projects
from festival_finder.timing import ScanTiming


def process_photos(service,items,locator,directory,config,on_progress=None):
    directory=Path(directory)
    photos=[item for item in items if item.get('mimeType','').startswith('image/')]
    timer=ScanTiming(len(photos))
    report={'mode':'face_detection_only','festival_id':config['festival'],'folder_id':config['folder'],
            'selected_folder':config['path'],'processed':0,'total_discovered':len(photos),
            'matches':[],'errors':[],'finished':False,'preview_only':True,'with_faces':0,'faces':0}
    def checkpoint():
        report['timing']=timer.snapshot(datetime.now(timezone.utc))
        write_json(directory/'report.json',report)
        if on_progress:
            on_progress(report)
    checkpoint()
    for item in photos:
        key=hashlib.sha256(json.dumps([item['id'],item.get('modifiedTime'),item.get('size')]).encode()).hexdigest()
        cache=directory/'files'/key
        try:
            cached=cache/'result.json'
            result=json.loads(cached.read_text()) if cached.exists() else None
            if result is None or not Path(result['hits'][0]['preview']).is_file() or not Path(result['boxed_preview']).is_file():
                located=locator.locate(drive.thumbnail(service,item),cache)
                result={**item,'video':False,'folder':config['path'],'local_path':'',
                        'url':item.get('webViewLink',f"https://drive.google.com/file/d/{item['id']}/view"),
                        'detected_faces':located['boxes'],'boxed_preview':located['boxed_preview'],
                        'hits':[{'timestamp':None,'score':0,'faces':[],'preview':located['preview']}]}
                write_json(cached,result)
            report['matches'].append(result)
            count=len(result['detected_faces'])
            report['with_faces']+=int(count>0)
            report['faces']+=count
        except Exception as exc:
            report['errors'].append({'name':item['name'],'reason':str(exc)})
        report['processed']+=1
        timer.complete_file()
        checkpoint()
    report['finished']=True
    checkpoint()
    return report


def run(root,data,directory):
    config=json.loads((directory/'config.json').read_text())
    state=json.loads((directory/'state.json').read_text())
    state.update(pid=os.getpid(),status='running')
    write_json(directory/'state.json',state)
    try:
        locator=FaceLocator(root/'models')
        service=drive.connect(root/'credentials.json',data/'token.json')
        items=drive.folder_media(service,config['folder'],config['path'])
        projects=Projects(data/'feedback.sqlite3')
        def progress(report):
            projects.archive_detection(config['festival'],config['folder'],report)
            state.update(processed=report['processed'],total=report['total_discovered'],
                         with_faces=report['with_faces'],faces=report['faces'],errors=len(report['errors']),timing=report['timing'])
            write_json(directory/'state.json',state)
        report=process_photos(service,items,locator,directory,config,progress)
        state['status']='needs_attention' if report['errors'] else 'finished'
    except Exception as exc:
        state.update(status='failed',error=str(exc))
        traceback.print_exc()
    write_json(directory/'state.json',state)


if __name__=='__main__':
    run(Path(sys.argv[1]),Path(sys.argv[2]),Path(sys.argv[3]))
