from __future__ import annotations

import calendar
import hashlib
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta
from supabase import Client, create_client

st.set_page_config(page_title="LYN | העלאות מעסיקים", page_icon="📁", layout="wide")

MONTHS_HE = {
    1: "ינואר", 2: "פברואר", 3: "מרץ", 4: "אפריל", 5: "מאי", 6: "יוני",
    7: "יולי", 8: "אוגוסט", 9: "ספטמבר", 10: "אוקטובר", 11: "נובמבר", 12: "דצמבר"
}
ROLES_HE = {"admin": "מנהל מערכת", "referent": "רפרנטית", "payroll": "חשבת שכר"}

st.markdown("""
<style>
html, body, [class*="css"] { direction: rtl; text-align: right; }
[data-testid="stSidebar"] { direction: rtl; }
.status-ok {background:#e8f5e9;border:1px solid #9bd3a1;padding:8px;border-radius:8px;text-align:center;font-weight:700;color:#176b2c}
.status-missing {background:#ffebee;border:1px solid #ef9a9a;padding:8px;border-radius:8px;text-align:center;font-weight:700;color:#a61b29}
.small-muted {color:#6b7280;font-size:.85rem}
</style>
""", unsafe_allow_html=True)


def require_secrets() -> None:
    required = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY")
    missing = [k for k in required if k not in st.secrets]
    has_secret = "SUPABASE_SECRET_KEY" in st.secrets or "SUPABASE_SERVICE_ROLE_KEY" in st.secrets
    if missing or not has_secret:
        st.error("חסרים פרטי חיבור ל-Supabase. העתיקו את .streamlit/secrets.toml.example לקובץ secrets.toml ומלאו את הערכים.")
        st.stop()


@st.cache_resource
def admin_client() -> Client:
    secret_key = st.secrets.get("SUPABASE_SECRET_KEY", st.secrets.get("SUPABASE_SERVICE_ROLE_KEY"))
    return create_client(st.secrets["SUPABASE_URL"], secret_key)


def auth_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_PUBLISHABLE_KEY"])


def normalize_email(value: str) -> str:
    return value.strip().lower()


def safe_filename(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).name)
    return clean[:150] or "upload.xml"


def is_xml_file(filename: str, content: bytes) -> bool:
    if Path(filename).suffix.lower() not in {".xml", ".dat"}:
        return False
    head = content.lstrip()[:100].lower()
    return head.startswith(b"<?xml") or head.startswith(b"<")


def login_screen() -> None:
    st.title("כניסה למערכת העלאות")
    st.caption("חשבות שכר ורפרנטיות רואות רק את המעסיקים ששויכו אליהן.")
    with st.form("login"):
        email = st.text_input("דוא״ל")
        password = st.text_input("סיסמה", type="password")
        submitted = st.form_submit_button("כניסה", use_container_width=True)
    if submitted:
        try:
            result = auth_client().auth.sign_in_with_password({"email": normalize_email(email), "password": password})
            st.session_state.user_id = str(result.user.id)
            st.session_state.user_email = result.user.email
            st.rerun()
        except Exception:
            st.error("פרטי הכניסה אינם נכונים או שהמשתמש אינו פעיל.")


