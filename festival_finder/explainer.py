"""A plain-language map of the existing app and its data flow."""


def render_explainer(st):
    st.header('How it works')
    st.info('Photo processing runs on your computer. It does not send photos to ChatGPT or use OpenAI API tokens.')
    st.caption('This page explains the existing system. Opening it does not start a scan or load any photos.')
    st.graphviz_chart('''digraph workflow {
        graph [rankdir=TB, bgcolor="transparent", nodesep=0.3, ranksep=0.45];
        node [shape=box, style="rounded,filled", fillcolor="#163047", color="#5A9CC8", fontcolor="white", fontname="Arial", margin=0.16];
        edge [color="#7FAAC5", fontcolor="#7FAAC5", fontname="Arial"];
        choose [label="1. Choose a festival and photographer folder"];
        drive [label="2. Google Drive lists files and supplies small previews"];
        local [label="3. Local OpenCV models process previews on your computer"];
        results [label="4. Save previews and suggested results locally"];
        review [label="5. You review photos and confirm or reject them"];
        saved [label="6. Local database stores your decisions and progress"];
        nearby [label="Nearby photos: two before and two after\nFilename sequence + your manual review"];
        collection [label="Confirmed photos collection"];
        download [label="Optional: request originals from Drive\nDownload your confirmed photos as a ZIP"];
        choose -> drive -> local -> results -> review -> saved;
        saved -> nearby -> review;
        saved -> collection -> download;
    }''', width='stretch')
    st.subheader('What each part does')
    st.write('**Google Drive** supplies folder names, file lists, small photo previews, and originals when you request them. Google sign-in controls which files the app can read. Some image data must transfer to your computer even when only previews are used.')
    st.write('**Local processing** uses OpenCV with the YuNet and SFace models. The existing scanner detects visible faces and compares numerical face features with saved examples. This runs on your CPU; suggested results can contain mistakes. It does not identify back-facing appearances automatically.')
    st.write('**Your review** is the source of confirmation. Whole-photo decisions work even when your face is hidden. They update the collection and counts, but do not add face references. Nearby review uses filename order, which may differ from actual capture order.')
    st.write('**Saved data** stays in this project’s local database and preview folders. Each festival has its own folder progress. Closing a browser tab does not stop an already running background worker; your computer must remain on.')
    st.write('**Downloads** happen only when you request originals. The ZIP contains the photographer’s uploaded quality, subject to their download permissions. Ordinary scanning uses previews. Current Google Drive video handling checks cover images only.')
    st.subheader('What uses tokens?')
    st.table([
        {'Activity': 'Photo processing and reviewing inside Find My Dance', 'OpenAI usage': 'No OpenAI API calls; uses local CPU, memory, disk, and internet for Drive'},
        {'Activity': 'Talking to the assistant, coding changes, or assistant computer use', 'OpenAI usage': 'Uses your Codex allowance; separate from the photo-processing loop'},
        {'Activity': 'Whisper', 'OpenAI usage': 'Not part of this app; it handles speech, not photo processing'},
    ])
    st.caption('You can use the app’s own controls without asking the assistant to operate them. The app does not need an ongoing ChatGPT conversation to keep a background worker running.')
