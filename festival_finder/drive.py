"""Read-only Google Drive access. Tokens belong to this local app only."""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

FOLDER = 'application/vnd.google-apps.folder'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']


def folder_id(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r'[A-Za-z0-9_-]{10,}', value):
        return value
    parsed = urlparse(value)
    if parsed.scheme != 'https' or parsed.hostname not in {'drive.google.com', 'www.drive.google.com'}:
        raise ValueError('Enter a Google Drive folder link or folder ID.')
    match = re.search(r'/folders/([A-Za-z0-9_-]+)', parsed.path)
    candidate = match.group(1) if match else parse_qs(parsed.query).get('id', [''])[0]
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,}', candidate):
        raise ValueError('The link does not contain a valid folder ID.')
    return candidate


def connect(credentials_path: Path, token_path: Path):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
    if not credentials or not credentials.valid:
        if not credentials_path.exists():
            raise ValueError('Add a Google Desktop OAuth client file as credentials.json. See README.md.')
        credentials = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES).run_local_server(
            port=0, timeout_seconds=180, access_type='offline', prompt='consent')
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json(), encoding='utf-8')
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


def list_media(service, roots: list[str]) -> list[dict]:
    """Paginate each folder and walk descendants; de-duplicate overlapping roots."""
    queue = []
    for root in roots:
        metadata = service.files().get(fileId=folder_id(root), fields='id,name,mimeType', supportsAllDrives=True).execute()
        if metadata['mimeType'] != FOLDER:
            raise ValueError(f"{metadata['name']} is not a folder.")
        queue.append((metadata['id'], metadata['name']))
    visited, found = set(), {}
    while queue:
        parent, breadcrumb = queue.pop(0)
        if parent in visited:
            continue
        visited.add(parent)
        token = None
        while True:
            page = service.files().list(
                q=f"'{parent}' in parents and trashed = false", pageSize=1000,
                pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
                fields='nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,thumbnailLink,capabilities(canDownload))'
            ).execute()
            for item in page.get('files', []):
                if item['mimeType'] == FOLDER:
                    queue.append((item['id'], f"{breadcrumb}/{item['name']}"))
                elif item['mimeType'].startswith(('image/', 'video/')):
                    item['folder'] = breadcrumb
                    found[item['id']] = item
            token = page.get('nextPageToken')
            if not token:
                break
    return list(found.values())


def thumbnail(service, item: dict) -> bytes:
    """Fetch only Google's preview; never fall back to original media."""
    # Refresh the short-lived URL rather than persisting it in a report.
    metadata = service.files().get(fileId=item['id'], fields='thumbnailLink', supportsAllDrives=True).execute()
    url = metadata.get('thumbnailLink', '')
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not (host.endswith('.googleusercontent.com') or host in {'googleusercontent.com', 'drive.google.com'}):
        raise ValueError('No accessible Google preview. Open the original in Drive; no original was downloaded.')
    for attempt in range(4):
        response, content = service._http.request(url, method='GET')
        if int(response.status) not in {429, 500, 502, 503, 504} or attempt == 3:
            break
        try:
            delay = float(response.get('retry-after', 2**attempt))
        except (ValueError, TypeError):
            delay = 2**attempt
        time.sleep(max(0, min(delay, 10)))
    if int(response.status) != 200:
        raise ValueError(f'Preview unavailable (HTTP {response.status}); no original was downloaded.')
    if not response.get('content-type', '').startswith('image/'):
        raise ValueError('Drive returned an unsupported preview.')
    return content


def browse_folder(service, value: str, page_token=None):
    """Read this folder and one page of its immediate child folders only."""
    fid = folder_id(value)
    metadata = service.files().get(fileId=fid, fields='id,name,mimeType,webViewLink', supportsAllDrives=True).execute()
    if metadata['mimeType'] != FOLDER:
        raise ValueError('Choose a Google Drive folder.')
    page = service.files().list(
        q=f"'{fid}' in parents and trashed = false and mimeType = '{FOLDER}'",
        pageSize=100, pageToken=page_token, orderBy='name',
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields='nextPageToken,files(id,name,webViewLink)').execute()
    return metadata, page.get('files', []), page.get('nextPageToken')


def media_batch(service, fid: str, size: int, page_token=None, breadcrumb=''):
    """Read one bounded media page; never traverse descendants."""
    fid = folder_id(fid)
    if not 1 <= size <= 100:
        raise ValueError('Choose a batch size between 1 and 100.')
    page = service.files().list(
        q=f"'{fid}' in parents and trashed = false and (mimeType contains 'image/' or mimeType contains 'video/')",
        pageSize=size, pageToken=page_token, orderBy='name',
        supportsAllDrives=True, includeItemsFromAllDrives=True,
        fields='nextPageToken,files(id,name,mimeType,size,modifiedTime,webViewLink,capabilities(canDownload))').execute()
    items = page.get('files', [])
    for item in items:
        item['folder'] = breadcrumb
    return items, page.get('nextPageToken')


def folder_media(service, fid: str, breadcrumb=''):
    """List all direct media children, using small metadata pages only."""
    items, seen_ids, seen_tokens = [], set(), set()
    token = None
    while True:
        batch, next_token = media_batch(service, fid, 100, token, breadcrumb)
        for item in batch:
            if item['id'] not in seen_ids:
                seen_ids.add(item['id'])
                items.append(item)
        if not next_token:
            return items
        if next_token in seen_tokens:
            raise ValueError('Google repeated a folder page token; retry the folder scan.')
        seen_tokens.add(next_token)
        token = next_token


def folder_tree(service, root_value, progress=None):
    """Inventory folder names only; never request media or thumbnails."""
    root, _, _ = browse_folder(service, root_value)
    queue = [(root['id'], None, root['name'], root['name'])]
    nodes, visited = [], set()
    while queue:
        fid, parent, name, path = queue.pop(0)
        if fid in visited:
            continue
        visited.add(fid)
        nodes.append({'id': fid, 'parent': parent, 'name': name, 'path': path})
        if progress:
            progress(path)
        token = None
        while True:
            _, children, token = browse_folder(service, fid, token)
            queue.extend((child['id'], fid, child['name'], f"{path} / {child['name']}") for child in children)
            if not token:
                break
    return root, nodes


def download(service, item: dict, directory: Path) -> Path:
    from googleapiclient.http import MediaIoBaseDownload
    if item.get('capabilities', {}).get('canDownload') is False:
        raise ValueError('The owner has disabled downloads for this file.')
    # Never use remote names as local paths.
    suffix = Path(item['name']).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,10}', suffix):
        suffix = '.media'
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{item['id']}{suffix}"
    temporary = target.with_suffix(target.suffix + '.part')
    try:
        with temporary.open('wb') as stream:
            downloader = MediaIoBaseDownload(stream, service.files().get_media(fileId=item['id'], supportsAllDrives=True))
            done = False
            while not done:
                _, done = downloader.next_chunk(num_retries=3)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target
