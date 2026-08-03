from __future__ import annotations

import calendar
import hashlib
import io
import re
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta
from supabase import Client, create_client

st.set_page_config(page_title="LYN | העלאות מעסיקים", page_icon="logo.png" if Path("logo.png").exists() else "📁", layout="wide")

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


def _secret_value(*names: str):
    """Read a secret from top-level Streamlit secrets, a [supabase] section, or env vars."""
    import os

    for name in names:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()

    section = st.secrets.get("supabase", {})
    for name in names:
        short_name = name.removeprefix("SUPABASE_")
        value = section.get(name) or section.get(short_name) or section.get(short_name.lower())
        if value:
            return str(value).strip()

    for name in names:
        value = os.getenv(name)
        if value:
            return value.strip()
    return None


def require_secrets() -> None:
    url = _secret_value("SUPABASE_URL", "URL")
    public_key = _secret_value("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY")
    secret_key = _secret_value("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SERVICE_ROLE_KEY")

    missing = []
    if not url:
        missing.append("SUPABASE_URL")
    if not public_key:
        missing.append("SUPABASE_PUBLISHABLE_KEY")
    if not secret_key:
        missing.append("SUPABASE_SECRET_KEY")

    if missing:
        st.error("חסרים פרטי חיבור ל-Supabase: " + ", ".join(missing))
        st.info("יש להזין את הערכים ב-Streamlit: Manage app → Settings → Secrets, לשמור ולבצע Reboot.")
        st.stop()


@st.cache_resource
def admin_client() -> Client:
    url = _secret_value("SUPABASE_URL", "URL")
    secret_key = _secret_value("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY", "SERVICE_ROLE_KEY")
    return create_client(url, secret_key)


def auth_client() -> Client:
    url = _secret_value("SUPABASE_URL", "URL")
    public_key = _secret_value("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_KEY", "SUPABASE_ANON_KEY")
    return create_client(url, public_key)

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



def _clean_text(value) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _normalize_match(value) -> str:
    text = _clean_text(value).lower()
    return re.sub(r"[\s\-_.\"'׳״()]+", "", text)


def _normalize_employer_number(value) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    digits = re.sub(r"\D", "", text)
    return digits or text


def _valid_email(value) -> bool:
    email = normalize_email(_clean_text(value))
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email))


def _temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#%"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in password)
                and any(c.isupper() for c in password)
                and any(c.isdigit() for c in password)):
            return password


def _read_import_workbook(uploaded_file) -> tuple[pd.DataFrame, pd.DataFrame]:
    content = uploaded_file.getvalue()
    workbook = pd.ExcelFile(io.BytesIO(content))

    if "מעסיקים לייבוא" not in workbook.sheet_names:
        raise ValueError("חסר גיליון בשם 'מעסיקים לייבוא'. יש להשתמש בקובץ הייבוא שהוכן למערכת.")
    if "משתמשי משרדים" not in workbook.sheet_names:
        raise ValueError("חסר גיליון בשם 'משתמשי משרדים'.")

    employers_df = pd.read_excel(
        io.BytesIO(content), sheet_name="מעסיקים לייבוא", dtype=str
    ).fillna("")
    users_df = pd.read_excel(
        io.BytesIO(content), sheet_name="משתמשי משרדים", dtype=str
    ).fillna("")

    required_employer_cols = {"שם מעסיק", "ח.פ./מזהה", "משרד רו״ח"}
    required_user_cols = {"משרד רו״ח", "מייל חשבת שכר"}
    missing_e = required_employer_cols - set(employers_df.columns)
    missing_u = required_user_cols - set(users_df.columns)
    if missing_e:
        raise ValueError("חסרות עמודות בגיליון מעסיקים: " + ", ".join(sorted(missing_e)))
    if missing_u:
        raise ValueError("חסרות עמודות בגיליון משתמשים: " + ", ".join(sorted(missing_u)))

    return employers_df, users_df


def _chunks(items: list[dict], size: int = 300):
    for index in range(0, len(items), size):
        yield items[index:index + size]


