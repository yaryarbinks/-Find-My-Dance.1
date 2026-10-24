"""A separate resumable job for face locations, without identity matching."""
import json
import os
import subprocess
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime,timezone
from pathlib import Path


def write_json(path,value):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(value,stream)
    try:
        for attempt in range(30):
            try:
                temporary.replace(path)
                break
            except PermissionError:
                if attempt==29:
                    raise
                time.sleep(.1)
    finally:
        temporary.unlink(missing_ok=True)


def alive(pid):
    if not pid:
        return False
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        api.OpenProcess.restype=wintypes.HANDLE
        api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        api.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=api.OpenProcess(0x1000,False,int(pid))
        if not handle:
            return False
        try:
            code=wintypes.DWORD()
            return bool(api.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(int(pid),0)
        return True
    except OSError:
        return False


def current_detection(data):
    root=Path(data)/'face-detection'
    try:
        pointer=json.loads((root/'active.json').read_text())
        directory=(root/pointer['job']).resolve()
        if not directory.is_relative_to(root.resolve()):
            return None
        state=json.loads((directory/'state.json').read_text())
        state['directory']=str(directory)
        pid=state.get('pid') or state.get('launcher_pid')
        if not pid and (directory/'launcher.json').exists():
            pid=json.loads((directory/'launcher.json').read_text()).get('pid')
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(state['started'])).total_seconds()
        if state['status'] in {'starting','running'} and not alive(pid) and age>15:
            state['status']='interrupted'
            state['error']='The detection worker stopped. Saved previews remain available.'
        return state
    except (OSError,ValueError,KeyError):
        return None


def start_detection(root,data,festival,node):
    root,data=Path(root).resolve(),Path(data).resolve()
    current=current_detection(data)
    if current and current['status'] in {'starting','running'}:
        return current
    # Retry the same interrupted folder from its per-file cache.
    if current and current['status'] in {'failed','interrupted','needs_attention'} and current['festival']==festival and current['folder']==node['id']:
        directory=Path(current['directory'])
    else:
        directory=data/'face-detection'/uuid.uuid4().hex
    directory.mkdir(parents=True,exist_ok=True)
    config={'festival':festival,'folder':node['id'],'path':node['path']}
    write_json(directory/'config.json',config)
    state={**config,'status':'starting','processed':0,'total':0,'with_faces':0,'faces':0,
           'errors':0,'started':datetime.now(timezone.utc).isoformat()}
    write_json(directory/'state.json',state)
    write_json(directory.parent/'active.json',{'job':directory.name})
    executable=Path(sys.executable)
    options={'cwd':str(root),'stdin':subprocess.DEVNULL,'close_fds':True}
    if os.name=='nt':
        executable=executable.with_name('pythonw.exe')
        options['creationflags']=subprocess.CREATE_NO_WINDOW
        startup=subprocess.STARTUPINFO()
        startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow=subprocess.SW_HIDE
        options['startupinfo']=startup
    else:
        options['start_new_session']=True
    with (directory/'worker.log').open('ab') as output:
        process=subprocess.Popen([str(executable),'-m','festival_finder.detection_worker',str(root),str(data),str(directory)],stdout=output,stderr=subprocess.STDOUT,**options)
    write_json(directory/'launcher.json',{'pid':process.pid})
    return {**state,'directory':str(directory)}


def detection_snapshot(data):
    state=current_detection(data)
    if state is None:
        return None
    from festival_finder.projects import confirmed_photos
    from festival_finder.timing import duration_text
    report_path=Path(state['directory'])/'report.json'
    report=json.loads(report_path.read_text()) if report_path.exists() else {'matches':[]}
    confirmed=set()
    database=Path(data)/'feedback.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True) as db:
            labels=dict(db.execute('SELECT sample,label FROM reviews'))
            photos=dict(db.execute('SELECT file,label FROM photo_reviews WHERE festival=? AND folder=?',(state['festival'],state['folder'])))
            legacy=db.execute('SELECT report FROM folder_scans WHERE festival=? AND folder=?',(state['festival'],state['folder'])).fetchone()
        for saved in [report]+([json.loads(legacy[0])] if legacy else []):
            confirmed.update(item['id'] for item in confirmed_photos(saved,labels,photos))
    timing=state.get('timing',{})
    status={'starting':'Starting face detection','running':'● Detecting face locations only',
            'finished':'✓ Face detection finished','needs_attention':'Detection finished with preview errors',
            'failed':'Face detection failed','interrupted':'Face detection interrupted'}.get(state['status'],state['status'])
    return {'folder':state['path'],'status':status,'processed':state.get('processed',0),'total':state.get('total',0),
            'possible':state.get('with_faces',0),'possible_label':'Photos with faces','checked_label':'Photos checked',
            'confirmed':len(confirmed),'errors':state.get('errors',0),'previews':[],
            'finished':state['status']=='finished','stopped':state['status'] in {'failed','interrupted','needs_attention'},
            'remaining_seconds':timing.get('remaining_seconds'),'remaining_text':duration_text(timing.get('remaining_seconds')),
            'estimated_finish':timing.get('estimated_finish'),
            'timing':f"Elapsed {duration_text(timing.get('elapsed_seconds'))} · remaining {duration_text(timing.get('remaining_seconds'))}"}
