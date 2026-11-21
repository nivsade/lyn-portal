"""LYN unmatched-deposit workflow: draft-only, no external mail sending."""
import re
from urllib.parse import quote
import streamlit as st

ROUTES = {
    'הראל': {'פנסיה': ('memshakpens@harel-ins.co.il', 'אומת בהתכתבויות'), 'גמל והשתלמות': ('memshakpens@harel-ins.co.il', 'אומת בהתכתבויות'), 'ביטוח מנהלים': ('gviahaim@harel-ins.co.il', 'דורש אימות לפי מקרה')},
    'מגדל': {'ביטוח מנהלים': ('tifulgviabituachmetafel@migdal.co.il', 'אומת בהפניה מגורם מתפעל'), 'פנסיה': ('', 'דרוש אימות'), 'גמל והשתלמות': ('', 'דרוש אימות')},
    'כלל': {'פנסיה': ('takanotpensia@clal-ins.co.il', 'ממשקים בלבד; לבירורי שירות sherutmetafel@clal-ins.co.il'), 'גמל והשתלמות': ('sherutmetafel@clal-ins.co.il', 'שירות מתפעלים; יש לאמת ניתוב לפי פנייה'), 'ביטוח מנהלים': ('', 'דרוש אימות')},
    'הפניקס': {'פנסיה': ('mtf@fnx.co.il', 'אומת בהתכתבויות'), 'ביטוח מנהלים': ('mtf@fnx.co.il', 'אומת בהתכתבויות'), 'גמל והשתלמות': ('gemel-mtf@fnx.co.il', 'אומת בהתכתבויות')},
    'אלטשולר שחם': {'פנסיה': ('maasikim@altshul.co.il', 'אומת בהתכתבויות'), 'גמל והשתלמות': ('maasikim@altshul.co.il', 'אומת בהתכתבויות')},
    'מיטב': {'פנסיה': ('', 'דרוש אימות'), 'גמל והשתלמות': ('hafkadot.pensia@mtds.co.il', 'נצפה שימוש אך התאמה למוצר אינה מאומתת')},
    'מנורה': {},
}

ISSUES = {
    'שגיאה 43 – קליטת הפקדה': {
        'steps': ['בדקי אם הכסף שויך ידנית או שהתקבל דיווח כפול.', 'אתרי שם קובץ, חודש שכר, מבוטח ואסמכתת העברה.', 'בקשי מהחברה אישור שיוך או סיבה מדויקת לאי-שיוך. אין לשדר שוב לפני הבירור.'],
        'ask': 'האם ההפקדה שויכה בפועל (כולל שיוך ידני או דיווח כפול)? אם לא, מדוע ומה נדרש לתיקון?',
    },
    'השבת כספים יזומה': {
        'steps': ['בדקי אילו חודשים הוחזרו והאם יש החזרים גם בחודשים האחרונים.', 'בדקי אם קיימת כיום קרן פעילה; אם לא, בקשי מהמעסיק/סוכן הביטוח להסדיר.', 'לאחר אישור הקרן והסדרת הכספים, הכיני דיווח רטרואקטיבי לחודשים הרלוונטיים ובדקי קליטה.'],
        'ask': 'מהי סיבת ההחזר, אילו חודשים הוחזרו והאם קיימת קרן פעילה לקליטת הפקדות?',
    },
    'אי-השלמת מסמכים': {
        'steps': ['בדקי אילו מסמכים חסרים ואם הקרן פעילה.', 'פני למעסיק כדי שישלים פתיחה/מסמכים מול הסוכן או הגוף המוסדי.', 'לאחר אישור קליטה, בדקי את ההפקדות שלא נקלטו.'],
        'ask': 'אילו מסמכים חסרים והאם הפוליסה פעילה ומוכנה לקליטת הפקדות?',
    },
    'חוסר תשלום / אכ״ע': {
        'steps': ['בדקי בפרטים הנוספים במסלקה את אחוז אכ״ע שדווח.', 'בררי מול הודיה או חברת הביטוח את האחוז הנכון בפוליסה.', 'העבירי לחשבת השכר את השיעור המאומת לתיקון להבא; בדקי אם נדרשת השלמה לחודש הנוכחי.'],
        'ask': 'מהו שיעור אכ״ע הנדרש לפי הפוליסה, ומהו ההפרש הכספי הנדרש אם קיים?',
    },
    'שגיאה 19 / חוקת הפיצול': {
        'steps': ['בדקי רכיבי תגמולי עובד, תגמולי מעסיק ופיצויים מול תנאי המוצר והדין.', 'בדקי אם הפער נובע מעיגול בסכומים קטנים.', 'אם יש צורך בתיקון, שמרי מקור, ודאי שסכום ההפקדה אינו משתנה ושאין דיווח כפול; אל תשני רכיבים רק כדי לעבור ולידציה.'],
        'ask': 'איזה רכיב או שיעור אינו תואם לחוקת הפיצול, ומהו הפיצול הנדרש לפי הפוליסה?',
    },
    'אחר / טרם אומת נוהל': {
        'steps': ['בדקי פירוט השגיאה במסלקה, קובץ מקורי ואסמכתת תשלום.', 'פני לחברה לקבלת סיבה ופעולה מתקנת מדויקת.', 'אל תבצעי תיקון כספי לפני אישור הנתונים.'],
        'ask': 'האם הכספים שויכו בפועל? אם לא, מה סיבת הדחייה המדויקת ואיזו פעולה נדרשת?',
    },
}

