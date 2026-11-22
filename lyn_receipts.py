"""Private bank transfer receipts, scoped to assigned employers by caller."""
import uuid
from datetime import date
from pathlib import Path
import pandas as pd
import streamlit as st

BUCKET = 'lyn-bank-receipts'
TYPES = {'pdf':'application/pdf','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg'}

def upload_receipts(profile, db, employers, current, months):
    choices = {f"{e['name']} ({e.get('employer_number') or e['id']})":e for e in employers}
    with st.form('receipt_upload'):
        employer = choices[st.selectbox('מעסיק', list(choices))]
        a,b = st.columns(2)
        year = a.selectbox('שנת שכר', list(range(current.year-5,current.year+2)), index=5)
        month = b.selectbox('חודש שכר', list(months), index=current.month-1, format_func=lambda m: months[m])
        files = st.file_uploader('אסמכתאות העברה בנקאית', type=list(TYPES), accept_multiple_files=True)
        company = st.text_input('חברת ביטוח / יעד העברה (לא חובה)')
        notes = st.text_input('הערות (לא חובה)')
        submit = st.form_submit_button('שמירת אסמכתאות')
    if not submit: return
    if not files: st.warning('יש לבחור לפחות קובץ אחד.'); return
    for f in files:
        content = f.getvalue(); ext = Path(f.name).suffix.lower().lstrip('.')
        valid = (ext=='pdf' and content.startswith(b'%PDF-')) or (ext=='png' and content.startswith(b'\x89PNG\r\n\x1a\n')) or (ext in ('jpg','jpeg') and content.startswith(b'\xff\xd8\xff'))
        if not valid or len(content)>10*1024*1024:
            st.error(f'{f.name}: סוג קובץ לא תקין או גודל מעל 10MB.'); continue
        path = f"{employer['id']}/{year}/{month:02d}/{uuid.uuid4()}.{ext}"
        try:
            db.storage.from_(BUCKET).upload(path, content, {'content-type':TYPES[ext],'upsert':'false'})
            try:
                db.table('lyn_bank_receipts').insert(dict(employer_id=employer['id'], salary_month=date(year,month,1).isoformat(), file_name=Path(f.name).name, storage_path=path, uploaded_by=profile['id'], file_size=len(content), insurance_company=company.strip() or None, notes=notes.strip() or None)).execute()
            except Exception:
                db.storage.from_(BUCKET).remove([path]); raise
            st.success(f'{f.name} נשמר לחודש שכר {month:02d}/{year}.')
        except Exception as ex: st.error(f'שמירת {f.name} נכשלה: {ex}')

def receipt_history(db, employers, key):
    if not employers: return
    names = {e['id']:e['name'] for e in employers}
    options = {'כל המעסיקים':None, **{f"{e['name']} ({e.get('employer_number') or e['id']})":e['id'] for e in employers}}
    eid = options[st.selectbox('סינון מעסיק',list(options),key=key+'_employer')] if len(employers)>1 else employers[0]['id']
    period = st.date_input('חודש שכר לסינון (לא חובה)',value=None,key=key+'_month')
    try:
        q = db.table('lyn_bank_receipts').select('*').in_('employer_id',[eid] if eid else list(names))
        if period: q=q.eq('salary_month',period.replace(day=1).isoformat())
        rows=q.order('uploaded_at',desc=True).limit(500).execute().data or []
        if not rows: st.info('אין אסמכתאות להצגה.'); return
        st.dataframe(pd.DataFrame([{'מעסיק':names[r['employer_id']], 'חודש שכר':r['salary_month'][5:7]+'/'+r['salary_month'][:4], 'קובץ':r['file_name'], 'חברת ביטוח':r.get('insurance_company'), 'הערות':r.get('notes'), 'הועלה':r['uploaded_at']} for r in rows]),hide_index=True,use_container_width=True)
        r=st.selectbox('בחירת אסמכתא',rows,format_func=lambda r:f"{names[r['employer_id']]} | {r['salary_month'][:7]} | {r['file_name']}",key=key+'_file')
        if st.button('הכנת אסמכתא להורדה',key=key+'_prepare'):
            content=db.storage.from_(BUCKET).download(r['storage_path'])
            st.download_button('הורדת אסמכתא',content,file_name=r['file_name'],mime=TYPES.get(Path(r['file_name']).suffix.lower().lstrip('.'),'application/octet-stream'),key=key+'_download')
    except Exception as ex: st.error(f'לא ניתן להציג אסמכתאות: {ex}')
