"""Compact presentation of saved review labels; no recognition work."""
import hashlib
from pathlib import Path

from festival_finder.projects import sample_id


def saved_review_card(st, item, labels, feedback, video_cover=False):
    faces = [(sample_id(item, hit, face), face) for hit in item.get('hits', [])
             for face in hit.get('faces', []) if 'embedding' in face]
    rejected = [(index, sample) for index, (sample, _) in enumerate(faces, 1)
                if labels.get(sample) == 'not_me']
    positive = sum(labels.get(sample) == 'me' for sample, _ in faces)
    unreviewed = sum(sample not in labels for sample, _ in faces)
    complete = bool(faces) and unreviewed == 0
    signature = hashlib.sha256(str([(sample, labels.get(sample)) for sample, _ in faces]).encode()).hexdigest()[:16]
    identity = item.get('review_key') or item.get('id') or item['name']
    if complete:
        with st.container(border=True):
            thumb, title, undo = st.columns([1, 5, 2])
            preview = next((hit.get('preview') for hit in item.get('hits', [])
                            if Path(hit.get('preview', '')).is_file()), None)
            if preview:
                thumb.image(preview, width=80)
            title.write(f"**{item['name']}**")
            title.caption(f'✓ Saved: {len(rejected)} face(s) marked Not me · {positive} confirmed · {unreviewed} unreviewed')
            last = st.session_state.get(f'last-rejected-{identity}')
            decisions = rejected or [(index, sample) for index, (sample, _) in enumerate(faces, 1)]
            index, sample = next(((index, sample) for index, sample in decisions if sample == last), decisions[-1])
            if undo.button('Undo rejection' if rejected else 'Undo confirmation', key=f'compact-undo-{identity}', help=f'Undo decision for face {index}'):
                feedback.undo(sample)
                st.rerun()
        title = f"Reopen {item['name']} / review faces"
    else:
        title = f"{item['name']} · {'video cover only' if video_cover else 'review preview'}"
    return st.expander(title, expanded=not complete, key=f'saved-review-{identity}-{signature}')
