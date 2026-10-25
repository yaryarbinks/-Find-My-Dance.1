"""Manual review of saved photo sequences, without recognition or rescanning."""
import hashlib
import re
from pathlib import Path


def photo_sequence(report):
    def natural(item):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r'(\d+)', item.get('name', '')))
    return sorted((item for item in report.get('matches', []) if not item.get('video')), key=natural)


def media_sequence(report):
    def natural(item):
        return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                     for part in re.split(r'(\d+)', item.get('name', '')))
    return sorted(report.get('matches', []), key=natural)


def candidate_similarity(item):
    scores = [face['score'] for hit in item.get('hits', []) for face in hit.get('faces', [])
              if face.get('candidate') and isinstance(face.get('score'), (int, float))]
    return max(scores) if scores else None


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
        available = [r for r in reports if r.get('matches')]
        if not available:
            st.info('No saved photo or video previews are available for this festival.')
            return
        reports_by_folder = {report['folder_id']: report for report in available}
        options = list(reports_by_folder)
        target = st.session_state.get('manual_review_folder') or st.query_params.get('folder')
        default = [target] if target in reports_by_folder else options
        selected_folders = st.multiselect(
            'Folders to review',
            options,
            default=default,
            format_func=lambda fid: names.get(fid, reports_by_folder[fid].get('selected_folder', fid)),
            key='review-folders')
        view = st.radio(
            'Saved result view',
            ['Saved suggestions', 'All saved media', 'Awaiting review', 'Media with detected faces',
             'Confirmed photos', 'Not in this photo'],
            horizontal=True,
            key='folder-review-view-v2')
        selected_reports = [reports_by_folder[fid] for fid in selected_folders]
        entries = []
        coverage = []
        for report in sorted(selected_reports, key=lambda row: names.get(row['folder_id'], row.get('selected_folder', ''))):
            items = media_sequence(report)
            photo_labels = projects.photo_labels(report['festival_id'], report['folder_id'])
            confirmed_ids = {item['id'] for item in projects.confirmed(report, labels)}
            if view == 'Awaiting review':
                items = [item for item in items if item['id'] not in photo_labels]
            elif view == 'Saved suggestions':
                items = [item for item in items if any(
                    face.get('candidate', False) for hit in item.get('hits', []) for face in hit.get('faces', []))]
            elif view == 'Media with detected faces':
                items = [item for item in items if item.get('detected_faces') or any(
                    hit.get('faces') for hit in item.get('hits', []))]
            elif view == 'Confirmed photos':
                items = [item for item in items if item['id'] in confirmed_ids and not item.get('video')]
            elif view == 'Not in this photo':
                items = [item for item in items if photo_labels.get(item['id']) == 'not_me']
            entries.extend((report, item, '') for item in items)
            all_items = media_sequence(report)
            coverage.append({
                'Folder': names.get(report['folder_id'], report.get('selected_folder', report['folder_id'])),
                'Files checked': f"{report.get('processed', 0)} / {report.get('total_discovered', 0)}",
                'Saved previews': len(all_items),
                'Photos': sum(not item.get('video') for item in all_items),
                'Video previews': sum(bool(item.get('video')) for item in all_items),
                'Errors': len(report.get('errors', [])),
            })
        total_checked = sum(report.get('processed', 0) for report in selected_reports)
        total_expected = sum(report.get('total_discovered', 0) for report in selected_reports)
        total_errors = sum(len(report.get('errors', [])) for report in selected_reports)
        saved_media = sum(len(report.get('matches', [])) for report in selected_reports)
        suggestion_count = sum(
            candidate_similarity(item) is not None
            for report in selected_reports for item in report.get('matches', []))
        st.caption(f'{len(selected_reports)} of {len(available)} scanned folders selected · '
                   f'{total_checked} / {total_expected} files checked · {saved_media} saved previews · '
                   f'{suggestion_count} recognition suggestions · {total_errors} file errors. '
                   'No scan or download runs from this page.')
        with st.expander('Scan coverage by folder'):
            st.dataframe(coverage, hide_index=True, use_container_width=True)
        if not selected_reports:
            st.info('Select one or more folders to review.')
            return
        if not entries:
            st.info('No saved media matches this review view in the selected folders. Recognition suggestions show only faces above the selected similarity cutoff.')
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
        st.caption('Two photos before and two after each confirmed photo, ordered by filename within the same folder. Confirming a nearby photo expands the review around it, so you can keep following the sequence. Rejected photos stay marked for reference but do not expand it. This is approximate filename order, not verified capture time.')
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
    st.caption(f'{len(entries)} item(s) in this view · {(len(entries)+11)//12} review page(s) at 12 per page.')
    page = st.number_input('Review page (12 items)', 1, max(1, (len(entries)+11)//12), 1, key=f'review-page-{mode}-{len(entries)}')
    for report, item, context in entries[(page-1)*12:page*12]:
        festival_id, folder_id = report['festival_id'], report['folder_id']
        with st.container(border=True):
            label = projects.photo_labels(festival_id, folder_id).get(item['id'])
            widget = f"photo-{mode}-{festival_id}-{folder_id}-{item['id']}"
            preview = next((hit['preview'] for hit in item.get('hits', []) if Path(hit.get('preview', '')).is_file()), None)
            if label in {'me', 'not_me'}:
                thumb, title, undo = st.columns([1, 4, 2])
                if preview:
                    thumb.image(preview, width=96)
                title.write(f"**{item['name']}**")
                title.caption('✓ Saved: you are in this photo' if label == 'me'
                              else '✓ Saved: not in this photo')
                if undo.button('Undo', key=f'{widget}-compact-undo'):
                    projects.review_photo(festival_id, folder_id, item['id'], None)
                    st.session_state['photo-review-notice'] = f"Undone: {item['name']}"
                    st.rerun()
                with st.expander('Reopen confirmed photo' if label == 'me' else 'Reopen rejected photo'):
                    if preview:
                        st.image(preview, width=640)
                    if item.get('url'):
                        st.link_button('View original in Drive', item['url'])
                    replacement = 'not_me' if label == 'me' else 'me'
                    action = 'Not in this photo' if label == 'me' else "I'm in this photo instead"
                    if st.button(action, key=f'{widget}-correct-{replacement}'):
                        projects.review_photo(festival_id, folder_id, item['id'], replacement)
                        decision = 'not in this photo' if replacement == 'not_me' else 'you are in this photo'
                        st.session_state['photo-review-notice'] = f"Saved: {item['name']} — {decision}."
                        st.rerun()
                continue
            st.subheader(item['name'])
            similarity = candidate_similarity(item)
            if similarity is not None:
                st.caption(f'Recognition suggestion · similarity {similarity:.2f} (not a probability)')
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
