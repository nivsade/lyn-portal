from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

STATUSES=['טרם דווח','ממתין להיזון','אי־שיוכים','שיוך מלא','לא נדרש דיווח']

def fetch(db, table, ids, month=None, field='salary_month'):
    rows=[]
    for i in range(0,len(ids),80):
        offset=0
        while True:
            q=db.table(table).select('*').in_('employer_id',ids[i:i+80])
            if month: q=q.eq(field,month)
            batch=q.order('employer_id').range(offset,offset+499).execute().data or []
            rows.extend(batch)
            if len(batch)<500: break
            offset+=500
    return rows

def monthly_page(profile,db,employers):
    if profile.get('role') not in ('admin','referent') or not profile.get('active'): return
    st.subheader('מעקב חודשי')
    today=datetime.now(ZoneInfo('Asia/Jerusalem')).date()
    default=date(today.year-1,12,1) if today.month==1 else date(today.year,today.month-1,1)
    a,b=st.columns(2)
    year=a.selectbox('שנת שכר',list(range(today.year-5,today.year+2)),index=default.year-(today.year-5))
    month=b.selectbox('חודש שכר',list(range(1,13)),index=default.month-1)
    period=date(year,month,1).isoformat(); ids=[e['id'] for e in employers]
    try:
        details={r['employer_id']:r for r in fetch(db,'lyn_employer_details',ids)}
        saved={r['employer_id']:r for r in fetch(db,'lyn_monthly_tracking',ids,period)}
        uploads={r['employer_id'] for r in fetch(db,'uploads',ids,period,'report_month')}
        receipts={r['employer_id'] for r in fetch(db,'lyn_bank_receipts',ids,period)}
    except Exception:
        st.error('לא ניתן לטעון מעקב חודשי. יש לבדוק את חיבור מסד הנתונים ולהריץ את קובצי ההתקנה.'); return
    rows=[]
    for e in employers:
        k=e['id']; d=details.get(k,{}); s=saved.get(k,{})
        rows.append({'id':k,'מעסיק':e['name'],'ח.פ.':e.get('employer_number') or '', 'רפרנטית':d.get('lyn_owner_name') or 'לא הוגדר','עובדים':d.get('employee_count'),'קובץ שכר':k in uploads,'אסמכתאות':k in receipts,'תאריך דיווח':date.fromisoformat(s['reported_on']) if s.get('reported_on') else None,'סטטוס':s.get('status','טרם דווח'),'הערות':s.get('notes','')})
    if not rows: st.info('אין לקוחות'); return
    df=pd.DataFrame(rows).set_index('id')
    if profile['role']=='admin':
        rep=st.selectbox('רפרנטית',['הכל']+sorted(df['רפרנטית'].unique()))
        if rep!='הכל': df=df[df['רפרנטית']==rep]
    cols=st.columns(4)
    for c,(label,n) in zip(cols,[('לקוחות',len(df)),('דווחו',int(df['תאריך דיווח'].notna().sum())),('טרם דווחו',int((df['סטטוס']=='טרם דווח').sum())),('שיוך מלא',int((df['סטטוס']=='שיוך מלא').sum()))]): c.metric(label,n)
    search=st.text_input('חיפוש מעסיק או ח.פ.')
    statuses=st.multiselect('סינון סטטוס',STATUSES)
    if search: df=df[df['מעסיק'].str.contains(search,regex=False,case=False)|df['ח.פ.'].astype(str).str.contains(search,regex=False)]
    if statuses: df=df[df['סטטוס'].isin(statuses)]
    st.caption('קבלת קבצים אינה דיווח. יש להזין תאריך דיווח בפועל; אסמכתאות מסומנות אם התקבל לפחות קובץ אחד.')
    with st.form('monthly_'+period):
        edited=st.data_editor(df,hide_index=True,use_container_width=True,disabled=[c for c in df.columns if c not in ['תאריך דיווח','סטטוס','הערות']],column_config={'תאריך דיווח':st.column_config.DateColumn(format='DD/MM/YYYY',max_value=today),'סטטוס':st.column_config.SelectboxColumn(options=STATUSES,required=True)},key='editor_'+period+'_'+str(tuple(df.index)))
        submit=st.form_submit_button('שמירת שינויים')
    if submit:
        changes=[]
        for k,r in edited.iterrows():
            old=saved.get(k,{}); dt=r['תאריך דיווח']; dt=None if pd.isna(dt) else pd.Timestamp(dt).date().isoformat(); status=r['סטטוס']; notes=str(r['הערות'] or '')
            if (dt,status,notes)==(old.get('reported_on'),old.get('status','טרם דווח'),old.get('notes','')): continue
            if (status in STATUSES[:1]+STATUSES[-1:]) != (dt is None) or (dt and dt>today.isoformat()):
                st.error('תאריך וסטטוס אינם תואמים עבור '+r['מעסיק']); return
            changes.append(dict(employer_id=k,salary_month=period,reported_on=dt,status=status,notes=notes,updated_by=profile['id'],updated_at=datetime.now(timezone.utc).isoformat()))
        if changes:
            try: db.table('lyn_monthly_tracking').upsert(changes,on_conflict='employer_id,salary_month').execute(); st.success('השינויים נשמרו'); st.rerun()
            except Exception: st.error('שמירה נכשלה. יש לנסות שוב.')
    st.download_button('ייצוא CSV לאקסל',df.to_csv(index=False).encode('utf-8-sig'),file_name='LYN_'+period+'.csv',mime='text/csv')

def monthly_history(db,eid):
    try:
        rows=fetch(db,'lyn_monthly_tracking',[eid]); rows.sort(key=lambda r:r['salary_month'],reverse=True)
        st.dataframe(pd.DataFrame([{'חודש שכר':r['salary_month'][:7],'תאריך דיווח':r['reported_on'],'סטטוס':r['status'],'הערות':r['notes']} for r in rows]),hide_index=True)
    except Exception: st.warning('היסטוריה חודשית אינה זמינה עדיין.')
