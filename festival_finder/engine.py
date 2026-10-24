from __future__ import annotations

import hashlib
import json
import math
import urllib.request
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np

from festival_finder.feedback import candidate_score

MODEL_FILES = {
    'detector': ('face_detection_yunet', 'face_detection_yunet_2023mar.onnx'),
    'recognizer': ('face_recognition_sface', 'face_recognition_sface_2021dec.onnx'),
}
IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tif', '.tiff'}
VIDEO_SUFFIXES = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.webm'}


def ensure_models(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind, (folder, filename) in MODEL_FILES.items():
        target = directory / filename
        if not target.exists():
            url = f'https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/{folder}/{filename}'
            temporary = target.with_suffix('.part')
            try:
                with urllib.request.urlopen(url, timeout=90) as response, temporary.open('wb') as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                if temporary.stat().st_size < 10000:
                    raise ValueError(f'Model download failed: {filename}')
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        paths[kind] = target
    return paths


def decode_image(raw: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Unsupported or unreadable image. Convert HEIC/RAW files to JPEG first.')
    return image


def normalize(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError('Invalid face embedding.')
    return vector / norm


class FaceEngine:
    def __init__(self, directory: Path):
        paths = ensure_models(directory)
        self.detector = cv2.FaceDetectorYN.create(str(paths['detector']), '', (320, 320), 0.8, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(str(paths['recognizer']), '')

    def faces(self, image: np.ndarray, max_side: int = 1920) -> list[tuple]:
        height, width = image.shape[:2]
        scale = min(1.0, max_side / max(width, height))
        resized = cv2.resize(image, (round(width * scale), round(height * scale))) if scale < 1 else image
        self.detector.setInputSize((resized.shape[1], resized.shape[0]))
        _, rows = self.detector.detect(resized)
        found = []
        for row in rows if rows is not None else []:
            row = row.copy()
            row[:14] /= scale
            if min(row[2:4]) < 20:
                continue
            aligned = self.recognizer.alignCrop(image, row)
            feature = normalize(self.recognizer.feature(aligned))
            found.append((row, feature, aligned))
        return found

    def enroll(self, raw: bytes) -> tuple[np.ndarray, np.ndarray]:
        found = self.faces(decode_image(raw))
        if len(found) != 1:
            raise ValueError(f'Found {len(found)} faces. Use a clear photo showing only your face, or crop it first.')
        _, feature, crop = found[0]
        return feature, crop

    def score_frame(self, image, references, threshold):
        matches = []
        for row, feature, _ in self.faces(image):
            score = float(np.max(references @ feature))
            if score >= threshold:
                matches.append({'score': round(score, 4), 'box': [int(v) for v in row[:4]]})
        return sorted(matches, key=lambda item: item['score'], reverse=True)


def scan_preview(engine, raw, references, negatives, threshold, output: Path):
    """Keep the small preview and aligned face chips, never the original."""
    image = decode_image(raw)
    output.mkdir(parents=True, exist_ok=True)
    faces = []
    for number, (row, feature, crop) in enumerate(engine.faces(image)):
        score, candidate = candidate_score(feature, references, negatives, threshold)
        chip = output / f'face-{number}.jpg'
        if not cv2.imwrite(str(chip), crop):
            raise ValueError('Could not save face preview.')
        faces.append({'score': round(score, 4), 'candidate': candidate,
                      'embedding': feature.tolist(), 'crop': str(chip.resolve()),
                      'box': [int(v) for v in row[:4]]})
    preview = output / 'preview.jpg'
    if not cv2.imwrite(str(preview), image):
        raise ValueError('Could not save preview.')
    return [{'timestamp': None, 'score': max((f['score'] for f in faces), default=0),
             'faces': faces, 'preview': str(preview.resolve())}]


def frames(path: Path, is_video: bool, interval: float):
    if not is_video:
        yield None, decode_image(path.read_bytes())
        return
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError('Video interval must be positive.')
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise ValueError('Unsupported or unreadable video.')
        fps = capture.get(cv2.CAP_PROP_FPS)
        count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count <= 0:
            raise ValueError('Video has no reliable frame rate or duration metadata.')
        step = max(1, round(fps * interval))
        for index in range(0, int(count), step):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, image = capture.read()
            if not ok:
                raise ValueError(f'Could not decode video at {index / fps:.2f}s; scan incomplete.')
            yield round(index / fps, 3), image
    finally:
        capture.release()


def scan_file(engine, path: Path, is_video: bool, references: np.ndarray,
              threshold: float, interval: float, output: Path, progress=None) -> list[dict]:
    output.mkdir(parents=True, exist_ok=True)
    hits = []
    for number, (timestamp, image) in enumerate(frames(path, is_video, interval)):
        if progress:
            progress(timestamp)
        matches = engine.score_frame(image, references, threshold)
        if not matches:
            continue
        preview = image.copy()
        for match in matches:
            x, y, width, height = match['box']
            cv2.rectangle(preview, (x, y), (x + width, y + height), (80, 230, 90), 3)
        scale = min(1.0, 960 / max(preview.shape[:2]))
        preview = cv2.resize(preview, (round(preview.shape[1] * scale), round(preview.shape[0] * scale)))
        target = output / f'{number}.jpg'
        if not cv2.imwrite(str(target), preview):
            raise ValueError('Could not save preview.')
        hits.append({'timestamp': timestamp, 'score': matches[0]['score'],
                     'faces': matches, 'preview': str(target.resolve())})
    return hits


def cache_key(identity: dict, references, threshold, interval) -> str:
    payload = json.dumps({'version': 2, 'identity': identity, 'threshold': threshold,
                          'interval': interval, 'models': MODEL_FILES}, sort_keys=True).encode()
    return hashlib.sha256(payload + np.asarray(references, dtype=np.float32).tobytes()).hexdigest()


def save_report(path: Path, report: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Windows readers/antivirus can briefly lock a target during atomic replace.
    # Use a unique temporary file and retry sharing violations without losing scan progress.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix=path.stem+'-', suffix='.part', delete=False) as stream:
        json.dump(report, stream, indent=2)
        temporary = Path(stream.name)
    try:
        for attempt in range(30):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 29:
                    raise
                time.sleep(min(.02 * (attempt+1), .1))
    finally:
        temporary.unlink(missing_ok=True)
