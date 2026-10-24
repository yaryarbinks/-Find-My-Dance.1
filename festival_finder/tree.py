"""A collapsible, clickable folder diagram; counts come from the database."""
from html import escape
import hashlib
from urllib.parse import urlencode


def folder_complete(row, branch=False):
    if branch:
        return (row.get('leaf_folders', 0) > 0 and
                row.get('leaf_completed', 0) == row['leaf_folders'] and
                row['status'] != 'Needs attention')
    return row['status'] == 'Completed'


def render_folder_tree(st, festival, rows, selected, on_select):
    """Use app buttons instead of hyperlinks, preserving the browser session."""
    st.markdown('''<style>
    [class*="st-key-tree-completed-"]{background:#16653426;border:1px solid #39a866;border-radius:10px;padding:6px}
    [class*="st-key-tree-completed-"] button,
    [class*="st-key-tree-completed-"] summary{background:#166534!important;color:#f0fff4!important;border-color:#4ade80!important}
    [class*="st-key-tree-completed-"] button:hover{background:#15803d!important}
    [class*="st-key-tree-completed-"] button[kind="primary"]{outline:2px solid #a7f3d0;outline-offset:2px}
    </style>''', unsafe_allow_html=True)
    children, by_id = {}, {row['id']: row for row in rows}
    for row in rows:
        children.setdefault(row['parent'], []).append(row)
    opened, cursor = set(), selected
    while cursor in by_id and cursor not in opened:
        opened.add(cursor)
        cursor = by_id[cursor]['parent']

    def render(parent, visited):
        for row in children.get(parent, []):
            if row['id'] in visited:
                continue
            fid = row['id']
            complete = folder_complete(row, bool(children.get(fid)))
            icon = '✅' if complete else ('⚠️' if row['status'] == 'Needs attention' else '📁')
            key = hashlib.sha256(f'{festival}:{fid}'.encode()).hexdigest()[:16]
            with st.container(key=f"tree-{'completed' if complete else 'pending'}-{key}"):
                if children.get(fid):
                    status = f"{len(children[fid])} subfolders · {row['leaf_completed']}/{row['leaf_folders']} finished · {row['completion_percent']}%"
                    with st.expander(f"{icon} {row['name']} · {status}",
                                     expanded=row['parent'] is None or fid in opened,
                                     key=f'tree-branch-{festival}-{fid}'):
                        st.button(f"{'✓ Selected' if fid == selected else 'Choose folder'}: {row['name']}",
                                  key=f'tree-select-{festival}-{fid}', on_click=on_select, args=(fid,),
                                  type='primary' if fid == selected else 'secondary')
                        render(fid, visited | {fid})
                else:
                    counts = f"{row['files_checked']}/{row['files_total']} checked · {row['confirmed_photos']} confirmed" if row['files_total'] is not None else 'Not reviewed'
                    st.button(f"{'✓ Selected' if fid == selected else icon} {row['name']} · {counts}",
                              key=f'tree-select-{festival}-{fid}', on_click=on_select, args=(fid,),
                              type='primary' if fid == selected else 'secondary')
    render(None, set())


def folder_tree_html(festival, rows, selected=None):
    children = {}
    for row in rows:
        children.setdefault(row['parent'], []).append(row)
    by_id = {row['id']: row for row in rows}
    opened = set()
    cursor = selected
    while cursor in by_id and cursor not in opened:
        opened.add(cursor)
        cursor = by_id[cursor]['parent']

    def render(parent, visited):
        result = '<ul>'
        for row in children.get(parent, []):
            if row['id'] in visited:
                continue
            url = '?' + urlencode({'festival': festival, 'folder': row['id']})
            complete = row['status'] == 'Completed'
            icon = '✅' if complete else ('⚠️' if row['status'] == 'Needs attention' else '📁')
            counts = f"{row['files_checked']} / {row['files_total']} checked · {row['confirmed_photos']} confirmed photos" if row['files_total'] is not None else 'Not scanned'
            if row.get('direct_subfolders'):
                counts = f"{row['direct_subfolders']} subfolders · {row['leaf_completed']} / {row['leaf_folders']} leaf folders finished ({row['completion_percent']}%)"
            selected_class = ' selected' if row['id'] == selected else ''
            node = f'<a class="folder-node{selected_class}" href="{escape(url, quote=True)}" target="_self">{icon} {escape(row["name"])}<span>{escape(counts)}</span></a>'
            result += '<li>'
            if row['id'] in children:
                expanded = ' open' if row['parent'] is None or row['id'] in opened else ''
                result += f'<details{expanded}><summary>{node}</summary>'
                result += render(row['id'], visited | {row['id']}) + '</details>'
            else:
                result += node
            result += '</li>'
        return result + '</ul>'

    return '''<style>
    .festival-tree {overflow-x:auto;padding:12px 0;max-height:650px;overflow-y:auto}
    .festival-tree ul {list-style:none!important;margin:0 0 0 20px!important;padding:0 0 0 22px!important;border-left:2px solid #75819855}
    .festival-tree>ul {border-left:0;margin-left:0!important;padding-left:0!important}
    .festival-tree li {position:relative;padding:6px 0!important}
    .festival-tree li:before {content:'';position:absolute;left:-22px;top:24px;width:22px;border-top:2px solid #75819855}
    .festival-tree>ul>li:before {display:none}
    a.folder-node {display:inline-block;padding:8px 14px;border:1px solid #75819866;border-radius:10px;text-decoration:none!important;color:inherit!important;min-width:180px}
    a.folder-node:hover {border-color:#55b2ff;background:#55b2ff18}
    a.folder-node.selected {border:2px solid #55b2ff;background:#55b2ff18}
    a.folder-node span {display:block;font-size:12px;opacity:.75;margin-top:3px}
    .festival-tree summary {cursor:pointer;list-style:disclosure-closed}
    .festival-tree details[open]>summary {list-style:disclosure-open}
    .festival-tree summary a {vertical-align:middle}
    </style><div class="festival-tree">''' + render(None, set()) + '</div>'