def unmatched_page(profile):
    st.title('טיפול באי־שיוכים')
    st.caption('מדריך תפעולי ויצירת טיוטות. אין שליחת מייל אוטומטית.')
    c1, c2 = st.columns(2)
    with c1:
        insurer = st.selectbox('חברה מוסדית', list(ROUTES))
        product = st.selectbox('סוג מוצר', ['פנסיה', 'ביטוח מנהלים', 'גמל והשתלמות'])
        issue = st.selectbox('סוג שגיאה', list(ISSUES))
    with c2:
        employer = st.text_input('שם המעסיק *')
        hp = st.text_input('ח.פ. / מזהה מעסיק *')
        month = st.text_input('חודש שכר (MM/YYYY)', placeholder='10/2026')
    c3, c4 = st.columns(2)
    with c3:
        insured = st.text_input('שם המבוטח')
        filename = st.text_input('שם קובץ הדיווח')
    with c4:
        amount = st.text_input('סכום הפקדה (אם ידוע)')
        transfer = st.text_input('פרטי אסמכתת העברה (אם קיימת)')
    with st.expander('מה עושים במקרה הזה?', expanded=True):
        for i, step in enumerate(ISSUES[issue]['steps'], 1):
            st.write(f'{i}. {step}')
    address, status = ROUTES[insurer].get(product, ('', 'דרוש אימות'))
    st.write('**כתובת לפנייה:**', address or 'לא אומתה כתובת למוצר זה')
    st.caption(f'סטטוס ניתוב: {status}. יש לאמת כתובת ונמען לפני שליחה.')
    if not employer.strip() or not hp.strip():
        st.info('יש למלא שם מעסיק ומספר ח.פ./מזהה כדי ליצור טיוטה.')
        return
    if not re.fullmatch(r'[0-9]{8,9}', hp.strip()):
        st.warning('מספר המעסיק צריך להכיל 8–9 ספרות. בדקי את המספר לפני שימוש.')
        return
    subject = f'{employer.strip()} – ח.פ. {hp.strip()} – {issue}' + (f' – שכר {month.strip()}' if month.strip() else '')
    body = '\n'.join([
        'שלום רב,', '',
        f'נבקש בירור בנוגע ל{issue}.',
        f'מעסיק: {employer.strip()} | ח.פ.: {hp.strip()}',
        f'מוצר: {product}',
        f'מבוטח: {insured.strip() or "[להשלמה]"}',
        f'חודש שכר: {month.strip() or "[להשלמה]"}',
        f'שם קובץ: {filename.strip() or "[להשלמה]"}',
        f'סכום: {amount.strip() or "[אם רלוונטי]"}',
        f'אסמכתת העברה: {transfer.strip() or "[יש לצרף אם רלוונטי]"}', '',
        ISSUES[issue]['ask'], '',
        'תודה רבה,', 'LYN – שירותי תפעול פנסיוני',
    ])
    st.subheader('טיוטת הודעה')
    st.text_input('נושא', subject)
    st.text_area('תוכן ההודעה', body, height=310)
    st.download_button('הורדת טיוטת מייל', data=f'אל: {address or "[כתובת לא מאומתת]"}\nנושא: {subject}\n\n{body}', file_name='lyn_unmatched_email.txt', mime='text/plain')
    if address:
        mailto = f'mailto:{quote(address)}?subject={quote(subject)}&body={quote(body)}'
        st.link_button('פתיחת טיוטה בתוכנת המייל', mailto)
    st.caption('לפני השליחה: בדקי את כתובת החברה, את פרטי העובד, את שם הקובץ ואת האסמכתאות. אין לשלוח פרטים שאינם נחוצים.')


def ai_knowledge_context() -> str:
    """Curated internal SOP and routing hints; no live email access."""
    lines = ["ידע תפעולי פנימי של LYN בנושא אי־שיוכים; יש לוודא נתונים מול הגוף המוסדי:"]
    for issue, info in ISSUES.items():
        lines.append(f"סוג: {issue}. שלבים: " + " ".join(info["steps"]))
    lines.append("ניתוב כתובות לפי גוף ומוצר; דרוש אימות פירושו שאין להמליץ על כתובת כמאומתת:")
    for insurer, products in ROUTES.items():
        for product, (address, status) in products.items():
            lines.append(f"{insurer} / {product}: {address or 'כתובת לא מאומתת'}; {status}")
    lines.append("בכל טיוטת פנייה נושא המייל חייב לכלול שם מעסיק וח.פ.; אם חסרים יש לבקש אותם בלשונית הטיפול. אין לשדר דיווח כפול או לשנות רכיבי הפרשה ללא אימות.")
    return "\n".join(lines)
