# Find My Dance

A local festival photo browser with manual review and an optional sequential scan queue. Scans use small Google Drive previews for photos and video cover thumbnails; originals are not downloaded during scanning.

## Use the app

Run `start.ps1` (Windows) or `./start.sh` (macOS) in this project folder and open http://127.0.0.1:8501.

1. Open a saved festival, or expand **Add a festival / refresh its folder tree** and paste its root Google Drive folder link.
2. Select a folder in the tree. **Add selected folder + subfolders** adds that folder and every descendant to the scan queue. Multiple selections can be added; duplicates are ignored.
3. Click **Start / resume queue**. A separate worker scans queued folders one at a time and continues if you close the browser. Add a reference photo first.
4. Each queued folder scans its photos and videos directly inside it. Video scans use Google Drive's cover/thumbnail preview. Empty folders are recorded and skipped.
5. **Folder review** selects all scanned folders by default and starts with **Saved suggestions**—only media with a face above the similarity cutoff. Similarity scores are shown as suggestions, not probabilities. Use **All saved media** only if you intentionally want every scanned preview. **Nearby photos** and **Confirmed photos** are also available. Manual photo decisions save immediately.

The **Rescan completed files** option applies to queued folders too. Failed folders remain visible and are retried when you start the queue again.

## Background work and recovery

A separate, windowless Python worker processes the queue sequentially. Closing the browser does not cancel processing, but the computer must remain on.

Folder scans run independently of the browser and process one folder at a time. Closing the browser does not cancel a scan, but the computer must remain on. If the queue worker stops unexpectedly, queued folders remain saved; starting the queue again resumes pending folders and retries failures. Individual file and folder errors are shown in the queue or saved scan report.

The top strip shows previews ready, photos awaiting manual review, confirmations for the current folder, and an estimated finish time in Israel. Its read-only service refreshes scan data every five seconds and updates the estimated time every second without starting processing or fetching extra images. It clears the settings sidebar when open. The queue list also refreshes every five seconds on the folder page.

Green tree cards mean preview preparation is complete for that folder or all its leaf folders; green does not mean every photo has been manually reviewed. Legacy completed scan folders also retain their saved completion state.

## Saved data and previous results

Historical reports, confirmations, face-review annotations, reference uploads, original downloads, and festival trees are preserved. The new preparation workflow does not use historical face embeddings. New preview reports are stored separately, and historical confirmations remain available in the confirmed collection.

A local backup of the previous app and database was saved under `data/backups/` when the app was replaced. Backups remain private local files.

**Nearby photos** shows two saved photos before and two after confirmed photos in the same folder, ordered by filename. Confirming a nearby photo makes it a new anchor and reveals its neighbors, so you can continue through the sequence. Confirmed and rejected cards collapse to thumbnails to leave room for more photos; reopen a card to see the full preview or change/undo its decision. Rejected photos remain marked but do not reveal further neighbors. The page defaults to all saved folders with confirmations. Filename order is approximate and does not guarantee actual capture order.

Photos rejected during manual review shrink to small cards in **All photos** or **Rejected** views. **Awaiting review** shows only undecided photos, so a saved decision moves a photo out of that view. Decisions apply to a whole photo and do not create face references.

## Google Drive setup

1. Enable the Google Drive API in a Google Cloud project.
2. Configure OAuth branding and audience; for a personal account use External and add the account as a test user while testing.
3. Create a Desktop app OAuth client and save its JSON as `credentials.json` in this project folder.
4. On first folder-tree loading or preparation, sign in with the account that can access the festival folder. The token is saved locally in `data/token.json`.

The app uses `drive.readonly`, which permits reading accessible files beyond the pasted folder; the app's queue restricts itself to selected folders in the loaded festival tree. No Drive source files are edited. The chat's connected Drive account and the standalone app have separate authentication.

## Storage

- `data/feedback.sqlite3`: festival inventory, historical reports and decisions, prepared reports, queue entries, file checkpoints and controls.
- `data/photo-queue/previews/`: cached small previews, keyed by source file ID, modification time and size.
- `data/photo-queue/worker.log`: preparation errors; `worker.lock` prevents concurrent workers.
- `data/originals/`: originals and ZIP files explicitly requested by the user.
- `data/token.json` and `credentials.json`: private Google authentication files; never share or commit them.

Ordinary preparation downloads thumbnails only. Some data must transfer to display a preview. Original files are fetched only through explicit download actions. There are no OpenAI API calls in the preparation or review loop; coding and assistant conversations have separate Codex usage. No video-frame review or video identity matching is implemented in this photos-only queue.

## Verification

Run focused checks with `.venv/Scripts/python.exe -m pytest tests/test_photo_queue.py tests/test_manual_app.py tests/test_projects.py tests/test_photo_review.py tests/test_progress_server.py -q`.

Tests cover branch scope, queue order and deduplication, an exclusive worker lock, photos-only thumbnail access, sequential background processing without a browser, pause/resume, retry cache reuse, preservation of historical confirmations, manual review persistence and read-only progress updates. No live festival face matching is performed by these tests or the new workflow.
