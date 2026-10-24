import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer

import pytest

from festival_finder.feedback import Feedback
from festival_finder.progress_server import handler, HTML


def test_panel_api_updates_without_page_reload_and_exposes_no_files(tmp_path):
    Feedback(tmp_path / 'feedback.sqlite3')
    report = {'processed': 100, 'total_discovered': 418, 'finished': False, 'matches': [], 'errors': [],
              'timing': {'remaining_seconds': 185, 'estimated_finish': '2026-10-24T10:03:05+00:00'}}
    path = tmp_path / 'last-report.json'
    path.write_text(json.dumps(report))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler(tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_address[1]}'
    try:
        with urllib.request.urlopen(url + '/') as page:
            html = page.read().decode()
        assert 'location.reload' not in html
        assert "node.textContent!==next" in html
        assert "key!==photoKey" in html
        assert 'setInterval(update,5000)' in html
        with urllib.request.urlopen(url + '/compact') as page:
            compact = page.read().decode()
        assert 'Live scan status' in compact
        assert 'Confirmed by you' in compact and 'Possible matches' in compact and 'Checked' in compact
        assert 'setInterval(update,5000)' in compact
        assert 'location.reload' not in compact and '<img' not in compact
        assert 'id="eta"' in compact and "timeZone:'Asia/Jerusalem'" in compact
        with urllib.request.urlopen(url + '/progress') as response:
            values = json.load(response)
            assert values['processed'] == 100
            assert values['remaining_text'] == '3m 5s'
            assert values['estimated_finish'] == report['timing']['estimated_finish']
        report['processed'] = 101
        path.write_text(json.dumps(report))
        with urllib.request.urlopen(url + '/progress') as response:
            assert json.load(response)['processed'] == 101
        for target in ['/preview/../../feedback.sqlite3', '/credentials.json']:
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(url + target)
            assert error.value.code == 404
        request = urllib.request.Request(url + '/progress', headers={'Sec-Fetch-Site': 'cross-site'})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown()
        server.server_close()


def test_toolbar_is_fixed_and_shared_by_all_app_pages():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_string('''
import streamlit as st
from festival_finder.toolbar import render_scan_toolbar
render_scan_toolbar(st, 'http://127.0.0.1:8503/')
''').run()
    assert not app.exception
    markup = app.markdown[0].value
    assert 'position:fixed' in markup and '/compact' in markup
    assert 'title="Live scan status"' in markup
    source = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')
    assert source.index('render_scan_toolbar(st,') < source.index("if page == 'How it works'")
