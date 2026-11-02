"""Launch the local read-only progress panel without a console window."""
import hashlib
import ipaddress
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PORT = 8503


def _identity(data):
    canonical = str(Path(data).resolve()).casefold().encode()
    return hashlib.sha256(canonical).hexdigest()


def browser_host(host_header):
    try:
        raw = (host_header or '').strip()
        host = raw if raw == 'localhost' else None
        if not host:
            try:
                address = ipaddress.ip_address(raw.strip('[]'))
                host = str(address) if address.is_loopback else None
            except ValueError:
                host = urlsplit(f'//{raw}').hostname
        if host == 'localhost' or (host and ipaddress.ip_address(host).is_loopback):
            return host
    except ValueError:
        pass
    return '127.0.0.1'


def _url(port, host):
    host = f'[{host}]' if ':' in host else host
    return f'http://{host}:{port}/'


def _address_family(host):
    return socket.AF_INET6 if ':' in host else socket.AF_INET


def _can_bind(host, port):
    try:
        with socket.socket(_address_family(host)) as server:
            server.bind((host, port))
        return True
    except OSError:
        return False


def healthy(data, port, host='127.0.0.1'):
    try:
        with urllib.request.urlopen(_url(port, host)+'health', timeout=.3) as response:
            return response.status == 200 and response.read().decode() == _identity(data)
    except OSError:
        return False


def _available_port(host):
    with socket.socket(_address_family(host)) as server:
        server.bind((host, 0))
        return server.getsockname()[1]


def ensure_panel_server(root, data, host='127.0.0.1'):
    root, data = Path(root).resolve(), Path(data).resolve()
    host = browser_host(host)
    data.mkdir(parents=True, exist_ok=True)
    port_file = data / 'panel-server-port'
    try:
        port = int(port_file.read_text())
    except (OSError, ValueError):
        port = None
    for candidate in (port, DEFAULT_PORT):
        if candidate and healthy(data, candidate, host):
            port_file.write_text(str(candidate))
            return _url(candidate, host)

    lock = data / 'panel-launch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        fd = None
    if fd is not None:
        os.close(fd)
        try:
            port = next((candidate for candidate in (port, DEFAULT_PORT)
                         if candidate and _can_bind(host, candidate)), None)
            if port is None:
                port = _available_port(host)
            port_file.write_text(str(port))
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
                process = subprocess.Popen([str(executable), '-m', 'festival_finder.progress_server',
                                            str(data), str(port), host],
                                           stdout=output, stderr=subprocess.STDOUT, **options)
            (data / 'panel-server.pid').write_text(str(process.pid))
        finally:
            lock.unlink(missing_ok=True)
    deadline = time.monotonic()+8
    while time.monotonic()<deadline:
        try:
            port = int(port_file.read_text())
        except (OSError, ValueError):
            port = None
        if port and healthy(data, port, host):
            return _url(port, host)
        time.sleep(.1)
    raise RuntimeError(f'Could not start the progress panel for {data}. See {data / "panel-server.log"}.')