def get_profile(user_id: str) -> dict | None:
    rows = admin_client().table("profiles").select("*").eq("id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def assigned_employers(profile: dict) -> list[dict]:
    db = admin_client()
    if profile["role"] == "admin":
        return db.table("employers").select("*").eq("active", True).order("name").execute().data
    links = db.table("user_employers").select("employer_id").eq("user_id", profile["id"]).execute().data
    ids = [x["employer_id"] for x in links]
    if not ids:
        return []
    return db.table("employers").select("*").in_("id", ids).eq("active", True).order("name").execute().data


def month_start(year: int, month: int) -> str:
    return date(year, month, 1).isoformat()


def upload_map(employer_ids: list[str], year: int) -> dict[tuple[str, int], dict]:
    if not employer_ids:
        return {}
    start = date(year, 1, 1).isoformat()
    end = date(year + 1, 1, 1).isoformat()
    rows = (admin_client().table("uploads").select("*")
            .in_("employer_id", employer_ids).gte("report_month", start).lt("report_month", end)
            .execute().data)
    return {(r["employer_id"], int(r["report_month"][5:7])): r for r in rows}


def dashboard(profile: dict) -> None:
    employers = assigned_employers(profile)
    st.title("סטטוס קבצים לפי מעסיק")
    if not employers:
        st.warning("עדיין לא שויכו אליך מעסיקים. יש לפנות למנהל המערכת.")
        return

    current = date.today()
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        year = st.selectbox("שנת דיווח", list(range(current.year - 2, current.year + 2)), index=2)
    with c2:
        months_count = st.selectbox("חודשים להצגה", [6, 12], index=1)
    with c3:
        search = st.text_input("חיפוש מעסיק")

    selected_months = list(range(1, 13))[-months_count:]
    employers = [e for e in employers if search.lower() in e["name"].lower()]
    uploads = upload_map([e["id"] for e in employers], year)

    header = st.columns([2.4] + [1] * len(selected_months))
    header[0].markdown("**מעסיק**")
    for col, m in zip(header[1:], selected_months):
        col.markdown(f"**{MONTHS_HE[m]}**")

    for employer in employers:
        row = st.columns([2.4] + [1] * len(selected_months))
        row[0].markdown(f"**{employer['name']}**  \n<span class='small-muted'>{employer.get('employer_number') or ''}</span>", unsafe_allow_html=True)
        for col, m in zip(row[1:], selected_months):
            item = uploads.get((employer["id"], m))
            if item:
                when = datetime.fromisoformat(item["uploaded_at"].replace("Z", "+00:00")).astimezone().strftime("%d/%m %H:%M")
                col.markdown(f"<div class='status-ok'>✓<br><small>{when}</small></div>", unsafe_allow_html=True)
            else:
                col.markdown("<div class='status-missing'>חסר</div>", unsafe_allow_html=True)
        st.divider()


def upload_page(profile: dict) -> None:
    st.title("העלאת קובץ XML")
    employers = assigned_employers(profile)
    if not employers:
        st.warning("לא שויכו אליך מעסיקים.")
        return
    employer_by_name = {f"{e['name']} ({e.get('employer_number') or 'ללא מספר'})": e for e in employers}
    current = date.today().replace(day=1) - relativedelta(months=1)

    with st.form("upload_form", clear_on_submit=True):
        employer_label = st.selectbox("מעסיק", list(employer_by_name))
        c1, c2 = st.columns(2)
        year = c1.selectbox("שנה", list(range(date.today().year - 2, date.today().year + 2)), index=2)
        month = c2.selectbox("חודש", list(MONTHS_HE), index=current.month - 1, format_func=lambda x: MONTHS_HE[x])
        uploaded_file = st.file_uploader("קובץ XML או DAT", type=["xml", "dat"])
        notes = st.text_input("הערה (לא חובה)")
        replace = st.checkbox("החלפת קובץ שכבר הועלה לאותו חודש")
        submit = st.form_submit_button("העלאה", use_container_width=True)

    if submit:
        if uploaded_file is None:
            st.error("יש לבחור קובץ.")
            return
        content = uploaded_file.getvalue()
        if len(content) > 10 * 1024 * 1024:
            st.error("הקובץ גדול מ-10MB.")
            return
        if not is_xml_file(uploaded_file.name, content):
            st.error("הקובץ אינו נראה כקובץ XML/DAT תקין.")
            return

        employer = employer_by_name[employer_label]
        report_month = month_start(year, month)
        db = admin_client()
        existing = (db.table("uploads").select("*").eq("employer_id", employer["id"])
                    .eq("report_month", report_month).limit(1).execute().data)
        if existing and not replace:
            st.error("כבר קיים קובץ למעסיק ולחודש שנבחרו. סמנו 'החלפת קובץ' כדי לעדכן.")
            return

        digest = hashlib.sha256(content).hexdigest()[:12]
        storage_path = f"{employer['id']}/{year}/{month:02d}/{uuid.uuid4()}_{digest}_{safe_filename(uploaded_file.name)}"
        try:
            db.storage.from_("xml-files").upload(storage_path, content, {"content-type": "application/xml", "upsert": "false"})
            payload = {
                "employer_id": employer["id"], "report_month": report_month,
                "file_name": uploaded_file.name, "storage_path": storage_path,
                "uploaded_by": profile["id"], "file_size": len(content), "notes": notes or None,
            }
            if existing:
                old = existing[0]
                db.table("uploads").update(payload).eq("id", old["id"]).execute()
                try:
                    db.storage.from_("xml-files").remove([old["storage_path"]])
                except Exception:
                    pass
            else:
                db.table("uploads").insert(payload).execute()
            st.success(f"הקובץ של {employer['name']} לחודש {MONTHS_HE[month]} {year} הועלה בהצלחה.")
        except Exception as exc:
            st.error(f"ההעלאה נכשלה: {exc}")


def history_page(profile: dict) -> None:
    st.title("היסטוריית העלאות")
    employers = assigned_employers(profile)
    ids = [e["id"] for e in employers]
    if not ids:
        return
    names = {e["id"]: e["name"] for e in employers}
    rows = (admin_client().table("uploads").select("*").in_("employer_id", ids)
            .order("uploaded_at", desc=True).limit(500).execute().data)
    if not rows:
        st.info("עדיין לא הועלו קבצים.")
        return
    df = pd.DataFrame(rows)
    df["מעסיק"] = df["employer_id"].map(names)
    df["חודש דיווח"] = pd.to_datetime(df["report_month"]).dt.strftime("%m/%Y")
    df["הועלה בתאריך"] = pd.to_datetime(df["uploaded_at"]).dt.tz_convert("Asia/Jerusalem").dt.strftime("%d/%m/%Y %H:%M")
    df = df.rename(columns={"file_name": "שם קובץ", "notes": "הערה"})
    st.dataframe(df[["מעסיק", "חודש דיווח", "שם קובץ", "הועלה בתאריך", "הערה"]], use_container_width=True, hide_index=True)

    selected = st.selectbox("הורדת קובץ", rows, format_func=lambda r: f"{names[r['employer_id']]} | {r['report_month'][5:7]}/{r['report_month'][:4]} | {r['file_name']}")
    if selected:
        try:
            content = admin_client().storage.from_("xml-files").download(selected["storage_path"])
            st.download_button("הורדה", content, file_name=selected["file_name"], mime="application/xml")
        except Exception as exc:
            st.error(f"לא ניתן להוריד את הקובץ: {exc}")


def admin_page(profile: dict) -> None:
    if profile["role"] != "admin":
        st.error("אין הרשאה לעמוד זה.")
        return
    st.title("ניהול מערכת")
    db = admin_client()
    tab1, tab2, tab3 = st.tabs(["מעסיקים", "משתמשים", "שיוכים"])

    with tab1:
        with st.form("new_employer", clear_on_submit=True):
            name = st.text_input("שם מעסיק")
            number = st.text_input("ח.פ./מספר מעסיק")
            if st.form_submit_button("הוספת מעסיק"):
                try:
                    db.table("employers").insert({"name": name.strip(), "employer_number": number.strip() or None}).execute()
                    st.success("המעסיק נוסף.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"לא ניתן להוסיף: {exc}")
        employers = db.table("employers").select("*").order("name").execute().data
        st.dataframe(pd.DataFrame(employers), use_container_width=True, hide_index=True)

    with tab2:
        st.info("יצירת משתמש חדש נעשית ב-Supabase: Authentication → Users → Add user. לאחר מכן המשתמש מופיע כאן אוטומטית.")
        profiles = db.table("profiles").select("*").order("full_name").execute().data
        if profiles:
            labels = {f"{p['full_name']} | {p['email']}": p for p in profiles}
            label = st.selectbox("בחירת משתמש לעריכה", list(labels))
            p = labels[label]
            with st.form("edit_user"):
                full_name = st.text_input("שם מלא", p["full_name"])
                role = st.selectbox("תפקיד", list(ROLES_HE), index=list(ROLES_HE).index(p["role"]), format_func=lambda x: ROLES_HE[x])
                office = st.text_input("משרד רו״ח / מחלקה", p.get("office_name") or "")
                active = st.checkbox("פעיל", p["active"])
                if st.form_submit_button("שמירה"):
                    db.table("profiles").update({"full_name": full_name, "role": role, "office_name": office or None, "active": active}).eq("id", p["id"]).execute()
                    st.success("המשתמש עודכן.")
                    st.rerun()

    with tab3:
        profiles = db.table("profiles").select("*").eq("active", True).order("full_name").execute().data
        employers = db.table("employers").select("*").eq("active", True).order("name").execute().data
        if profiles and employers:
            p_labels = {f"{p['full_name']} ({ROLES_HE[p['role']]})": p for p in profiles}
            selected_p_label = st.selectbox("משתמש", list(p_labels), key="assign_user")
            selected_p = p_labels[selected_p_label]
            current_links = db.table("user_employers").select("employer_id").eq("user_id", selected_p["id"]).execute().data
            current_ids = {x["employer_id"] for x in current_links}
            e_labels = {e["name"]: e for e in employers}
            chosen = st.multiselect("מעסיקים שיופיעו למשתמש", list(e_labels), default=[n for n, e in e_labels.items() if e["id"] in current_ids])
            if st.button("שמירת שיוכים", type="primary"):
                db.table("user_employers").delete().eq("user_id", selected_p["id"]).execute()
                payload = [{"user_id": selected_p["id"], "employer_id": e_labels[n]["id"]} for n in chosen]
                if payload:
                    db.table("user_employers").insert(payload).execute()
                st.success("השיוכים נשמרו.")


def main() -> None:
    require_secrets()
    if "user_id" not in st.session_state:
        login_screen()
        return
    profile = get_profile(st.session_state.user_id)
    if not profile or not profile.get("active"):
        st.session_state.clear()
        st.error("המשתמש אינו פעיל.")
        return

    with st.sidebar:
        st.subheader("LYN")
        st.write(profile["full_name"])
        st.caption(f"{ROLES_HE[profile['role']]} · {profile.get('office_name') or ''}")
        pages = ["סטטוס חודשי", "העלאת קובץ", "היסטוריה"]
        if profile["role"] == "admin":
            pages.append("ניהול מערכת")
        page = st.radio("תפריט", pages)
        if st.button("יציאה"):
            st.session_state.clear()
            st.rerun()

    if page == "סטטוס חודשי": dashboard(profile)
    elif page == "העלאת קובץ": upload_page(profile)
    elif page == "היסטוריה": history_page(profile)
    else: admin_page(profile)


if __name__ == "__main__":
    main()
