"""LYN writing assistant: drafts only, no sending."""
import json
from urllib.request import Request, urlopen
import streamlit as st

WRITING_RULES = '''כאשר המשתמש מבקש ניסוח או שכתוב, החזר נוסח מוכן להעתקה בעברית אלא אם ביקש שפה אחרת. שמור על העובדות, הסכומים, התאריכים והכוונה; אל תוסיף עובדות, הבטחות, אשמה או התחייבויות. ברירת המחדל היא מקצועית, שירותית, אנושית וקצרה. בדרך כלל פתח ב'היי', ללא התנצלות מיותרת. מול מעסיק היה סבלני ושירותי, מול חשבת שכר שיתופי ולא מאשים, מול חברת ביטוח קצר וישיר. ציין בבירור מה נדרש ומה הצעד הבא. בוואטסאפ אל תוסיף נושא. במייל הנוגע למעסיק הנושא חייב לכלול שם המעסיק וח.פ.; אם חסרים השתמש במצייני מקום [שם המעסיק] ו[ח.פ.] והבהר שיש להשלים לפני שליחה. אל תמציא כתובות מייל. בפנייה על אי־שיוך לפי נוהל 43 שמור על התבנית הקצרה המאושרת. אין לשלוח הודעות בפועל. אין לבקש תעודות זהות, מידע רפואי או נתוני עובדים מזהים בצ'אט; השתמש במצייני מקום.''' 

def writing_page(api_key):
    st.subheader('ניסוח הודעות ומיילים')
    st.caption('כתבי בשפה חופשית וקבלי נוסח מקצועי ומוכן להעתקה. אין שליחה אוטומטית.')
    if not api_key:
        st.info('יש להגדיר OPENAI_API_KEY להפעלת עוזר הניסוח.')
        return
    with st.form('lyn_writing_form'):
        recipient = st.selectbox('למי מיועדת ההודעה?', ['מעסיק', 'חשבת שכר / רואה חשבון', 'חברת ביטוח', 'אחר'])
        channel = st.radio('סוג ההודעה', ['וואטסאפ', 'מייל'], horizontal=True)
        tone = st.selectbox('סגנון הניסוח', ['מקצועי ושירותי', 'קצר וענייני', 'אסרטיבי ומכבד', 'קליל וחברי'])
        draft = st.text_area('מה תרצי לנסח?', height=160, placeholder='כתבי כאן את ההודעה בשפה חופשית...')
        st.caption('אין להזין תעודות זהות, פרטי חשבון או מידע אישי רגיש. אפשר להשתמש במצייני מקום ולהשלים לאחר ההעתקה.')
        submitted = st.form_submit_button('נסח לי')
    if submitted:
        st.session_state.pop('lyn_writing_result', None)
        if not draft.strip():
            st.warning('יש להזין הודעה לניסוח.')
        elif len(draft) > 4000:
            st.warning('נא לקצר את ההודעה ל-4,000 תווים.')
        else:
            try:
                payload = {'model':'gpt-4.1-mini','messages':[{'role':'system','content':WRITING_RULES + '\nהחזר רק את הנוסח המוצע, ללא הסברים מיותרים.'},{'role':'user','content':json.dumps({'recipient':recipient,'channel':channel,'tone':tone,'draft':draft},ensure_ascii=False)}],'temperature':0.2,'max_tokens':1200}
                req = Request('https://api.openai.com/v1/chat/completions', data=json.dumps(payload,ensure_ascii=False).encode('utf-8'), headers={'Authorization':'Bearer '+api_key,'Content-Type':'application/json'},method='POST')
                with st.spinner('מנסח את ההודעה...'):
                    with urlopen(req,timeout=35) as response:
                        result = json.load(response)['choices'][0]['message']['content']
                st.session_state['lyn_writing_result'] = result
            except Exception:
                st.error('לא ניתן לקבל נוסח כרגע. נסי שוב או פני למנהל המערכת.')
    if st.session_state.get('lyn_writing_result'):
        st.markdown('**הנוסח המוצע**')
        st.code(st.session_state['lyn_writing_result'], language=None)
        st.caption('בדקי את הפרטים והשלימי מצייני מקום לפני השליחה. ניתן להעתיק באמצעות כפתור ההעתקה.')
        if st.button('ניקוי הנוסח', key='lyn_writing_clear'):
            st.session_state.pop('lyn_writing_result', None)
            st.rerun()
