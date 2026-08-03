# LYN Upload Portal

מערכת פשוטה להעלאת קבצי XML/DAT לפי מעסיק וחודש דיווח.

## מה יש במערכת
- כניסה בדוא״ל וסיסמה.
- תפקידים: מנהל, רפרנטית, חשבת שכר.
- כל משתמש רואה רק מעסיקים ששויכו אליו.
- לוח חודשי אדום/ירוק המציג אם קובץ הועלה ומתי.
- העלאה והחלפה של קובץ לפי מעסיק וחודש.
- היסטוריה והורדת קבצים.
- מסך ניהול מעסיקים, משתמשים ושיוכים.

## התקנה
1. פתחו פרויקט חדש ב-Supabase.
2. ב-SQL Editor הריצו את `schema.sql`.
3. ב-Project Settings > API העתיקו URL, anon key ו-service_role key.
4. העתיקו `.streamlit/secrets.toml.example` אל `.streamlit/secrets.toml` ומלאו את הערכים.
5. התקנה והרצה:

```bash
pip install -r requirements.txt
streamlit run app.py
```

## יצירת מנהל ראשון
1. ב-Supabase עברו ל-Authentication > Users > Add user.
2. צרו משתמש בדוא״ל וסיסמה.
3. ב-Table Editor > profiles שנו את `role` שלו מ-`payroll` ל-`admin`.
4. התחברו למערכת. מכאן ניתן לנהל מעסיקים, הרשאות ושיוכים.

## פרסום ב-Streamlit Community Cloud
1. העלו את התיקייה ל-GitHub. אין להעלות את `secrets.toml`.
2. צרו אפליקציה חדשה ובחרו `app.py`.
3. ב-App settings > Secrets הדביקו את שלושת משתני הסוד.

## אבטחה
- קבצי XML נשמרים ב-bucket פרטי.
- מפתח service-role נשמר רק בצד השרת ב-Streamlit Secrets.
- ההרשאות נאכפות באפליקציה. לפני שימוש רחב או מידע רגיש במיוחד מומלץ להעביר את פעולות ההרשאה ל-RPC/Edge Functions ולהוסיף RLS מלא לפי JWT.
