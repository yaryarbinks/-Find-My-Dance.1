"""Read-only progress API and a stable browser panel with incremental DOM updates."""
import hashlib
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from festival_finder.jobs import current_job
from festival_finder.live import read_snapshot, live_stats
from festival_finder.timing import duration_text


HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark}body{font:15px system-ui,sans-serif;margin:0;padding:12px;overflow-anchor:none;background:transparent;color:light-dark(#202938,#e9edf4)}
h2{font-size:18px;margin:0 0 10px;overflow-wrap:anywhere}#status{margin:8px 0 18px;color:light-dark(#356a51,#8ad6ac)}
.metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.label{font-size:13px;opacity:.75}.value{font-size:28px;font-variant-numeric:tabular-nums;min-height:40px}
.track{height:7px;background:#8090a433;border-radius:10px;margin:12px 0}.bar{height:100%;width:0;background:#3aa6d8;border-radius:10px;transition:width .3s}
.note{font-size:12px;opacity:.7;margin:10px 0}.photos{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.photo img{width:100%;height:180px;object-fit:contain;border-radius:8px;background:#8090a415}.photo p{font-size:12px;overflow-wrap:anywhere}.photo a{color:light-dark(#135caa,#8dc2ff)}
@media(max-width:600px){.metrics{gap:8px}.value{font-size:22px}.photos{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style></head><body>
<h2 id="folder">Background scan</h2><p id="status">Connecting to progress…</p>
<div class="metrics"><div><div class="label">Files checked so far</div><div id="checked" class="value">—</div></div><div><div class="label">Possible matches (automatic)</div><div id="possible" class="value">—</div></div><div><div class="label">Photos confirmed by you</div><div id="confirmed" class="value">—</div></div></div>
<div class="track" role="progressbar" aria-label="Scan progress" aria-valuemin="0" aria-valuemax="100"><div class="bar" id="bar"></div></div>
<p id="timing" class="note"></p><p id="errors" class="note"></p>
<p class="note">Possible matches are unverified suggestions. Only your “That’s me” decisions count as confirmed. Updates change in place without reloading the page.</p>
<h3>Latest possible matches</h3><div id="empty" class="note">No automatic candidates found so far.</div><div id="photos" class="photos"></div>
<p class="note">Up to six recent previews. Review faces in the main app; this panel does not start, stop, or restart scans.</p>
<script>
let photoKey='';let busy=false;
function text(id,value){const node=document.getElementById(id);const next=String(value);if(node.textContent!==next)node.textContent=next;}
async function update(){if(busy)return;busy=true;try{
 const response=await fetch('/progress',{cache:'no-store'});if(!response.ok)throw Error('Progress unavailable');const data=await response.json();
 text('folder',data.folder);text('status',data.status);text('checked',data.processed+' / '+data.total);text('possible',data.possible);text('confirmed',data.confirmed);text('timing',data.timing);text('errors',data.errors?data.errors+' file error(s)':'');
 const width=data.total?Math.min(100,100*data.processed/data.total):0;const bar=document.getElementById('bar');const value=width+'%';if(bar.style.width!==value)bar.style.width=value;bar.parentElement.setAttribute('aria-valuenow',Math.round(width));
 const key=JSON.stringify(data.previews.map(p=>[p.id,p.image]));if(key!==photoKey){photoKey=key;const list=document.getElementById('photos');const fragment=document.createDocumentFragment();for(const item of data.previews){const card=document.createElement('div');card.className='photo';const img=document.createElement('img');img.src=item.image;img.alt=item.name+' — possible match, not verified';card.appendChild(img);const label=document.createElement('p');label.textContent=item.name+' · possible match';card.appendChild(label);if(item.url){const link=document.createElement('a');link.href=item.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open in Drive';card.appendChild(link);}fragment.appendChild(card);}list.replaceChildren(fragment);document.getElementById('empty').hidden=data.previews.length>0;}
 }catch(error){text('status','Progress connection temporarily unavailable; retrying…');}finally{busy=false;}}
update();setInterval(update,5000);
</script></body></html>'''


COMPACT_HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:light dark}*{box-sizing:border-box}body{margin:0;font:12px system-ui,sans-serif;color:light-dark(#202938,#e9edf4);background:light-dark(#fff,#0e1117)}
.strip{display:grid;grid-template-columns:minmax(100px,1fr) repeat(3,minmax(65px,auto));gap:16px;align-items:center;padding:5px 12px;border:1px solid #75819855;border-radius:10px}
.heading{min-width:0}.status{font-size:12px;font-weight:650;color:light-dark(#257247,#8ad6ac);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#folder{font-size:11px;opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}#eta{font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px}.label{font-size:10px;opacity:.75;white-space:nowrap}.value{font-size:19px;font-weight:650;font-variant-numeric:tabular-nums;white-space:nowrap}.track{height:3px;margin-top:4px;background:#75819833;border-radius:4px}.bar{height:100%;background:#3aa6d8;border-radius:4px;transition:width .3s}
@media(max-width:540px){.strip{gap:8px;padding:6px 8px}.value{font-size:15px}.label{font-size:9px}}
@media(max-width:360px){.strip{grid-template-columns:repeat(3,1fr);gap:3px}.heading{grid-column:1/-1}.status{flex-shrink:0}#folder{display:none}.value{font-size:14px}}
</style></head><body>
<section class="strip" aria-label="Live scan status">
<div class="heading"><div id="status" class="status">Connecting…</div><div id="folder">Background scan</div><div id="eta" aria-label="Estimated finish">Estimating finish…</div></div>
<div><div class="label" id="checked-label">Checked</div><div id="checked" class="value">—</div></div>
<div><div class="label" id="possible-label">Possible matches</div><div id="possible" class="value">—</div></div>
<div title="Photos you manually confirmed in this scan folder"><div class="label">Confirmed by you</div><div id="confirmed" class="value">—</div></div>
</section><div class="track" role="progressbar" aria-label="Scan progress" aria-valuemin="0" aria-valuemax="100"><div id="bar" class="bar"></div></div>
<script>
let busy=false;let progressState=null;
function text(id,value){const node=document.getElementById(id);const next=String(value);if(node.textContent!==next)node.textContent=next;}
function duration(seconds){const total=Math.max(0,Math.ceil(seconds));const hours=Math.floor(total/3600),minutes=Math.floor(total%3600/60),remainder=total%60;return hours?hours+'h '+minutes+'m':minutes+'m '+remainder+'s';}
function renderEta(){if(!progressState)return;const elapsed=(performance.now()-progressState.receivedAt)/1000;const data=progressState.data;
 let eta=data.finished?'Completed':data.stopped?'Estimate unavailable — scan stopped':data.remaining_seconds==null?'Estimating finish…':'≈ '+duration(data.remaining_seconds-elapsed)+' left';
 const finish=new Date(data.estimated_finish);if(!data.finished&&!data.stopped&&data.estimated_finish&&!Number.isNaN(finish.getTime()))eta+=' · finish '+new Intl.DateTimeFormat('en-GB',{hour:'2-digit',minute:'2-digit',timeZone:'Asia/Jerusalem'}).format(finish);
 text('eta',eta);document.getElementById('eta').title=eta+' (finish time in Israel)';
}
async function update(){if(busy)return;busy=true;try{
 const response=await fetch('/progress',{cache:'no-store'});if(!response.ok)throw Error();const data=await response.json();
 text('status',data.status.replace(' — you can use other tabs',''));text('folder',data.folder.split(' / ').slice(-3).join(' / '));document.getElementById('folder').title=data.folder;
 text('checked',data.processed+' / '+data.total);text('possible',data.possible);text('confirmed',data.confirmed);
 text('checked-label',data.checked_label||'Checked');text('possible-label',data.possible_label||'Possible matches');
 progressState={data,receivedAt:performance.now()};renderEta();
 const width=data.total?Math.min(100,100*data.processed/data.total):0;const bar=document.getElementById('bar');bar.style.width=width+'%';bar.parentElement.setAttribute('aria-valuenow',Math.round(width));
 }catch(error){text('status','Progress reconnecting…');}finally{busy=false;}}
update();setInterval(update,5000);setInterval(renderEta,1000);
</script></body></html>'''


def snapshot(data):
    from festival_finder.detection_jobs import detection_snapshot
    detection=detection_snapshot(data)
    if detection is not None:
        return detection, {}
    report, labels = read_snapshot(data)
    if report is None:
        return {'folder': 'No scan yet', 'status': 'Choose a folder in the main app.', 'processed': 0,
                'total': 0, 'possible': 0, 'confirmed': 0, 'timing': '', 'remaining_seconds': None,
                'remaining_text': '', 'estimated_finish': None, 'finished': False, 'stopped': True,
                'errors': 0, 'previews': []}, {}
    stats = live_stats(report, labels)
    job = current_job(data)
    status = '✓ Scan finished' if report.get('finished') else '● Running in background — you can use other tabs'
    if job and job['status'] in {'interrupted', 'failed'} and not report.get('finished'):
        status = job.get('error', 'Background scan stopped; completed files remain cached.')
    matches = report.get('matches', [])
    folder = matches[0].get('folder', '') if matches else report.get('selected_folder', 'Current folder')
    previews, images = [], {}
    for item, hit in reversed(stats['candidates'][-6:]):
        path = Path(hit.get('preview', '')).resolve()
        if not path.is_file() or not path.is_relative_to((Path(data) / 'runs').resolve()):
            continue
        key = hashlib.sha256(str(path).encode()).hexdigest()
        images[key] = path
        url = item.get('url', '')
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'drive.google.com':
            url = ''
        previews.append({'id': item.get('id', item['name']), 'name': item['name'], 'image': '/preview/'+key, 'url': url})
    timing = report.get('timing', {})
    return {'folder': folder, 'status': status, 'processed': stats['processed'], 'total': stats['total'],
            'possible': stats['possible_files'], 'confirmed': stats['confirmed_files'], 'errors': len(report.get('errors', [])),
            'remaining_seconds': timing.get('remaining_seconds'), 'remaining_text': duration_text(timing.get('remaining_seconds')),
            'estimated_finish': timing.get('estimated_finish'), 'finished': bool(report.get('finished')),
            'stopped': bool(job and job['status'] in {'interrupted', 'failed'} and not report.get('finished')),
            'timing': f"Elapsed {duration_text(timing.get('elapsed_seconds'))} · estimated remaining {duration_text(timing.get('remaining_seconds'))}",
            'previews': previews}, images


def handler(data):
    identity = hashlib.sha256(str(Path(data).resolve()).casefold().encode()).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            # Bind locally and reject cross-site browser fetches. The iframe uses same-origin requests.
            path = urlparse(self.path).path
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' and path not in {'/', '/compact'}:
                self.send_error(403)
                return
            try:
                if path == '/health':
                    body, kind = identity.encode(), 'text/plain'
                elif path == '/':
                    body, kind = HTML.encode(), 'text/html; charset=utf-8'
                elif path == '/compact':
                    body, kind = COMPACT_HTML.encode(), 'text/html; charset=utf-8'
                elif path == '/progress':
                    payload, _ = snapshot(data)
                    body, kind = json.dumps(payload).encode(), 'application/json'
                elif self.path.startswith('/preview/'):
                    _, images = snapshot(data)
                    path = images.get(self.path.removeprefix('/preview/'))
                    if path is None:
                        self.send_error(404)
                        return
                    body, kind = path.read_bytes(), 'image/jpeg'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'private, max-age=3600' if kind == 'image/jpeg' else 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError):
                self.send_error(503)
    return Handler


if __name__ == '__main__':
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8503
    ThreadingHTTPServer(('127.0.0.1', port), handler(Path(sys.argv[1]))).serve_forever()
