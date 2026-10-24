"""Scan independently of Streamlit's page/session lifetime."""
import json
import os
import sys
import faulthandler
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import cv2

from festival_finder import drive
from festival_finder.engine import FaceEngine, cache_key, save_report, scan_preview, scan_file
from festival_finder.feedback import Feedback
from festival_finder.projects import Projects
from festival_finder.timing import ScanTiming


def run(config):
    cv2.setNumThreads(2)
    root, data, directory = map(Path, (config['root'], config['data'], config['job_directory']))
    fault_log = (directory / 'fault.log').open('a')
    faulthandler.enable(file=fault_log, all_threads=True)
    state = json.loads((directory / 'state.json').read_text())
    state.update(status='running', pid=os.getpid())
    save_report(directory / 'state.json', state)
    items = config['items']
    matrix = np.asarray(config['references'], dtype=np.float32).reshape(-1, 128)
    negatives = np.asarray(config['negatives'], dtype=np.float32).reshape(-1, 128)
    threshold, interval = config['threshold'], config['interval']
    report = {'total_discovered': len(items), 'limit': len(items), 'processed': 0, 'cached': 0,
              'skipped': [], 'errors': [], 'matches': [], 'threshold': threshold, 'interval': interval,
              'reference_count': len(matrix), 'preview_only': config['source'] == 'drive', 'preview_bytes': 0,
              'selected_folder': config['folder_name'], 'festival_id': config.get('festival_id'),
              'folder_id': config.get('folder_id'), 'scan_scope': 'whole_selected_folder', 'finished': False,
              'job_status': 'running', 'worker_pid': os.getpid()}
    engine, service = None, None
    timer = ScanTiming(len(items))
    bank = Feedback(data / 'feedback.sqlite3')
    projects = Projects(bank.path)

    def publish():
        report['timing'] = timer.snapshot(datetime.now(ZoneInfo('Asia/Jerusalem')))
        report['updated_at'] = datetime.now(timezone.utc).isoformat()
        save_report(directory / 'report.json', report)
        save_report(data / 'last-report.json', report)
    publish()
    try:
        for item in items:
            state['current_file'] = item['name']
            save_report(directory / 'state.json', state)
            try:
                identity = {key: item.get(key) for key in ['id', 'size', 'modifiedTime']}
                identity['mode'] = 'drive-preview' if config['source'] == 'drive' else 'local-original'
                import hashlib
                identity['negative_examples'] = hashlib.sha256(negatives.tobytes()).hexdigest()
                key = cache_key(identity, matrix, threshold, interval)
                destination = data / 'runs' / key
                cached = destination / 'result.json'
                if cached.exists() and not config.get('force'):
                    hits = json.loads(cached.read_text(encoding='utf-8'))['hits']
                    if any(not Path(hit['preview']).exists() for hit in hits):
                        raise ValueError('Cached preview missing; enable Rescan completed files to repair.')
                    report['cached'] += 1
                else:
                    if engine is None:
                        engine = FaceEngine(root / 'models')
                    if config['source'] == 'drive':
                        if service is None:
                            service = drive.connect(root / 'credentials.json', data / 'token.json')
                        raw = drive.thumbnail(service, item)
                        report['preview_bytes'] += len(raw)
                        hits = scan_preview(engine, raw, matrix, negatives, threshold, destination)
                    else:
                        path = Path(item['local_path'])
                        hits = (scan_file(engine, path, True, matrix, threshold, interval, destination)
                                if item['mimeType'].startswith('video/') else
                                scan_preview(engine, path.read_bytes(), matrix, negatives, threshold, destination))
                    save_report(cached, {'hits': hits})
                report['processed'] += 1
                if hits:
                    report['matches'].append({'id': item['id'], 'name': item['name'], 'folder': item['folder'],
                        'review_key': key, 'url': item.get('webViewLink', ''), 'local_path': item.get('local_path', ''),
                        'video': item['mimeType'].startswith('video/'), 'hits': hits})
            except Exception as exc:
                report['errors'].append({'name': item['name'], 'reason': str(exc)})
            timer.complete_file()
            publish()
        report.update(finished=True, job_status='finished')
        if report.get('festival_id') and report.get('folder_id'):
            projects.archive(report['festival_id'], report['folder_id'], report)
        publish()
        state.update(status='finished', errors=len(report['errors']))
    except BaseException as exc:
        report.update(job_status='failed', worker_error=str(exc))
        publish()
        state.update(status='failed', error=str(exc))
    finally:
        save_report(directory / 'state.json', state)
        faulthandler.disable()
        fault_log.close()


if __name__ == '__main__':
    run(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
