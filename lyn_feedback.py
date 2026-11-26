import hashlib, io, json
from datetime import datetime
from collections import defaultdict
import pandas as pd
import streamlit as st
from openpyxl import load_workbook
ID='מספר מזהה מעסיק'; FILE='שם הקובץ שהועבר מהמסלקה לחברה המנהלת'; SOURCE='שם קובץ הדיווח שהועבר מהמעסיק למסלקה'; STATUS='סטטוס תנועה נוכחי'; ERROR='סוג שגיאה'; PAY='סטטוס טיפול בכספים'; ALLOC='סכום ההקצאה לקופה'; ASSIGNED='סכום ששויך לחשבונות העובדים'; FUND='מספר קידוד אחיד קופה'; CASE='מס\' תיק מסלקה'
FIELDS=[ID,'שם מעסיק','שם חברה מנהלת','שם קופה',FUND,'מספר מזהה עובד','שם פרטי','שם משפחה','חודש משכורת','סוג פעולה','סוג הפרשה',STATUS,ERROR,PAY,ALLOC,ASSIGNED,FILE,SOURCE,CASE,'מספר מזהה תנועה','תאריך הפצת הקובץ לחברה המנהלת','תאריך הפצה לחברה המנהלת','תאריך נכונות מידע']
def norm(v):
    s=str(v or '').strip().removesuffix('.0'); return s.zfill(9) if s.isdigit() and len(s)<=9 else s

def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def parse(raw):
    w=load_workbook(io.BytesIO(raw),read_only=True,data_only=True); out=[]
    try:
        for name,header,kind in [('כל התנועות',3,'movement'),('פירוט סטטוס הפקדות כספיות',2,'payment')]:
            it=w[name].iter_rows(min_row=header,values_only=True); cols=[str(x or '').strip() for x in next(it)]
            if not {ID,FILE,STATUS if kind=='movement' else PAY}.issubset(cols): raise ValueError('מבנה דוח לא מוכר')
            for i,values in enumerate(it,header+1):
                r={k:(v.isoformat() if hasattr(v,'isoformat') else v) for k,v in zip(cols,values) if k in FIELDS or k.startswith('סכום הפרשה')}
                if not r.get(ID): continue
                r[ID]=norm(r[ID]); m=r.get('חודש משכורת'); month=None
                if m:
                    try: month=pd.Timestamp(m).strftime('%Y-%m-01')
                    except Exception: pass
                out.append(dict(row_key=f'{kind}:{i}',kind=kind,salary_month=month,payload=r))
    finally: w.close()
    return out

def pages(q,order):
    out=[]
    for i in range(0,1000000,500):
        b=q.order(order).range(i,i+499).execute().data or []; out+=b
        if len(b)<500:return out
    raise RuntimeError('יותר מדי רשומות')
def load(db,ids):
    if not ids:return []
    batches=pages(db.table('lyn_feedback_batches').select('id,created_at').eq('complete',True),'id'); dates={b['id']:b['created_at'] for b in batches}; out=[]
    for i in range(0,len(ids),40):
        out+=pages(db.table('lyn_feedback_rows').select('*').in_('employer_id',ids[i:i+40]),'row_key')
    # latest observation per stable source identity; missing rows remain visible
    latest={}
    for r in out:
        if r['batch_id'] not in dates:continue
        p=r['payload']; identity=(r['employer_id'],r['kind'],p.get('מספר מזהה תנועה') or digest([p.get(CASE),p.get(FILE),p.get(FUND),p.get('מספר מזהה עובד'),p.get('סוג הפרשה')]))
        if identity not in latest or dates[r['batch_id']]>dates[latest[identity]['batch_id']]:latest[identity]=r
    return list(latest.values())
def issue(r):
    p=r['payload']
    if r['kind']=='movement':return p.get(STATUS)!='רשומה נקלטה'
    try:return p.get(PAY)!='תשלום נפרע במלואו' or abs(float(p[ALLOC])-float(p[ASSIGNED]))>.01
    except (ValueError,TypeError,KeyError):return True

