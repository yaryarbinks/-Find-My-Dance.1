"""Review face locations, with explicit whole-photo human decisions."""
from pathlib import Path

from festival_finder.detection_jobs import current_detection


def render_detection_page(st,projects,feedback,data):
    st.header('Face detection')
    st.caption('Boxes locate faces. They do not identify anyone or compare faces with reference photos.')
    @st.fragment(run_every='5s')
    def progress():
        state=current_detection(data)
        if not state:
            st.info('Choose a folder in Search and folders, then click Detect faces in this folder.')
            return
        st.write(state['path'])
        st.write(state['status'].replace('_',' ').title())
        a,b,c=st.columns(3)
        a.metric('Photos checked',f"{state.get('processed',0)} / {state.get('total',0)}")
        b.metric('Photos containing detected faces',state.get('with_faces',0))
        c.metric('Face locations',state.get('faces',0))
        if state.get('error'):
            st.error(state['error'])
        st.caption('Progress updates every five seconds. Opening this page does not start another job.')
    progress()
    festivals=projects.festivals()
    available=[]
    for festival in festivals:
        for row in projects.folders(festival['id']):
            report=projects.detection_report(festival['id'],row['id'])
            if report is not None:
                available.append((festival['id'],row,report))
    if not available:
        return
    state=current_detection(data)
    keys=[(festival,row['id']) for festival,row,_ in available]
    active=(state['festival'],state['folder']) if state else None
    chosen=st.selectbox('Detection result folder',keys,index=keys.index(active) if active in keys else 0,
                        format_func=lambda key:next(row['path'] for festival,row,_ in available if (festival,row['id'])==key))
    report=next(report for festival,row,report in available if (festival,row['id'])==chosen)
    show=st.radio('Detection view',['Photos with faces','All checked photos'],horizontal=True)
    photos=[item for item in report['matches'] if show=='All checked photos' or item.get('detected_faces')]
    st.caption(f'{len(photos)} photos in this view. A preview with no detected faces can still contain a person whose face is hidden, distant, or blurred.')
    if report.get('errors'):
        with st.expander(f"{len(report['errors'])} preview errors"):
            st.json(report['errors'])
    page=st.number_input('Detection gallery page',1,max(1,(len(photos)+11)//12),1,key=f'detection-page-{chosen}-{len(photos)}')
    for item in photos[(page-1)*12:page*12]:
        label=projects.photo_labels(*chosen).get(item['id'])
        key=f"detected-{chosen[0]}-{chosen[1]}-{item['id']}"
        with st.container(border=True):
            st.write(f"**{item['name']}** · {len(item.get('detected_faces',[]))} face location(s)")
            if label=='not_me':
                st.caption('✓ You marked this photo as not you.')
                if st.button('Undo photo decision',key=key+'-undo'):
                    projects.review_photo(*chosen,item['id'],None)
                    st.rerun()
                expanded=st.expander('Reopen photo',expanded=False)
            else:
                if label=='me':
                    st.success('✓ You confirmed you appear in this photo.')
                expanded=st.container()
            with expanded:
                preview=Path(item['boxed_preview'])
                if preview.is_file():
                    st.image(str(preview),width=640)
                st.link_button('Open original in Drive',item['url'])
                a,b,c=st.columns(3)
                for col,title,value in [(a,"I'm in this photo",'me'),(b,'Not in this photo','not_me'),(c,'Undo',None)]:
                    if col.button(title,key=key+str(value),disabled=label==value):
                        projects.review_photo(*chosen,item['id'],value)
                        st.rerun()
