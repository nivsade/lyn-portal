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


ACTIONS={'טעינת קובץ':('file_loaded_on','file_load_status'),'למעסיק במייל':('employer_email_sent_on','employer_email_status'),'דיווח קופות':('reported_on','reporting_status')}

def as_date(v):
    return None if pd.isna(v) or not v else pd.Timestamp(v).date()

def as_text(v):
    return '' if pd.isna(v) else str(v)

def monthly_page(profile,db,employers):
    if profile.get('role') not in ('admin','referent') or not profile.get('active'): return
    st.subheader('תפעול שוטף')
    today=datetime.now(ZoneInfo('Asia/Jerusalem')).date()
    default=date(today.year-1,12,1) if today.month==1 else date(today.year,today.month-1,1)
    a,b=st.columns(2)
    year=a.selectbox('שנת שכר',list(range(today.year-5,today.year+2)),index=default.year-(today.year-5))
    month=b.selectbox('חודש שכר',list(range(1,13)),index=default.month-1)
    period=date(year,month,1).isoformat(); ids=[e['id'] for e in employers if e.get('active',True)]
    try:
        details={r['employer_id']:r for r in fetch(db,'lyn_employer_details',ids)}
        saved={r['employer_id']:r for r in fetch(db,'lyn_monthly_tracking',ids,period)}
    except Exception as ex:
        st.error('טעינת המעקב נכשלה.'); return
    rows=[]
    for e in employers:
        k=e['id']
        if k not in ids: continue
        d=details.get(k,{}); s=saved.get(k,{})
        rows.append({'id':k,'שם מעסיק':e['name'],'מזהה מעסיק':d.get('employer_identifier') or e.get('employer_number') or '', **{label:as_date(s.get(field)) for label,(field,raw) in ACTIONS.items()}, 'מס׳ עובדים':s.get('employee_count'),'היזונים':s.get('feedback_status') or '', 'הערות':s.get('notes') or ''})
    if not rows: st.info('אין לקוחות'); return
    df=pd.DataFrame(rows).set_index('id')
    if profile['role']=='admin':
        owners={k:details.get(k,{}).get('lyn_owner_name') or 'לא הוגדר' for k in ids}
        rep=st.selectbox('רפרנטית',['הכל']+sorted(set(owners.values())))
        if rep!='הכל': df=df.loc[[k for k in df.index if owners[k]==rep]]
    if st.checkbox('רק רשומות קיימות בחודש',value=period<default.isoformat()): df=df.loc[[k for k in df.index if k in saved]]
    if df.empty: st.info('אין רשומות מתאימות'); return
    total=len(df)
    records=[saved.get(k,{}) for k in df.index]
    def done(r,field,raw):
        return bool(r.get(field)) or str(r.get(raw) or '').strip() in ('בוצע','דווח','שויך','שיוך מלא','כן')
    exempt=sum(r.get('status')=='לא נדרש דיווח' for r in records)
    eligible=total-exempt
    reported=sum(r.get('status')!='לא נדרש דיווח' and (done(r,'reported_on','reporting_status') or r.get('status') in ('ממתין להיזון','אי־שיוכים','שיוך מלא')) for r in records)
    linked=sum(r.get('status')=='שיוך מלא' for r in records)
    def pct(n,d): return f'{100*n/d:.1f}%' if d else '—'
    st.markdown('#### תמונת מצב חודשית')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('סה״כ מעסיקים',total)
    c2.metric('דווחו לקופות',reported,pct(reported,eligible),delta_color='off')
    c3.metric('ללא דיווח מאומת',eligible-reported,pct(eligible-reported,eligible),delta_color='off')
    c4.metric('שיוך מלא',linked,pct(linked,eligible),delta_color='off')
    for label,(field,raw) in ACTIONS.items():
        n=reported if field=='reported_on' else sum(done(r,field,raw) for r in records)
        d=eligible if field=='reported_on' else total
        st.progress(n/d if d else 0,text=f'{label}: {n}/{d} ({pct(n,d)})')
    st.caption(f'לא נדרש דיווח: {exempt}. אחוזי דיווח ושיוך מחושבים מתוך המעסיקים הנדרשים לדיווח. נתון חסר אינו הוכחה שלא דווח.')
    search=st.text_input('חיפוש לפי שם או מזהה מעסיק')
    if search: df=df[df['שם מעסיק'].str.contains(search,regex=False,case=False)|df['מזהה מעסיק'].astype(str).str.contains(search,regex=False)]
    if df.empty: st.info('אין רשומות מתאימות'); return
    st.caption('תא תאריך ריק אינו בהכרח פעולה שלא בוצעה. ערכי המקור ללא תאריך מוצגים מתחת לטבלה.')
    def persist(k,patch):
        old=saved.get(k,{})
        if 'reported_on' in patch:
            dt=patch['reported_on']; status=old.get('status','טרם דווח')
            patch['status']=('ממתין להיזון' if status in ('טרם דווח','לא נדרש דיווח') else status) if dt else 'טרם דווח'
        patch.update(updated_by=profile['id'],updated_at=datetime.now(timezone.utc).isoformat())
        if old:
            q=db.table('lyn_monthly_tracking').update(patch).eq('employer_id',k).eq('salary_month',period).eq('updated_at',old['updated_at'])
            if not q.execute().data: raise RuntimeError('הרשומה השתנתה או לא נשמרה')
        else:
            db.table('lyn_monthly_tracking').insert(dict(employer_id=k,salary_month=period,**patch)).execute()
    import hashlib
    version=hashlib.sha256(str([(k,saved.get(k,{}).get('updated_at')) for k in df.index]).encode()).hexdigest()[:20]
    edited=st.data_editor(df,hide_index=True,use_container_width=True,num_rows='fixed',disabled=['שם מעסיק','מזהה מעסיק'],column_config={**{label:st.column_config.DateColumn(format='DD/MM/YYYY',max_value=today) for label in ACTIONS},'מס׳ עובדים':st.column_config.NumberColumn(min_value=0,step=1)},key='monthly_'+period+'_'+version)
    changes=[]
    for k,r in edited.iterrows():
        patch={}; old=df.loc[k]
        for label,(field,raw) in ACTIONS.items():
            dt=as_date(r[label])
            if dt!=as_date(old[label]):
                if dt and dt>today: st.error('אין להזין תאריך עתידי'); return
                patch[field]=dt.isoformat() if dt else None; patch[raw]='בוצע' if dt else 'טרם בוצע'
        for label,field in [('היזונים','feedback_status'),('הערות','notes')]:
            if as_text(r[label])!=as_text(old[label]): patch[field]=as_text(r[label])
        n=None if pd.isna(r['מס׳ עובדים']) else int(r['מס׳ עובדים']); prev=None if pd.isna(old['מס׳ עובדים']) else int(old['מס׳ עובדים'])
        if n!=prev: patch['employee_count']=n
        if patch: changes.append((k,patch))
    if changes:
        try:
            for k,patch in changes: persist(k,patch)
            st.session_state['monthly_notice']='השינויים נשמרו'; st.rerun()
        except Exception: st.error('השמירה לא הושלמה. ייתכן שחלק מהשינויים נשמרו. רענן ובדוק לפני ניסיון נוסף.'); return
    if st.session_state.pop('monthly_notice',None): st.success('השינויים נשמרו')
    with st.expander('סימון פעולה בתאריך היום'):
        k=st.selectbox('מעסיק',list(df.index),format_func=lambda k:df.loc[k,'שם מעסיק'],key='today_employer_'+period)
        label=st.selectbox('פעולה',list(ACTIONS),key='today_action_'+period)
        if st.button('סמן היום',key='today_save_'+period):
            field,raw=ACTIONS[label]
            try: persist(k,{field:today.isoformat(),raw:'בוצע'}); st.rerun()
            except Exception: st.error('השמירה נכשלה. רענן ונסה שוב.')
    with st.expander('מידע היסטורי ללא תאריך מדויק'):
        rawrows=[]
        for k in df.index:
            s=saved.get(k,{})
            raw={label:s.get(raw) or '' for label,(field,raw) in ACTIONS.items() if not s.get(field) and s.get(raw)}
            if raw: rawrows.append({'שם מעסיק':df.loc[k,'שם מעסיק'],**raw})
        if rawrows: st.dataframe(pd.DataFrame(rawrows).fillna(''),hide_index=True,use_container_width=True)
        else: st.info('אין ערכי מקור נוספים')
    st.download_button('ייצוא CSV לאקסל',df.to_csv(index=False).encode('utf-8-sig'),file_name='LYN_'+period+'.csv',mime='text/csv')

def monthly_history(db,eid):
    try:
        rows=fetch(db,'lyn_monthly_tracking',[eid]); rows.sort(key=lambda r:r['salary_month'],reverse=True)
        st.dataframe(pd.DataFrame([{'חודש שכר':r['salary_month'][:7],**{label:r.get(field) or r.get(raw) for label,(field,raw) in ACTIONS.items()},'מס׳ עובדים':r.get('employee_count'),'היזונים':r.get('feedback_status'),'הערות':r.get('notes')} for r in rows]),hide_index=True)
    except Exception: st.warning('היסטוריה חודשית אינה זמינה עדיין.')
