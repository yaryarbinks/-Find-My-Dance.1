"""Manual review of saved photo sequences, without recognition or rescanning."""
import hashlib
import re
from pathlib import Path


def photo_sequence(report):
    def natural(item):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r'(\d+)', item.get('name', '')))
    return sorted((item for item in report.get('matches', []) if not item.get('video')), key=natural)


def nearby_photos(report, confirmed, radius=2):
    sequence = photo_sequence(report)
    anchors = {item['id'] for item in confirmed}
    neighbors = {}
    for index, anchor in enumerate(sequence):
        if anchor['id'] not in anchors:
            continue
        for position in range(max(0, index-radius), min(len(sequence), index+radius+1)):
            item = sequence[position]
            if item['id'] in anchors:
                continue
            neighbors.setdefault(item['id'], {'item': item, 'near': []})['near'].append(
                {'name': anchor['name'], 'offset': position-index})
    return list(neighbors.values())


def nearby_review_rows(report, confirmed, photo_labels):
    """Keep manually reviewed cards visible after they become new anchors."""
    neighbors = {row['item']['id']: row for row in nearby_photos(report, confirmed)}
    return [neighbors.get(item['id'], {'item': item, 'near': []})
            for item in photo_sequence(report)
            if item['id'] in neighbors or item['id'] in photo_labels]


