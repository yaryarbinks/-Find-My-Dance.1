"""Launch the local read-only progress panel without a console window."""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

URL = 'http://127.0.0.1:8503/'


def healthy():
    try:
        with urllib.request.urlopen(URL+'health', timeout=.3) as response:
            return response.status == 200
    except OSError:
        return False


def ensure_panel_server(root, data):
    if healthy():
        return URL
    root, data = Path(root).resolve(), Path(data).resolve()
    data.mkdir(parents=True, exist_ok=True)
    lock = data / 'panel-launch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        fd = None
    if fd is not None:
        os.close(fd)
        try:
            executable = Path(sys.executable)
            options = {'cwd': str(root), 'stdin': subprocess.DEVNULL, 'close_fds': True}
            if os.name == 'nt':
                executable = executable.with_name('pythonw.exe')
                options['creationflags'] = subprocess.CREATE_NO_WINDOW
                startup = subprocess.STARTUPINFO()
                startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startup.wShowWindow = subprocess.SW_HIDE
                options['startupinfo'] = startup
            else:
                options['start_new_session'] = True
            with (data / 'panel-server.log').open('ab') as output:
                process = subprocess.Popen([str(executable), '-m', 'festival_finder.progress_server', str(data)],
                                           stdout=output, stderr=subprocess.STDOUT, **options)
            (data / 'panel-server.pid').write_text(str(process.pid))
        finally:
            lock.unlink(missing_ok=True)
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        if healthy():
            return URL
        time.sleep(.1)
    return URL