def import_page(profile,db,employers):
    if profile.get('role')!='admin' or not profile.get('active'):return
    f=st.file_uploader('דוח מענים XLSX',type=['xlsx'],key='feedback_upload')
    if not f:return
    try:
        raw=f.getvalue(); rows=parse(raw); mapping=defaultdict(set)
        for e in employers:mapping[norm(e.get('employer_number'))].add(e['id'])
        for d in pages(db.table('lyn_employer_details').select('employer_id,employer_identifier'),'employer_id'):
            if d['employer_id'] in {e['id'] for e in employers}:mapping[norm(d.get('employer_identifier'))].add(d['employer_id'])
        matched=[]; missing=defaultdict(int)
        for r in rows:
            ids=mapping[r['payload'][ID]]
            if len(ids)==1:matched.append(dict(r,employer_id=next(iter(ids))))
            else:missing[(r['payload'][ID],r['payload'].get('שם מעסיק'))]+=1
        st.write(f'שורות מותאמות: {len(matched)} / {len(rows)}')
        if missing:st.dataframe([{'מזהה':k[0],'מעסיק':k[1],'שורות':v} for k,v in missing.items()]);st.warning('שורות ללא התאמה חד משמעית לא ייקלטו.')
        if matched and st.button('אישור קליטת שורות מותאמות'):
            bid=hashlib.sha256(raw).hexdigest(); existing=db.table('lyn_feedback_batches').select('complete').eq('id',bid).execute().data
            if existing and existing[0]['complete']:st.info('הדוח כבר נקלט');return
            db.table('lyn_feedback_batches').upsert(dict(id=bid,filename=f.name,uploaded_by=profile['id'],complete=False)).execute()
            for i in range(0,len(matched),200):db.table('lyn_feedback_rows').upsert([dict(r,batch_id=bid) for r in matched[i:i+200]]).execute()
            db.table('lyn_feedback_batches').update({'complete':True}).eq('id',bid).execute();st.success('הדוח נקלט')
    except Exception:st.error('קליטה נכשלה. בדוק התקנת SQL ומבנה הדוח; דוח חלקי אינו מוצג.')

def feedback_view(profile,db,employers,key='feedback',only_issues=False):
    if profile.get('role') not in ('admin','referent') or not profile.get('active'):return
    try: rows=load(db,[e['id'] for e in employers])
    except Exception:st.warning('מודול היזונים אינו זמין. יש להתקין את SQL.');return
    if not rows:st.info('אין דוחות שנקלטו');return
    months=sorted({r['salary_month'] for r in rows if r['salary_month']},reverse=True)
    month=st.selectbox('חודש שכר',['הכל','לא ידוע']+months,key=key+'month'); rows=[r for r in rows if month=='הכל' or (r['salary_month'] or 'לא ידוע')==month]
    a,b,c=st.columns(3);a.metric('מעסיקים בדוח',len({r['employer_id'] for r in rows}));b.metric('שורות לבדיקה',sum(issue(r) for r in rows));c.metric('תנועות שנקלטו',sum(r['kind']=='movement' and not issue(r) for r in rows))
    if only_issues or st.checkbox('רק חריגים',key=key+'only'):rows=[r for r in rows if issue(r)]
    if not rows:return
    st.dataframe(pd.DataFrame([r['payload'] for r in rows]),hide_index=True,use_container_width=True)
    groups=defaultdict(list)
    for r in rows:
        if not issue(r):continue
        p=r['payload']; k=digest([r['employer_id'],r['salary_month'],p.get('מספר מזהה עובד'),p.get(FUND),p.get(FILE),p.get(CASE),p.get(ERROR),p.get(STATUS) or p.get(PAY)]) ;groups[k].append(r)
    if not groups:return
    k=st.selectbox('בחירת חריג לטיפול',list(groups),format_func=lambda k:' | '.join(str(groups[k][0]['payload'].get(x) or '') for x in ['שם מעסיק','שם פרטי','שם משפחה','שם קופה',ERROR,STATUS,PAY]),key=key+'case'); r=groups[k][0];p=r['payload'];st.code(p.get(FILE) or 'לא מופיע בדוח');st.write('שורות מקור בחריג:',len(groups[k]));st.dataframe(pd.DataFrame([x['payload'] for x in groups[k]]),hide_index=True)
    old=db.table('lyn_feedback_cases').select('*').eq('employer_id',r['employer_id']).eq('case_key',k).execute().data;old=old[0] if old else {}; states=['פתוח','בטיפול','ממתין לתשובה','טופל ידנית'];
    with st.form(key+'form'+k):
        status=st.selectbox('סטטוס טיפול',states,index=states.index(old.get('status','פתוח')));notes=st.text_area('הערות',old.get('notes',''))
        if st.form_submit_button('שמירה'):db.table('lyn_feedback_cases').upsert(dict(employer_id=r['employer_id'],case_key=k,status=status,notes=notes)).execute();st.success('נשמר')
    st.text_area('טיוטת פנייה לחברה',f"נושא: בירור שיוך – {p.get('שם מעסיק')} {p.get(ID)}\nשלום, נא לבדוק את השיוך עבור {p.get('שם פרטי') or ''} {p.get('שם משפחה') or ''}, מזהה {p.get('מספר מזהה עובד') or ''}, חודש {r['salary_month'] or 'לא ידוע'}, קובץ {p.get(FILE) or 'לא ידוע'}.\nשגיאה: {p.get(ERROR) or p.get(PAY) or p.get(STATUS)}. תודה.",key=key+'draft'+k)