def render_photo_page(st, projects, feedback, data, root, mode):
    from festival_finder import drive
    from festival_finder.originals import build_zip

    st.header(mode)
    notice = st.session_state.pop('photo-review-notice', None)
    if notice:
        st.success(notice)
        st.toast(notice, icon='✅')
    st.caption('Uses saved previews only. Opening this page does not scan or download originals.')
    festivals = projects.festivals()
    if not festivals:
        st.info('Open a festival and save a folder scan first.')
        return
    festival = st.selectbox('Festival project', festivals, format_func=lambda f: f['name'], key='review-festival')
    names = {row['id']: row['path'] for row in projects.folders(festival['id'])}
    reports = projects.reports(festival['id'])
    labels = feedback.labels()
    confirmed = [(report, item) for report in reports for item in projects.confirmed(report, labels)
                 if not item.get('video')]
    st.metric('Confirmed photos in this festival', len({item['id'] for _, item in confirmed}))

    if mode == 'Folder review':
        available = [r for r in reports if any(not item.get('video') for item in r.get('matches', []))]
        if not available:
            st.info('No saved photo previews are available for this festival.')
            return
        options = [r['folder_id'] for r in available]
        target = st.session_state.get('manual_review_folder') or st.query_params.get('folder')
        folder = st.selectbox('Saved result folder', options, index=options.index(target) if target in options else 0,
                              format_func=lambda fid: names.get(fid, fid), key='saved-review-folder')
        report = next(r for r in available if r['folder_id'] == folder)
        photos = photo_sequence(report)
        view = st.radio('Saved photo view', ['Saved suggestions', 'Photos with detected faces', 'All saved photos', 'Confirmed photos'], horizontal=True)
        confirmed_ids = {item['id'] for item in projects.confirmed(report, labels)}
        suggestions = [item for item in photos if any(face.get('candidate', False)
                        for hit in item.get('hits', []) for face in hit.get('faces', []))]
        if view == 'Saved suggestions':
            photos = suggestions
        elif view == 'Photos with detected faces':
            photos = [item for item in photos if item.get('detected_faces')]
        elif view == 'Confirmed photos':
            photos = [item for item in photos if item['id'] in confirmed_ids]
        st.caption(f"{report.get('processed', 0)} of {report.get('total_discovered', 0)} files were recorded in this saved report. This view does not run recognition again.")
        if view == 'Saved suggestions' and not suggestions:
            st.info('This saved report has no suggested photos. Choose All saved photos to inspect the existing previews.')
        entries = [(report, item, '') for item in photos]
    elif mode == 'Confirmed photos':
        st.caption('Your confirmed collection across all saved folders. Originals stay in Drive until you request a download.')
        items = list({item['id']: item for _, item in confirmed if item.get('url')}.values())
        key = hashlib.sha256('|'.join(sorted(item['id'] for item in items)).encode()).hexdigest()
        target = data / 'originals' / f'confirmed-{key}.zip'
        if items and st.button('Prepare original-quality ZIP', key='collection-zip'):
            try:
                with st.spinner('Preparing only your confirmed original photos…'):
                    service = drive.connect(root / 'credentials.json', data / 'token.json')
                    _, failures = build_zip(service, items, data / 'originals')
                if failures:
                    st.warning(f'{len(failures)} originals could not be downloaded. The ZIP contains successful downloads only.')
            except Exception as exc:
                st.error(str(exc))
        if items and target.exists():
            st.download_button('Download confirmed originals ZIP', target.read_bytes(), 'my-confirmed-photos.zip', 'application/zip')
        entries = [(report, item, '') for report, item in confirmed]
    else:
        st.caption('Two photos before and two after each confirmed photo, ordered by filename within the same folder. This is approximate sequence order, not verified capture time. New confirmations can reveal further neighbors.')
        available = [report for report in reports if projects.confirmed(report, labels)]
        if not available:
            st.info('Confirm a photo first to use it as a starting point.')
            return
        scope = st.selectbox('Folder scope', ['all'] + [r['folder_id'] for r in available],
                             format_func=lambda fid: 'All folders with confirmed photos' if fid == 'all' else names.get(fid, fid),
                             key='neighbor-folder-scope')
        selected_reports = [r for r in available if scope == 'all' or r['folder_id'] == scope]
        entries, pending = [], 0
        for report in sorted(selected_reports, key=lambda r: names.get(r['folder_id'], '')):
            photo_labels = projects.photo_labels(report['festival_id'], report['folder_id'])
            for row in nearby_review_rows(report, projects.confirmed(report, labels), photo_labels):
                context = '; '.join(f"{abs(near['offset'])} {'before' if near['offset'] < 0 else 'after'} {near['name']}" for near in row['near'])
                entries.append((report, row['item'], context))
                pending += row['item']['id'] not in photo_labels
        st.caption(f'{len(selected_reports)} saved folder(s) included. Nearby photos refresh from your saved confirmations whenever this page opens or you make a review decision; no extra scan is needed.')
        st.write(f'{pending} photos awaiting review · {len(entries)-pending} reviewed cards.')
        st.caption('Confirmed cards stay marked green. Rejected cards shrink to a thumbnail and filename; reopen or undo them anytime.')

    if not entries:
        st.info('No photos in this view yet.')
        return
    page = st.number_input('Review page (12 photos)', 1, max(1, (len(entries)+11)//12), 1, key=f'review-page-{mode}-{len(entries)}')
    for report, item, context in entries[(page-1)*12:page*12]:
        festival_id, folder_id = report['festival_id'], report['folder_id']
        with st.container(border=True):
            label = projects.photo_labels(festival_id, folder_id).get(item['id'])
            widget = f"photo-{mode}-{festival_id}-{folder_id}-{item['id']}"
            preview = next((hit['preview'] for hit in item.get('hits', []) if Path(hit.get('preview', '')).is_file()), None)
            if label == 'not_me':
                thumb, title, undo = st.columns([1, 4, 2])
                if preview:
                    thumb.image(preview, width=96)
                title.write(f"**{item['name']}**")
                title.caption('✓ Saved: not in this photo')
                if undo.button('Undo', key=f'{widget}-compact-undo'):
                    projects.review_photo(festival_id, folder_id, item['id'], None)
                    st.session_state['photo-review-notice'] = f"Undone: {item['name']}"
                    st.rerun()
                with st.expander('Reopen rejected photo'):
                    if preview:
                        st.image(preview, width=640)
                    if item.get('url'):
                        st.link_button('View original in Drive', item['url'])
                    if st.button("I'm in this photo instead", key=f'{widget}-correct-me'):
                        projects.review_photo(festival_id, folder_id, item['id'], 'me')
                        st.session_state['photo-review-notice'] = f"Saved: {item['name']} — you are in this photo."
                        st.rerun()
                continue
            st.subheader(item['name'])
            if label == 'me':
                st.success('✓ Saved — you confirmed you are in this photo')
            st.caption(names.get(folder_id, folder_id))
            if context:
                st.caption(context)
            if preview:
                st.image(preview, width=640)
            else:
                st.caption('Saved preview unavailable. Use the source link to inspect this photo.')
            if item.get('url'):
                st.link_button('View original in Drive', item['url'])
            st.caption({'me': 'You confirmed you appear in this photo.', 'not_me': 'You marked this photo as not you.'}.get(label, 'No photo-level decision saved.'))
            st.caption('These buttons label the whole photo and do not add face references. Undo restores any earlier face-based confirmation.')
            yes, no, undo = st.columns(3)
            for column, title, value in [(yes, "I'm in this photo", 'me'), (no, 'Not in this photo', 'not_me'), (undo, 'Undo photo decision', None)]:
                selected = value is not None and label == value
                if column.button('✓ Confirmed' if selected else title, key=f'{widget}-{value}',
                                 type='primary' if selected else 'secondary',
                                 disabled=selected or (value is None and label is None)):
                    projects.review_photo(festival_id, folder_id, item['id'], value)
                    decision = {'me': 'you are in this photo', 'not_me': 'not in this photo', None: 'photo decision undone'}[value]
                    st.session_state['photo-review-notice'] = f"Saved: {item['name']} — {decision}."
                    st.rerun()
