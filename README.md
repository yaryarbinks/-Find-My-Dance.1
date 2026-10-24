# Find My Dance

A local festival photo browser with a persistent, photos-only preparation queue and manual review. The current app prepares small Google Drive thumbnails; it does not run face identification or score people.

## Use the app

Run `start.ps1` (Windows) or `./start.sh` (macOS) in this project folder and open http://127.0.0.1:8501.

1. Open a saved festival, or expand **Add a festival / refresh its folder tree** and paste its root Google Drive folder link.
2. Select a folder in the tree. Choose **This folder only**, **This folder and all subfolders**, or **Choose folders inside this branch**.
3. Click **Add to photo queue**, then **Start / resume preparation queue**. Alternatively, **Add and start preparation** does both.
4. The worker prepares one folder at a time in queue order. Photos only: video files are ignored. Empty parent folders finish without downloading media.
5. Open **Review folder** beside a queue entry, or use **Folder review**. Mark whole photos **I'm in this photo**, **Not in this photo**, or undo the decision. Decisions save immediately.
6. **Confirmed photos** collects your saved confirmations for the festival. Request an original-quality ZIP when ready; photographer download restrictions are respected.

The queue is restricted to the selected branch of the loaded festival tree. To queue an entire festival, select its root. To queue one day, select that day. Duplicated queue entries are not added again. Failed entries offer **Retry failed preparation**, which keeps successfully prepared files.

## Background work and recovery

A separate, windowless Python worker processes the queue. An exclusive operating-system lock prevents simultaneous preparation workers. Closing the browser does not cancel preparation, but the computer must remain on.

Each photo's metadata and preview location are checkpointed in SQLite. **Pause after current photo** pauses between files. **Start / resume preparation queue** continues saved work after a pause or process interruption. With the queue enabled, the open folder page can restart an unexpectedly exited preparation worker. Folder-listing failures and individual thumbnail errors are shown; failed entries require retry rather than being silently marked ready.

The top strip shows previews ready, photos awaiting manual review, confirmations for the current folder, and an estimated finish time in Israel. Its read-only service updates every five seconds without starting processing or fetching extra images. It clears the settings sidebar when open. The queue list also refreshes every five seconds on the folder page.

Green tree cards mean preview preparation is complete for that folder or all its leaf folders; green does not mean every photo has been manually reviewed. Legacy completed scan folders also retain their saved completion state.

## Saved data and previous results

Historical reports, confirmations, face-review annotations, reference uploads, original downloads, and festival trees are preserved. The new preparation workflow does not use historical face embeddings. New preview reports are stored separately, and historical confirmations remain available in the confirmed collection.

A local backup of the previous app and database was saved under `data/backups/` when the app was replaced. Backups remain private local files.

**Nearby photos** shows two saved photos before and two after confirmed photos in the same folder, ordered by filename. It defaults to all saved folders with confirmations. New human confirmations are included when opening or reviewing that page. Filename order is approximate and does not guarantee actual capture order.

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
