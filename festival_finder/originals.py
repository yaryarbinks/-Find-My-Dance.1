"""Original-quality media is loaded only following an explicit user click."""
import hashlib
import re
import zipfile
from pathlib import Path

from festival_finder import drive


def load_original(service, item, directory):
    metadata = service.files().get(fileId=item['id'], supportsAllDrives=True,
        fields='id,name,mimeType,size,modifiedTime,capabilities(canDownload)').execute()
    if not metadata['mimeType'].startswith('image/'):
        raise ValueError('This action supports original photos. Open videos in Drive to download them.')
    if metadata.get('capabilities', {}).get('canDownload') is False:
        raise ValueError('The photographer has disabled original downloads.')
    version = hashlib.sha256(str(metadata.get('modifiedTime', '')).encode()).hexdigest()[:16]
    directory = Path(directory) / version
    suffix = Path(metadata['name']).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,10}', suffix):
        suffix = '.media'
    path = directory / f"{metadata['id']}{suffix}"
    if not path.exists():
        path = drive.download(service, metadata, directory)
    return path, metadata['name']


def build_zip(service, items, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256('|'.join(sorted(item['id'] for item in items)).encode()).hexdigest()
    target = directory / f'confirmed-{key}.zip'
    temp = target.with_suffix('.part')
    errors, included = [], 0
    try:
        with zipfile.ZipFile(temp, 'w', compression=zipfile.ZIP_STORED) as archive:
            for item in items:
                try:
                    path, name = load_original(service, item, directory / 'photos')
                    safe_name = re.sub(r'[^\w. -]', '_', Path(name.replace('\\', '/')).name)
                    archive.write(path, f"{item['id']}-{safe_name}")
                    included += 1
                except Exception as exc:
                    errors.append({'name': item['name'], 'reason': str(exc)})
        if included:
            temp.replace(target)
        return target if included else None, errors
    finally:
        temp.unlink(missing_ok=True)
