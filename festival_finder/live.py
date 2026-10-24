"""Read-only scan summaries shared by the scanner and separate live viewer."""
import json
import sqlite3
from pathlib import Path


from festival_finder.projects import confirmed_photos


def possible_matches(report):
    """Count files, not faces/frames, using only automatic candidate flags."""
    found, seen = [], set()
    for item in report.get('matches', []):
        identifier = item.get('id') or item.get('local_path') or item.get('url') or item['name']
        if identifier in seen:
            continue
        candidate_hits = [hit for hit in item.get('hits', []) if any(
            face.get('candidate', face.get('score', -1) >= report.get('threshold', .4))
            for face in hit.get('faces', []))]
        if candidate_hits:
            seen.add(identifier)
            found.append((item, max(candidate_hits, key=lambda hit: hit.get('score', 0))))
    return found


def live_stats(report, labels):
    candidates = possible_matches(report)
    confirmed = {item.get('id') or item.get('local_path') or item.get('url') or item['name']
                 for item in confirmed_photos(report, labels, report.get('photo_labels'))}
    return {'possible_files': len(candidates), 'confirmed_files': len(confirmed),
            'processed': report.get('processed', 0), 'total': report.get('total_discovered', 0),
            'candidates': candidates}


def read_snapshot(directory):
    """Never write scan state or modify the feedback database."""
    directory = Path(directory)
    path = directory / 'last-report.json'
    if not path.exists():
        return None, {}
    report = json.loads(path.read_text(encoding='utf-8'))
    labels = {}
    database = directory / 'feedback.sqlite3'
    if database.exists():
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            labels = dict(db.execute('SELECT sample,label FROM reviews'))
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='photo_reviews'").fetchone():
                report['photo_labels'] = dict(db.execute(
                    'SELECT file,label FROM photo_reviews WHERE festival=? AND folder=?',
                    (report.get('festival_id'), report.get('folder_id'))))
    return report, labels

