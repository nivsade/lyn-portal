"""LYN internal operations screens. Only call for admin/referent profiles."""
import streamlit as st
import pandas as pd

INTERNAL = {'admin', 'referent'}

def _guard(profile):
    if profile.get('role') not in INTERNAL or not profile.get('active'):
        st.error('אין הרשאה לצפות בנתונים תפעוליים.')
        st.stop()

def _records(db, table, employer_id=None):
    q = db.table(table).select('*')
    if employer_id:
        q = q.eq('employer_id', employer_id)
    return q.limit(1000).execute().data or []

def _show(rows, columns):
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df[[c for c in columns if c in df.columns]], hide_index=True, use_container_width=True)
    else:
        st.info('אין עדיין נתונים להצגה.')

def operations_page(profile, db, employers):
    _guard(profile)
    st.title('LYN | מערכת תפעול')
    if not employers:
        st.info('אין מעסיקים משויכים.'); return
    choices = {f"{e['name']} · {e.get('employer_number') or ''}": e for e in employers}
    selected = choices[st.selectbox('בחר מעסיק', list(choices), key='ops_employer')]
    eid = selected['id']
    st.subheader(selected['name'])
    st.caption(f"מזהה מעסיק: {selected.get('employer_number') or 'לא הוזן'}")
    tab1, tab2, tab3, tab4, tab5 = st.tabs(['כרטיס מעסיק','ייפויי כוח','אי־שיוכים','משימות','קבצים'])
    with tab1:
        details = _records(db, 'lyn_employer_details', eid)
        old = details[0] if details else {}
        with st.form('employer_details_form'):
            office = st.text_input('משרד רו״ח', old.get('accounting_office') or '')
            payroll = st.text_input('מייל חשבת שכר', old.get('payroll_contact_email') or '')
            contact = st.text_input('מייל איש קשר', old.get('employer_contact_email') or '')
            owner = st.text_input('אחראית LYN', old.get('lyn_owner_name') or '')
            notes = st.text_area('הערות', old.get('notes') or '')
            if st.form_submit_button('שמירת פרטי מעסיק'):
                payload = dict(employer_id=eid, employer_identifier=selected.get('employer_number'), accounting_office=office, payroll_contact_email=payroll, employer_contact_email=contact, lyn_owner_name=owner, notes=notes)
                try:
                    db.table('lyn_employer_details').upsert(payload, on_conflict='employer_id').execute()
                    st.success('פרטי המעסיק נשמרו.')
                except Exception as ex: st.error(f'שמירה נכשלה: {ex}')
    with tab2:
        _show(_records(db, 'lyn_powers_of_attorney', eid), ['insurance_company','sent_status','handling_status','sent_at','notes'])
        with st.form('new_poa'):
            company = st.text_input('חברת ביטוח')
            status = st.selectbox('סטטוס', ['טרם נשלח','נשלח','חסר מסמך','אושר','נדחה'])
            notes = st.text_area('הערות לייפוי כוח')
            if st.form_submit_button('הוספת ייפוי כוח'):
                if not company.strip(): st.error('יש להזין חברת ביטוח.')
                else:
                    try:
                        db.table('lyn_powers_of_attorney').insert({'employer_id':eid,'insurance_company':company.strip(),'handling_status':status,'notes':notes}).execute()
                        st.success('נוסף בהצלחה.'); st.rerun()
                    except Exception as ex: st.error(str(ex))
    with tab3:
        _show(_records(db, 'lyn_unmatched_cases', eid), ['employee_identifier','employee_first_name','employee_last_name','fund_name','report_month','error_type','error_detail','handling_status','reported_contributions'])
        st.caption('ייבוא המקרים מקובץ האקסל יתווסף בשלב הבא. אין שינוי בנתוני המקור.')
    with tab4:
        tasks = _records(db, 'lyn_tasks', eid)
        _show(tasks, ['title','status','priority','due_date','description'])
        with st.form('new_task'):
            title = st.text_input('שם משימה')
            description = st.text_area('תיאור')
            priority = st.selectbox('עדיפות', ['רגילה','גבוהה','דחופה'])
            due = st.date_input('תאריך יעד', value=None)
            if st.form_submit_button('הוספת משימה'):
                if not title.strip(): st.error('יש להזין שם משימה.')
                else:
                    try:
                        db.table('lyn_tasks').insert({'employer_id':eid,'title':title.strip(),'description':description,'priority':priority,'due_date':due.isoformat() if due else None}).execute()
                        st.success('המשימה נוספה.'); st.rerun()
                    except Exception as ex: st.error(str(ex))
        open_tasks = [t for t in tasks if t.get('status') != 'הושלמה']
        if open_tasks:
            chosen = st.selectbox('סימון משימה כהושלמה', open_tasks, format_func=lambda t: t['title'], key='task_complete')
            if st.button('סמן כהושלמה'):
                try:
                    db.table('lyn_tasks').update({'status':'הושלמה'}).eq('id',chosen['id']).eq('employer_id',eid).execute()
                    st.rerun()
                except Exception as ex: st.error(str(ex))
    with tab5:
        _show(_records(db, 'uploads', eid), ['file_name','report_month','uploaded_at','notes'])
        st.caption('העלאה והורדה מתבצעות במסכים הקיימים בפורטל.')