def import_excel_data(uploaded_file, create_users: bool) -> dict:
    employers_df, users_df = _read_import_workbook(uploaded_file)
    db = admin_client()

    employers_df["שם מעסיק"] = employers_df["שם מעסיק"].map(_clean_text)
    employers_df["ח.פ./מזהה"] = employers_df["ח.פ./מזהה"].map(_normalize_employer_number)
    employers_df["משרד רו״ח"] = employers_df["משרד רו״ח"].map(_clean_text)
    if "רפרנטית LYN" not in employers_df.columns:
        employers_df["רפרנטית LYN"] = ""
    employers_df["רפרנטית LYN"] = employers_df["רפרנטית LYN"].map(_clean_text)
    employers_df = employers_df[employers_df["שם מעסיק"] != ""].copy()

    users_df["משרד רו״ח"] = users_df["משרד רו״ח"].map(_clean_text)
    users_df["מייל חשבת שכר"] = users_df["מייל חשבת שכר"].map(lambda x: normalize_email(_clean_text(x)))
    users_df = users_df[
        (users_df["משרד רו״ח"] != "") & users_df["מייל חשבת שכר"].map(_valid_email)
    ].drop_duplicates(subset=["משרד רו״ח", "מייל חשבת שכר"])

    existing_employers = db.table("employers").select("*").execute().data or []
    by_number = {str(e.get("employer_number")): e for e in existing_employers if e.get("employer_number")}
    by_name = {_normalize_match(e.get("name")): e for e in existing_employers}

    new_employer_payload = []
    row_keys = []
    for _, row in employers_df.iterrows():
        name = row["שם מעסיק"]
        number = row["ח.פ./מזהה"]
        key = (number or "", _normalize_match(name))
        row_keys.append(key)
        existing = by_number.get(number) if number else by_name.get(_normalize_match(name))
        if existing:
            # אם זו רשומה זמנית שנוצרה במהלך קריאת האקסל,
            # אין עדיין UUID ולכן לא מנסים לעדכן אותה.
            if existing.get("id"):
                if (
                    existing.get("name") != name
                    or (
                        number
                        and existing.get("employer_number") != number
                    )
                ):
                    (
                        db.table("employers")
                        .update(
                            {
                                "name": name,
                                "active": True,
                            }
                        )
                        .eq("id", existing["id"])
                        .execute()
                    )
        
            continue
        new_employer_payload.append({"name": name, "employer_number": number, "active": True})
        # Prevent duplicates inside the same workbook.
        placeholder = {"id": None, "name": name, "employer_number": number}
        if number:
            by_number[number] = placeholder
        by_name[_normalize_match(name)] = placeholder

    inserted_count = 0
    if new_employer_payload:
        # Remove workbook duplicates before insertion.
        unique = {}
        for item in new_employer_payload:
            k = item["employer_number"] or f"name:{_normalize_match(item['name'])}"
            unique[k] = item
        for chunk in _chunks(list(unique.values()), 200):
            inserted = db.table("employers").insert(chunk).execute().data or []
            inserted_count += len(inserted)

    # Reload employers so every row has a real UUID.
    all_employers = db.table("employers").select("*").execute().data or []
    by_number = {str(e.get("employer_number")): e for e in all_employers if e.get("employer_number")}
    by_name = {_normalize_match(e.get("name")): e for e in all_employers}

    profiles = db.table("profiles").select("*").execute().data or []
    profile_by_email = {normalize_email(p.get("email", "")): p for p in profiles}
    new_credentials = []
    user_errors = []

    office_users: dict[str, list[dict]] = {}
    for _, row in users_df.iterrows():
        office = row["משרד רו״ח"]
        email = row["מייל חשבת שכר"]
        profile = profile_by_email.get(email)

        if not profile and create_users:
            password = _temporary_password()
            try:
                created = db.auth.admin.create_user({
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "user_metadata": {"full_name": email.split("@")[0]},
                })
                user_id = str(created.user.id)
                profile_data = {
                    "id": user_id,
                    "full_name": email.split("@")[0],
                    "email": email,
                    "role": "payroll",
                    "office_name": office,
                    "active": True,
                }
                db.table("profiles").upsert(profile_data, on_conflict="id").execute()
                profile = profile_data
                profile_by_email[email] = profile
                new_credentials.append({
                    "משרד רו״ח": office,
                    "מייל": email,
                    "סיסמה זמנית": password,
                })
            except Exception as exc:
                user_errors.append(f"{email}: {exc}")
                continue
        elif profile:
            update = {"role": "payroll", "office_name": office, "active": True}
            db.table("profiles").update(update).eq("id", profile["id"]).execute()
            profile.update(update)

        if profile:
            office_users.setdefault(_normalize_match(office), []).append(profile)

    # Every payroll user already defined with the same office also receives the office's employers.
    refreshed_profiles = db.table("profiles").select("*").eq("active", True).execute().data or []
    for p in refreshed_profiles:
        if p.get("role") == "payroll" and p.get("office_name"):
            office_users.setdefault(_normalize_match(p["office_name"]), []).append(p)

    referents = {
        _normalize_match(p.get("full_name")): p
        for p in refreshed_profiles
        if p.get("role") == "referent"
    }

    links_to_add = set()
    unmatched_offices = set()
    unmatched_referents = set()
    for _, row in employers_df.iterrows():
        employer = by_number.get(row["ח.פ./מזהה"]) if row["ח.פ./מזהה"] else by_name.get(_normalize_match(row["שם מעסיק"]))
        if not employer:
            continue
        office_key = _normalize_match(row["משרד רו״ח"])
        payroll_profiles = office_users.get(office_key, [])
        if not payroll_profiles and row["משרד רו״ח"]:
            unmatched_offices.add(row["משרד רו״ח"])
        for p in payroll_profiles:
            links_to_add.add((p["id"], employer["id"]))

        referent_name = row.get("רפרנטית LYN", "")
        if referent_name:
            referent = referents.get(_normalize_match(referent_name))
            if referent:
                links_to_add.add((referent["id"], employer["id"]))
            else:
                unmatched_referents.add(referent_name)

    existing_links = db.table("user_employers").select("user_id,employer_id").execute().data or []
    existing_link_set = {(x["user_id"], x["employer_id"]) for x in existing_links}
    new_links = [
        {"user_id": user_id, "employer_id": employer_id}
        for user_id, employer_id in links_to_add
        if (user_id, employer_id) not in existing_link_set
    ]
    for chunk in _chunks(new_links, 400):
        db.table("user_employers").insert(chunk).execute()

    return {
        "employers_in_file": len(employers_df),
        "employers_added": inserted_count,
        "users_in_file": len(users_df),
        "users_created": len(new_credentials),
        "links_added": len(new_links),
        "credentials": new_credentials,
        "unmatched_offices": sorted(unmatched_offices),
        "unmatched_referents": sorted(unmatched_referents),
        "user_errors": user_errors,
    }


