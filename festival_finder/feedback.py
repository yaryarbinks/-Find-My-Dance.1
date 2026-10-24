"""A local, reversible bank of explicitly reviewed face examples."""
import json
import hashlib
import sqlite3
from pathlib import Path

import numpy as np


class Feedback:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS reviews (sample TEXT PRIMARY KEY, label TEXT NOT NULL, embedding TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS reference_photos (id TEXT PRIMARY KEY, name TEXT NOT NULL, original BLOB NOT NULL, crop BLOB NOT NULL, embedding TEXT NOT NULL)')

    def connection(self):
        return sqlite3.connect(self.path)

    def set(self, sample: str, label: str, embedding):
        if label not in {'me', 'not_me'}:
            raise ValueError('Unknown review label.')
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size != 128 or not np.all(np.isfinite(vector)) or not np.isclose(np.linalg.norm(vector), 1, atol=.01):
            raise ValueError('Invalid face embedding for review.')
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO reviews VALUES (?, ?, ?)', (sample, label, json.dumps(vector.tolist())))

    def undo(self, sample):
        with self.connection() as db:
            db.execute('DELETE FROM reviews WHERE sample = ?', (sample,))

    def labels(self):
        with self.connection() as db:
            return dict(db.execute('SELECT sample, label FROM reviews'))

    def examples(self, label):
        with self.connection() as db:
            rows = db.execute('SELECT embedding FROM reviews WHERE label = ?', (label,)).fetchall()
        return np.asarray([json.loads(row[0]) for row in rows], dtype=np.float32).reshape(-1, 128)

    def save_reference(self, name, original, crop, embedding):
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size != 128 or not np.all(np.isfinite(vector)) or not np.isclose(np.linalg.norm(vector), 1, atol=.01):
            raise ValueError('Invalid reference face embedding.')
        identifier = hashlib.sha256(original).hexdigest()
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO reference_photos VALUES (?, ?, ?, ?, ?)',
                       (identifier, name, original, crop, json.dumps(vector.tolist())))
        return identifier

    def references(self):
        with self.connection() as db:
            rows = db.execute('SELECT id, name, crop FROM reference_photos ORDER BY rowid').fetchall()
        return [{'id': row[0], 'name': row[1], 'crop': row[2]} for row in rows]

    def reference_examples(self):
        with self.connection() as db:
            rows = db.execute('SELECT embedding FROM reference_photos ORDER BY rowid').fetchall()
        return np.asarray([json.loads(row[0]) for row in rows], dtype=np.float32).reshape(-1, 128)

    def remove_reference(self, identifier):
        with self.connection() as db:
            db.execute('DELETE FROM reference_photos WHERE id = ?', (identifier,))


def candidate_score(feature, references, negatives, threshold):
    positive = float(np.max(references @ feature))
    negative = float(np.max(negatives @ feature)) if negatives is not None and len(negatives) else -1.
    # Negative feedback vetoes only when it is more similar by a margin.
    return positive, positive >= threshold and negative < positive + .03
