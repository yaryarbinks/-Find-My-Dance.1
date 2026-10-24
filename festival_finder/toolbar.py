"""A persistent, read-only scan strip beside Streamlit's toolbar."""
from html import escape


SIDEBAR_LAYOUT = '''<script>
(() => {
 const host=window.parent, doc=host.document;
 if(host.findMyDanceToolbarCleanup)host.findMyDanceToolbarCleanup();
 let scheduled=false;
 function layout(){scheduled=false;const strip=doc.querySelector('.global-scan-status');if(!strip)return;
  const sidebar=doc.querySelector('[data-testid="stSidebar"]');
  const edge=sidebar&&sidebar.dataset.collapsed!=='true'?Math.max(0,sidebar.getBoundingClientRect().right):0;
  const left=Math.max(host.innerWidth<700?45:64,edge+12);
  const right=host.innerWidth<480?70:host.innerWidth<700?112:185;
  const tight=host.innerWidth-left-right<320;
  const values={left:(tight?16:left)+'px',right:(tight?16:right)+'px',top:(tight?62:5)+'px'};
  for(const [key,value]of Object.entries(values))if(strip.style[key]!==value)strip.style[key]=value;
  const header=doc.querySelector('[data-testid="stHeader"]');
  if(header){const height=tight?'140px':'90px';if(header.style.height!==height)header.style.height=height;}
 }
 function schedule(){if(!scheduled){scheduled=true;host.requestAnimationFrame(layout);}}
 const observer=new MutationObserver(schedule);
 observer.observe(doc.body,{childList:true,subtree:true,attributes:true,attributeFilter:['style','data-collapsed']});
 host.addEventListener('resize',schedule);layout();
 host.findMyDanceToolbarCleanup=()=>{observer.disconnect();host.removeEventListener('resize',schedule);};
})();
</script>'''


def render_scan_toolbar(st, panel_url):
    import streamlit.components.v1 as components
    url = escape(panel_url.rstrip('/') + '/compact?layout=2', quote=True)
    st.markdown('''<style>
    .global-scan-status{position:fixed;top:5px;left:64px;right:185px;height:68px;z-index:1000001}
    .global-scan-status iframe{display:block;width:100%;height:68px;border:0;background:transparent}
    [data-testid="stHeader"]{height:90px}
    [data-testid="stMainBlockContainer"]{padding-top:7rem}
    @media(max-width:700px){.global-scan-status{left:45px;right:112px}}
    @media(max-width:480px){.global-scan-status{left:44px;right:70px;height:92px}.global-scan-status iframe{height:92px}[data-testid="stHeader"]{height:100px}[data-testid="stMainBlockContainer"]{padding-top:8rem}}
    </style><div class="global-scan-status"><iframe src="''' + url + '''" title="Live scan status" sandbox="allow-scripts allow-same-origin"></iframe></div>''', unsafe_allow_html=True)
    components.html(SIDEBAR_LAYOUT, height=0, width=0)
