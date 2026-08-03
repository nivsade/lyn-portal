from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta
from supabase import Client, create_client


st.set_page_config(
    page_title="LYN | העלאות מעסיקים",
    page_icon="logo.png",
    layout="wide",
)


MONTHS_HE = {
    1: "ינואר",
    2: "פברואר",
    3: "מרץ",
    4: "אפריל",
    5: "מאי",
    6: "יוני",
    7: "יולי",
    8: "אוגוסט",
    9: "ספטמבר",
    10: "אוקטובר",
    11: "נובמבר",
    12: "דצמבר",
}

ROLES_HE = {
    "admin": "מנהל מערכת",
    "referent": "רפרנטית",
    "payroll": "חשבת שכר",
}


st.markdown(
    """
    <style>
    html, body, [class*="css"] {
        direction: rtl;
        text-align: right;
    }

    [data-testid="stSidebar"] {
        direction: rtl;
    }

    .status-ok {
        background: #e8f5e9;
        border: 1px solid #9bd3a1;
        padding: 8px;
        border-radius: 8px;
        text-align: center;
        font-weight: 700;
        color: #176b2c;
    }

    .status-missing {
        background: #ffebee;
        border: 1px solid #ef9a9a;
        padding: 8px;
        border-radius: 8px;
        text-align: center;
        font-weight: 700;
        color: #a61b29;
    }

    .small-muted {
        color: #6b7280;
        font-size: 0.85rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def secret_value(*names: str):
    import os

    for name in names:
        value = st.secrets.get(name)
        if value:
            return str(value).strip()

    supabase_section = st.secrets.get("supabase", {})

    for name in names:
        short_name = name.removeprefix("SUPABASE_")

        value = (
            supabase_section.get(name)
            or supabase_section.get(short_name)
            or supabase_section.get(short_name.lower())
        )

        if value:
            return str(value).strip()

    for name in names:
        value = os.getenv(name)

        if value:
            return value.strip()

    return None


def require_secrets() -> None:
    url = secret_value("SUPABASE_URL", "URL")

    public_key = secret_value(
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
    )

    secret_key = secret_value(
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SERVICE_ROLE_KEY",
    )

    missing = []

    if not url:
        missing.append("SUPABASE_URL")

    if not public_key:
        missing.append("SUPABASE_PUBLISHABLE_KEY")

    if not secret_key:
        missing.append("SUPABASE_SECRET_KEY")

    if missing:
        st.error(
            "חסרים פרטי חיבור ל-Supabase: "
            + ", ".join(missing)
        )

        st.info(
            "יש להזין את הערכים ב-Streamlit תחת "
            "Manage app → Settings → Secrets, "
            "לשמור ולבצע Reboot."
        )

        st.stop()


@st.cache_resource
def admin_client() -> Client:
    url = secret_value("SUPABASE_URL", "URL")

    secret_key = secret_value(
        "SUPABASE_SECRET_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SERVICE_ROLE_KEY",
    )

    return create_client(url, secret_key)


def auth_client() -> Client:
    url = secret_value("SUPABASE_URL", "URL")

    public_key = secret_value(
        "SUPABASE_PUBLISHABLE_KEY",
        "SUPABASE_KEY",
        "SUPABASE_ANON_KEY",
    )

    return create_client(url, public_key)


def normalize_email(value: str) -> str:
    return value.strip().lower()


def safe_filename(name: str) -> str:
    clean = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        Path(name).name,
    )

    return clean[:150] or "upload.xml"


def is_xml_file(filename: str, content: bytes) -> bool:
    extension = Path(filename).suffix.lower()

    if extension not in {".xml", ".dat"}:
        return False

    head = content.lstrip()[:100].lower()

    return head.startswith(b"<?xml") or head.startswith(b"<")


def login_screen() -> None:
    st.title("כניסה למערכת העלאות")

    st.caption(
        "חשבות שכר ורפרנטיות רואות רק את המעסיקים "
        "ששויכו אליהן."
    )

    with st.form("login"):
        email = st.text_input("דוא״ל")
        password = st.text_input("סיסמה", type="password")

        submitted = st.form_submit_button(
            "כניסה",
            use_container_width=True,
        )

    if submitted:
        try:
            result = auth_client().auth.sign_in_with_password(
                {
                    "email": normalize_email(email),
                    "password": password,
                }
            )

            st.session_state.user_id = str(result.user.id)
            st.session_state.user_email = result.user.email

            st.rerun()

        except Exception:
            st.error(
                "פרטי הכניסה אינם נכונים או שהמשתמש אינו פעיל."
            )


def get_profile(user_id: str) -> dict | None:
    rows = (
        admin_client()
        .table("profiles")
        .select("*")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
    )

    return rows[0] if rows else None


def assigned_employers(profile: dict) -> list[dict]:
    db = admin_client()

    if profile["role"] == "admin":
        return (
            db.table("employers")
            .select("*")
            .eq("active", True)
            .order("name")
            .execute()
            .data
        )

    links = (
        db.table("user_employers")
        .select("employer_id")
        .eq("user_id", profile["id"])
        .execute()
        .data
    )

    employer_ids = [
        item["employer_id"]
        for item in links
    ]

    if not employer_ids:
        return []

    return (
        db.table("employers")
        .select("*")
        .in_("id", employer_ids)
        .eq("active", True)
        .order("name")
        .execute()
        .data
    )


def month_start(year: int, month: int) -> str:
    return date(year, month, 1).isoformat()


def upload_map(
    employer_ids: list[str],
    year: int,
) -> dict[tuple[str, int], dict]:

    if not employer_ids:
        return {}

    start = date(year, 1, 1).isoformat()
    end = date(year + 1, 1, 1).isoformat()

    rows = (
        admin_client()
        .table("uploads")
        .select("*")
        .in_("employer_id", employer_ids)
        .gte("report_month", start)
        .lt("report_month", end)
        .execute()
        .data
    )

    return {
        (
            row["employer_id"],
            int(row["report_month"][5:7]),
        ): row
        for row in rows
    }


def dashboard(profile: dict) -> None:
    employers = assigned_employers(profile)

    st.title("סטטוס קבצים לפי מעסיק")

    if not employers:
        st.warning(
            "עדיין לא שויכו אליך מעסיקים. "
            "יש לפנות למנהל המערכת."
        )

        return

    current = date.today()

    column1, column2, column3 = st.columns([1, 1, 2])

    with column1:
        year = st.selectbox(
            "שנת דיווח",
            list(
                range(
                    current.year - 2,
                    current.year + 2,
                )
            ),
            index=2,
        )

    with column2:
        months_count = st.selectbox(
            "חודשים להצגה",
            [6, 12],
            index=1,
        )

    with column3:
        search = st.text_input("חיפוש מעסיק")

    selected_months = list(range(1, 13))[-months_count:]

    employers = [
        employer
        for employer in employers
        if search.lower() in employer["name"].lower()
    ]

    uploads = upload_map(
        [employer["id"] for employer in employers],
        year,
    )

    header = st.columns(
        [2.4] + [1] * len(selected_months)
    )

    header[0].markdown("**מעסיק**")

    for column, month in zip(
        header[1:],
        selected_months,
    ):
        column.markdown(
            f"**{MONTHS_HE[month]}**"
        )

    for employer in employers:
        row = st.columns(
            [2.4] + [1] * len(selected_months)
        )

        row[0].markdown(
            f"""
            **{employer["name"]}**  
            <span class="small-muted">
            {employer.get("employer_number") or ""}
            </span>
            """,
            unsafe_allow_html=True,
        )

        for column, month in zip(
            row[1:],
            selected_months,
        ):
            item = uploads.get(
                (employer["id"], month)
            )

            if item:
                uploaded_at = datetime.fromisoformat(
                    item["uploaded_at"].replace(
                        "Z",
                        "+00:00",
                    )
                )

                uploaded_at = (
                    uploaded_at
                    .astimezone()
                    .strftime("%d/%m %H:%M")
                )

                column.markdown(
                    f"""
                    <div class="status-ok">
                    ✓<br>
                    <small>{uploaded_at}</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            else:
                column.markdown(
                    """
                    <div class="status-missing">
                    חסר
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.divider()


def upload_page(profile: dict) -> None:
    st.title("העלאת קובץ XML")

    employers = assigned_employers(profile)

    if not employers:
        st.warning("לא שויכו אליך מעסיקים.")
        return

    employer_by_name = {
        (
            f"{employer['name']} "
            f"({employer.get('employer_number') or 'ללא מספר'})"
        ): employer
        for employer in employers
    }

    current_month = (
        date.today().replace(day=1)
        - relativedelta(months=1)
    )

    with st.form(
        "upload_form",
        clear_on_submit=True,
    ):
        employer_label = st.selectbox(
            "מעסיק",
            list(employer_by_name),
        )

        column1, column2 = st.columns(2)

        year = column1.selectbox(
            "שנה",
            list(
                range(
                    date.today().year - 2,
                    date.today().year + 2,
                )
            ),
            index=2,
        )

        month = column2.selectbox(
            "חודש",
            list(MONTHS_HE),
            index=current_month.month - 1,
            format_func=lambda value: MONTHS_HE[value],
        )

        uploaded_file = st.file_uploader(
            "קובץ XML או DAT",
            type=["xml", "dat"],
        )

        notes = st.text_input(
            "הערה (לא חובה)"
        )

        replace = st.checkbox(
            "החלפת קובץ שכבר הועלה לאותו חודש"
        )

        submit = st.form_submit_button(
            "העלאה",
            use_container_width=True,
        )

    if submit:
        if uploaded_file is None:
            st.error("יש לבחור קובץ.")
            return

        content = uploaded_file.getvalue()

        if len(content) > 10 * 1024 * 1024:
            st.error("הקובץ גדול מ-10MB.")
            return

        if not is_xml_file(
            uploaded_file.name,
            content,
        ):
            st.error(
                "הקובץ אינו נראה כקובץ XML/DAT תקין."
            )
            return

        employer = employer_by_name[
            employer_label
        ]

        report_month = month_start(
            year,
            month,
        )

        db = admin_client()

        existing = (
            db.table("uploads")
            .select("*")
            .eq("employer_id", employer["id"])
            .eq("report_month", report_month)
            .limit(1)
            .execute()
            .data
        )

        if existing and not replace:
            st.error(
                "כבר קיים קובץ למעסיק ולחודש שנבחרו. "
                "סמנו 'החלפת קובץ' כדי לעדכן."
            )
            return

        digest = hashlib.sha256(
            content
        ).hexdigest()[:12]

        storage_path = (
            f"{employer['id']}/"
            f"{year}/"
            f"{month:02d}/"
            f"{uuid.uuid4()}_"
            f"{digest}_"
            f"{safe_filename(uploaded_file.name)}"
        )

        try:
            db.storage.from_("xml-files").upload(
                storage_path,
                content,
                {
                    "content-type": "application/xml",
                    "upsert": "false",
                },
            )

            payload = {
                "employer_id": employer["id"],
                "report_month": report_month,
                "file_name": uploaded_file.name,
                "storage_path": storage_path,
                "uploaded_by": profile["id"],
                "file_size": len(content),
                "notes": notes or None,
            }

            if existing:
                old_upload = existing[0]

                db.table("uploads").update(
                    payload
                ).eq(
                    "id",
                    old_upload["id"],
                ).execute()

                try:
                    db.storage.from_(
                        "xml-files"
                    ).remove(
                        [
                            old_upload[
                                "storage_path"
                            ]
                        ]
                    )

                except Exception:
                    pass

            else:
                db.table("uploads").insert(
                    payload
                ).execute()

            st.success(
                f"הקובץ של {employer['name']} "
                f"לחודש {MONTHS_HE[month]} "
                f"{year} הועלה בהצלחה."
            )

        except Exception as error:
            st.error(
                f"ההעלאה נכשלה: {error}"
            )


def history_page(profile: dict) -> None:
    st.title("היסטוריית העלאות")

    employers = assigned_employers(profile)

    employer_ids = [
        employer["id"]
        for employer in employers
    ]

    if not employer_ids:
        return

    employer_names = {
        employer["id"]: employer["name"]
        for employer in employers
    }

    rows = (
        admin_client()
        .table("uploads")
        .select("*")
        .in_("employer_id", employer_ids)
        .order("uploaded_at", desc=True)
        .limit(500)
        .execute()
        .data
    )

    if not rows:
        st.info("עדיין לא הועלו קבצים.")
        return

    dataframe = pd.DataFrame(rows)

    dataframe["מעסיק"] = dataframe[
        "employer_id"
    ].map(employer_names)

    dataframe["חודש דיווח"] = (
        pd.to_datetime(
            dataframe["report_month"]
        ).dt.strftime("%m/%Y")
    )

    dataframe["הועלה בתאריך"] = (
        pd.to_datetime(
            dataframe["uploaded_at"]
        )
        .dt.tz_convert("Asia/Jerusalem")
        .dt.strftime("%d/%m/%Y %H:%M")
    )

    dataframe = dataframe.rename(
        columns={
            "file_name": "שם קובץ",
            "notes": "הערה",
        }
    )

    st.dataframe(
        dataframe[
            [
                "מעסיק",
                "חודש דיווח",
                "שם קובץ",
                "הועלה בתאריך",
                "הערה",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    selected = st.selectbox(
        "הורדת קובץ",
        rows,
        format_func=lambda row: (
            f"{employer_names[row['employer_id']]} | "
            f"{row['report_month'][5:7]}/"
            f"{row['report_month'][:4]} | "
            f"{row['file_name']}"
        ),
    )

    if selected:
        try:
            content = (
                admin_client()
                .storage
                .from_("xml-files")
                .download(
                    selected["storage_path"]
                )
            )

            st.download_button(
                "הורדה",
                content,
                file_name=selected["file_name"],
                mime="application/xml",
            )

        except Exception as error:
            st.error(
                f"לא ניתן להוריד את הקובץ: {error}"
            )


def admin_page(profile: dict) -> None:
    if profile["role"] != "admin":
        st.error("אין הרשאה לעמוד זה.")
        return

    st.title("ניהול מערכת")

    db = admin_client()

    tab1, tab2, tab3 = st.tabs(
        [
            "מעסיקים",
            "משתמשים",
            "שיוכים",
        ]
    )

    with tab1:
        with st.form(
            "new_employer",
            clear_on_submit=True,
        ):
            name = st.text_input("שם מעסיק")
            number = st.text_input(
                "ח.פ./מספר מעסיק"
            )

            add_employer = st.form_submit_button(
                "הוספת מעסיק"
            )

        if add_employer:
            if not name.strip():
                st.error("יש להזין שם מעסיק.")

            else:
                try:
                    db.table("employers").insert(
                        {
                            "name": name.strip(),
                            "employer_number": (
                                number.strip()
                                or None
                            ),
                        }
                    ).execute()

                    st.success("המעסיק נוסף.")
                    st.rerun()

                except Exception as error:
                    st.error(
                        f"לא ניתן להוסיף: {error}"
                    )

        employers = (
            db.table("employers")
            .select("*")
            .order("name")
            .execute()
            .data
        )

        if employers:
            st.dataframe(
                pd.DataFrame(employers),
                use_container_width=True,
                hide_index=True,
            )

    with tab2:
        st.info(
            "יצירת משתמש חדש נעשית ב-Supabase: "
            "Authentication → Users → Add user. "
            "לאחר מכן המשתמש מופיע כאן אוטומטית."
        )

        profiles = (
            db.table("profiles")
            .select("*")
            .order("full_name")
            .execute()
            .data
        )

        if profiles:
            labels = {
                (
                    f"{profile_item['full_name']} | "
                    f"{profile_item['email']}"
                ): profile_item
                for profile_item in profiles
            }

            selected_label = st.selectbox(
                "בחירת משתמש לעריכה",
                list(labels),
            )

            selected_profile = labels[
                selected_label
            ]

            with st.form("edit_user"):
                full_name = st.text_input(
                    "שם מלא",
                    selected_profile["full_name"],
                )

                role_options = list(ROLES_HE)

                role = st.selectbox(
                    "תפקיד",
                    role_options,
                    index=role_options.index(
                        selected_profile["role"]
                    ),
                    format_func=lambda value: (
                        ROLES_HE[value]
                    ),
                )

                office = st.text_input(
                    "משרד רו״ח / מחלקה",
                    selected_profile.get(
                        "office_name"
                    )
                    or "",
                )

                active = st.checkbox(
                    "פעיל",
                    selected_profile["active"],
                )

                save_user = (
                    st.form_submit_button("שמירה")
                )

            if save_user:
                db.table("profiles").update(
                    {
                        "full_name": full_name,
                        "role": role,
                        "office_name": (
                            office or None
                        ),
                        "active": active,
                    }
                ).eq(
                    "id",
                    selected_profile["id"],
                ).execute()

                st.success("המשתמש עודכן.")
                st.rerun()

    with tab3:
        profiles = (
            db.table("profiles")
            .select("*")
            .eq("active", True)
            .order("full_name")
            .execute()
            .data
        )

        employers = (
            db.table("employers")
            .select("*")
            .eq("active", True)
            .order("name")
            .execute()
            .data
        )

        if profiles and employers:
            profile_labels = {
                (
                    f"{profile_item['full_name']} "
                    f"({ROLES_HE[profile_item['role']]})"
                ): profile_item
                for profile_item in profiles
            }

            selected_profile_label = st.selectbox(
                "משתמש",
                list(profile_labels),
                key="assign_user",
            )

            selected_profile = profile_labels[
                selected_profile_label
            ]

            current_links = (
                db.table("user_employers")
                .select("employer_id")
                .eq(
                    "user_id",
                    selected_profile["id"],
                )
                .execute()
                .data
            )

            current_ids = {
                item["employer_id"]
                for item in current_links
            }

            employer_labels = {
                employer["name"]: employer
                for employer in employers
            }

            chosen = st.multiselect(
                "מעסיקים שיופיעו למשתמש",
                list(employer_labels),
                default=[
                    name
                    for name, employer
                    in employer_labels.items()
                    if employer["id"] in current_ids
                ],
            )

            if st.button(
                "שמירת שיוכים",
                type="primary",
            ):
                (
                    db.table("user_employers")
                    .delete()
                    .eq(
                        "user_id",
                        selected_profile["id"],
                    )
                    .execute()
                )

                payload = [
                    {
                        "user_id": (
                            selected_profile["id"]
                        ),
                        "employer_id": (
                            employer_labels[
                                employer_name
                            ]["id"]
                        ),
                    }
                    for employer_name in chosen
                ]

                if payload:
                    (
                        db.table("user_employers")
                        .insert(payload)
                        .execute()
                    )

                st.success("השיוכים נשמרו.")


def main() -> None:
    require_secrets()

    if "user_id" not in st.session_state:
        login_screen()
        return

    profile = get_profile(
        st.session_state.user_id
    )

    if not profile or not profile.get("active"):
        st.session_state.clear()
        st.error("המשתמש אינו פעיל.")
        return

    with st.sidebar:
        st.image("logo.png", width=170)
        st.write(profile["full_name"])

        st.caption(
            f"{ROLES_HE[profile['role']]} · "
            f"{profile.get('office_name') or ''}"
        )

        pages = [
            "סטטוס חודשי",
            "העלאת קובץ",
            "היסטוריה",
        ]

        if profile["role"] == "admin":
            pages.append("ניהול מערכת")

        page = st.radio(
            "תפריט",
            pages,
        )

        if st.button("יציאה"):
            st.session_state.clear()
            st.rerun()

    if page == "סטטוס חודשי":
        dashboard(profile)

    elif page == "העלאת קובץ":
        upload_page(profile)

    elif page == "היסטוריה":
        history_page(profile)

    else:
        admin_page(profile)


if __name__ == "__main__":
    main()
