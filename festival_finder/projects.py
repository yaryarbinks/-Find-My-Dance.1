"""Persistent festival checklist, scan reports, and photo-level review counts."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone


def sample_id(item, hit, face):
    return hashlib.sha256(json.dumps([item.get('id'), hit['timestamp'], face['box']], sort_keys=True).encode()).hexdigest()


def confirmed_photos(report, labels, photo_labels=None):
    photo_labels = photo_labels or {}
    return [item for item in report.get('matches', []) if photo_labels.get(item['id']) == 'me' or (
        item['id'] not in photo_labels and any(
        labels.get(sample_id(item, hit, face)) == 'me'
        for hit in item['hits'] for face in hit['faces']))]


class Projects:
    def __init__(self, path):
        self.path = path
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS festivals (id TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS festival_folders (festival TEXT, id TEXT, parent TEXT, name TEXT, path TEXT, PRIMARY KEY(festival,id));
                CREATE TABLE IF NOT EXISTS folder_scans (festival TEXT, folder TEXT, total INTEGER, processed INTEGER, errors INTEGER, finished INTEGER, updated TEXT, report TEXT, PRIMARY KEY(festival,folder));
                CREATE TABLE IF NOT EXISTS folder_samples (festival TEXT, folder TEXT, file TEXT, sample TEXT, PRIMARY KEY(festival,folder,file,sample));
                CREATE TABLE IF NOT EXISTS photo_reviews (festival TEXT, folder TEXT, file TEXT, label TEXT NOT NULL, PRIMARY KEY(festival,folder,file));
                CREATE TABLE IF NOT EXISTS detection_reports (festival TEXT, folder TEXT, report TEXT NOT NULL, PRIMARY KEY(festival,folder));
            ''')

    def connection(self):
        return sqlite3.connect(self.path)

    def register(self, root):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO festivals VALUES (?,?,?)',
                       (root['id'], root['name'], root.get('webViewLink', f"https://drive.google.com/drive/folders/{root['id']}")))

    def festivals(self):
        with self.connection() as db:
            return [dict(zip(['id', 'name', 'url'], row)) for row in db.execute('SELECT id,name,url FROM festivals ORDER BY rowid')]

    def photo_labels(self, festival, folder):
        with self.connection() as db:
            return dict(db.execute('SELECT file,label FROM photo_reviews WHERE festival=? AND folder=?', (festival, folder)))

    def review_photo(self, festival, folder, file, label):
        if label not in {'me', 'not_me', None}:
            raise ValueError('Unknown photo label.')
        with self.connection() as db:
            if label is None:
                db.execute('DELETE FROM photo_reviews WHERE festival=? AND folder=? AND file=?', (festival, folder, file))
            else:
                db.execute('INSERT OR REPLACE INTO photo_reviews VALUES (?,?,?,?)', (festival, folder, file, label))

    def confirmed(self, report, labels):
        return confirmed_photos(report, labels, self.photo_labels(report.get('festival_id'), report.get('folder_id')))

    def reports(self, festival):
        with self.connection() as db:
            folders={row[0] for row in db.execute('SELECT folder FROM folder_scans WHERE festival=? UNION SELECT folder FROM detection_reports WHERE festival=?',(festival,festival))}
        return [self.report(festival,folder) for folder in sorted(folders)]

    def archive_detection(self, festival, folder, report):
        """Store detection-only output separately; historical reports are untouched."""
        value={**report,'festival_id':festival,'folder_id':folder,'mode':'face_detection_only'}
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO detection_reports VALUES (?,?,?)',(festival,folder,json.dumps(value)))

    def detection_report(self, festival, folder):
        with self.connection() as db:
            row=db.execute('SELECT report FROM detection_reports WHERE festival=? AND folder=?',(festival,folder)).fetchone()
        return json.loads(row[0]) if row else None

    def save_folders(self, festival, nodes):
        with self.connection() as db:
            db.executemany('INSERT OR REPLACE INTO festival_folders VALUES (?,?,?,?,?)',
                           [(festival, n['id'], n.get('parent'), n['name'], n['path']) for n in nodes])

    def folders(self, festival):
        with self.connection() as db:
            return [dict(zip(['id', 'parent', 'name', 'path'], row)) for row in db.execute(
                'SELECT id,parent,name,path FROM festival_folders WHERE festival=? ORDER BY path', (festival,))]

    def archive(self, festival, folder, report):
        report['festival_id'], report['folder_id'] = festival, folder
        samples = [(festival, folder, item['id'], sample_id(item, hit, face))
                   for item in report.get('matches', []) for hit in item['hits'] for face in hit['faces']]
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO folder_scans VALUES (?,?,?,?,?,?,?,?)',
                       (festival, folder, report['total_discovered'], report['processed'], len(report['errors']),
                        int(bool(report.get('finished'))), datetime.now(timezone.utc).isoformat(), json.dumps(report)))
            db.execute('DELETE FROM folder_samples WHERE festival=? AND folder=?', (festival, folder))
            db.executemany('INSERT OR IGNORE INTO folder_samples VALUES (?,?,?,?)', samples)

    def report(self, festival, folder):
        with self.connection() as db:
            row = db.execute('SELECT report FROM folder_scans WHERE festival=? AND folder=?', (festival, folder)).fetchone()
        legacy=json.loads(row[0]) if row else None
        detected=self.detection_report(festival,folder)
        if detected is None:
            return legacy
        previous={item['id']:item for item in (legacy or {}).get('matches',[])}
        for item in detected['matches']:
            old=previous.get(item['id'])
            if old and old.get('hits'):
                # Preserve historical human decisions. No new features or scores
                # are generated by the detector.
                preview=item['hits'][0]['preview']
                item['hits']=[{**hit,'preview':preview} for hit in old['hits']]
        present={item['id'] for item in detected['matches']}
        detected['matches'].extend(item for item in previous.values() if item['id'] not in present)
        return detected

    def checklist(self, festival):
        with self.connection() as db:
            scans = {row[0]: row[1:] for row in db.execute('SELECT folder,total,processed,errors,finished FROM folder_scans WHERE festival=?', (festival,))}
            for row in db.execute('SELECT folder,report FROM detection_reports WHERE festival=?',(festival,)):
                if row[0] not in scans:
                    r=json.loads(row[1])
                    scans[row[0]]=(r['total_discovered'],r['processed'],len(r['errors']),int(bool(r.get('finished'))))
            labels = dict(db.execute('SELECT sample,label FROM reviews'))
        counts = {report['folder_id']: len(self.confirmed(report, labels)) for report in self.reports(festival)}
        result = []
        for folder in self.folders(festival):
            scan = scans.get(folder['id'])
            state = 'Not scanned' if not scan else ('Completed' if scan[3] and not scan[2] else 'Needs attention')
            result.append({**folder, 'status': state, 'files_checked': scan[1] if scan else 0,
                           'files_total': scan[0] if scan else None, 'confirmed_photos': counts.get(folder['id'], 0)})
        children = {}
        by_id = {row['id']: row for row in result}
        for row in result:
            children.setdefault(row['parent'], []).append(row['id'])
        for row in result:
            queue, visited, leaves = [row['id']], set(), []
            while queue:
                fid = queue.pop()
                if fid in visited:
                    continue
                visited.add(fid)
                nested = children.get(fid, [])
                if nested:
                    queue.extend(nested)
                else:
                    leaves.append(fid)
            complete = sum(by_id[fid]['status'] == 'Completed' for fid in leaves)
            row.update(direct_subfolders=len(children.get(row['id'], [])),
                       descendant_subfolders=max(0, len(visited)-1), leaf_folders=len(leaves),
                       leaf_completed=complete, completion_percent=round(100*complete/len(leaves)) if leaves else 0)
        return result

    def trail(self, festival, folder):
        nodes = {node['id']: node for node in self.folders(festival)}
        result, visited = [], set()
        while folder in nodes and folder not in visited:
            visited.add(folder)
            result.append(nodes[folder])
            folder = nodes[folder]['parent']
        return list(reversed(result))