def excel_import_tab() -> None:
    st.subheader("ייבוא מעסיקים ומשתמשים מאקסל")
    st.write(
        "העלה את הקובץ **LYN_ייבוא_מעסיקים_ומשרדים.xlsx**. "
        "המערכת תוסיף מעסיקים, תיצור חשבות שכר חדשות ותשייך לכל חשבת את כל המעסיקים של משרד רואי החשבון שלה."
    )
    st.warning("מומלץ לבצע את הייבוא פעם אחת בלבד. הרצה חוזרת לא אמורה ליצור כפילויות, אלא להשלים נתונים חסרים.")

    import_file = st.file_uploader(
        "בחירת קובץ Excel",
        type=["xlsx"],
        key="excel_import_file",
    )
    create_users = st.checkbox(
        "ליצור אוטומטית משתמשים לחשבות שכר שלא קיימות",
        value=True,
        help="לכל משתמש חדש תיווצר סיסמה זמנית שניתן להוריד בסיום.",
    )

    if import_file is not None:
        try:
            employers_df, users_df = _read_import_workbook(import_file)
            c1, c2 = st.columns(2)
            c1.metric("מעסיקים בקובץ", len(employers_df))
            c2.metric("חשבונות חשבות שכר בקובץ", len(users_df))
        except Exception as exc:
            st.error(str(exc))
            return

    if st.button(
        "ייבוא הכול למערכת",
        type="primary",
        use_container_width=True,
        disabled=import_file is None,
    ):
        with st.spinner("מייבא מעסיקים, משתמשים ושיוכים... זה עשוי לקחת כמה דקות."):
            try:
                result = import_excel_data(import_file, create_users=create_users)
                st.session_state["last_import_result"] = result
                st.success("הייבוא הסתיים בהצלחה.")
            except Exception as exc:
                st.error(f"הייבוא נכשל: {exc}")

    result = st.session_state.get("last_import_result")
    if result:
        c1, c2, c3 = st.columns(3)
        c1.metric("מעסיקים חדשים", result["employers_added"])
        c2.metric("משתמשים חדשים", result["users_created"])
        c3.metric("שיוכים חדשים", result["links_added"])

        if result["credentials"]:
            credentials_df = pd.DataFrame(result["credentials"])
            st.warning("הורד ושמור את הסיסמאות הזמניות עכשיו. הן אינן נשמרות להצגה חוזרת.")
            st.dataframe(credentials_df, use_container_width=True, hide_index=True)
            st.download_button(
                "הורדת משתמשים וסיסמאות",
                credentials_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="LYN_משתמשים_וסיסמאות_זמניות.csv",
                mime="text/csv",
                use_container_width=True,
            )

        if result["unmatched_offices"]:
            with st.expander("משרדים ללא משתמש חשבת שכר"):
                st.write(result["unmatched_offices"])
        if result["unmatched_referents"]:
            with st.expander("רפרנטיות שלא נמצאה להן התאמה"):
                st.write(result["unmatched_referents"])
        if result["user_errors"]:
            with st.expander("שגיאות ביצירת משתמשים"):
                st.write(result["user_errors"])

def admin_page(profile: dict) -> None:
    if profile["role"] != "admin":
        st.error("אין הרשאה לעמוד זה.")
        return
    st.title("ניהול מערכת")
    db = admin_client()
    tab1, tab2, tab3, tab4 = st.tabs(["מעסיקים", "משתמשים", "שיוכים", "ייבוא מאקסל"])

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

    with tab4:
        excel_import_tab()


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
        if Path("logo.png").exists():
            st.image("logo.png", width=170)
        else:
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
