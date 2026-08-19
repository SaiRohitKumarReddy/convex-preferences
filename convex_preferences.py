from __future__ import annotations

import hmac
import json
import threading
from datetime import datetime, timedelta, timezone

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="Convex Preferences",
    #page_icon="🟠",
    layout="wide",
)


# ============================================================
# GOOGLE SHEETS SETTINGS
# ============================================================

GOOGLE_SHEET_ID = str(
    st.secrets["GOOGLE_SHEET_ID"]
)

GOOGLE_WORKSHEET = str(
    st.secrets["GOOGLE_WORKSHEET"]
)

CSV_COLUMNS = [
    "submitted_at",
    "student_name",
    "rank_1",
]

IST = timezone(
    timedelta(
        hours=5,
        minutes=30,
    ),
    name="IST",
)


# ============================================================
# BUNDLES
# ============================================================

BUNDLES = {
    "Bundle X": "9 Pizzas, 1 Pepsi Bottle",
    "Bundle Y": "1 Pizzas, 9 Pepsi Bottle",
    "Bundle Z": "5 Pizzas, 5 Pepsi Bottle",
}


# ============================================================
# PROFESSOR PASSWORD
# ============================================================

try:
    PROFESSOR_PASSWORD = str(
        st.secrets["PROFESSOR_PASSWORD"]
    )

except Exception:
    st.error(
        "Professor password is not configured."
    )

    st.info(
        """
        Create:

        .streamlit/secrets.toml

        and add:

        PROFESSOR_PASSWORD = "your-password"
        """
    )

    st.stop()


# ============================================================
# GOOGLE SHEETS CONNECTION
# ============================================================

try:
    GCP_SERVICE_ACCOUNT_INFO = json.loads(
        str(
            st.secrets[
                "GCP_SERVICE_ACCOUNT_JSON"
            ]
        )
    )

except Exception:
    st.error(
        "Google service account credentials "
        "are not configured correctly."
    )

    st.stop()


@st.cache_resource
def google_worksheet():
    """
    Create one shared authenticated connection
    to the Google Sheet worksheet.
    """

    scopes = [
        (
            "https://www.googleapis.com/"
            "auth/spreadsheets"
        ),
        (
            "https://www.googleapis.com/"
            "auth/drive"
        ),
    ]

    credentials = (
        Credentials.from_service_account_info(
            GCP_SERVICE_ACCOUNT_INFO,
            scopes=scopes,
        )
    )

    client = gspread.authorize(
        credentials
    )

    spreadsheet = client.open_by_key(
        GOOGLE_SHEET_ID
    )

    return spreadsheet.worksheet(
        GOOGLE_WORKSHEET
    )


# ============================================================
# SHARED GOOGLE SHEET LOCK
# ============================================================

@st.cache_resource
def csv_lock() -> threading.Lock:
    """
    One shared lock for Google Sheet access
    across Streamlit sessions.
    """
    return threading.Lock()


# ============================================================
# INITIALIZE GOOGLE SHEET
# ============================================================

def initialize_worksheet() -> None:
    """
    Make sure the worksheet has the expected Rank-1-only header row.

    The active schema is:
        submitted_at | student_name | rank_1

    If the worksheet still has the previous rank_2 and rank_3 columns,
    clear those old columns while preserving submitted_at, student_name,
    and rank_1 data already stored in columns A:C.
    """

    worksheet = google_worksheet()

    first_row = worksheet.row_values(1)

    if not first_row:
        worksheet.append_row(
            CSV_COLUMNS,
            value_input_option="RAW",
        )
        return

    if first_row[:3] != CSV_COLUMNS:
        worksheet.update(
            range_name="A1:C1",
            values=[CSV_COLUMNS],
            value_input_option="RAW",
        )

    old_rank_columns_present = (
        len(first_row) >= 5
        and first_row[3:5] == [
            "rank_2",
            "rank_3",
        ]
    )

    if old_rank_columns_present:
        worksheet.batch_clear([
            "D:E",
        ])


# ============================================================
# LOAD RESPONSES
# ============================================================

def load_responses() -> pd.DataFrame:
    """
    Load saved responses from Google Sheets.

    Returns an empty DataFrame when there are
    no student responses yet.
    """

    initialize_worksheet()

    worksheet = google_worksheet()

    values = worksheet.get_all_values()

    if len(values) <= 1:
        return pd.DataFrame(
            columns=CSV_COLUMNS
        )

    rows = []

    for row in values[1:]:
        normalized_row = (
            row
            + [""] * len(CSV_COLUMNS)
        )[:len(CSV_COLUMNS)]

        rows.append(
            normalized_row
        )

    return pd.DataFrame(
        rows,
        columns=CSV_COLUMNS,
    )


# ============================================================
# SAVE RESPONSE
# ============================================================

def save_response(
    student_name: str,
    rank_1: str,
) -> None:
    """
    Save one student's Rank 1 preference to Google Sheets.

    Student names are not treated as unique identifiers, so two or
    more students may submit using the same name.
    """

    cleaned_name = student_name.strip()

    with csv_lock():

        worksheet = google_worksheet()

        worksheet.append_row(
            [
                (
                    datetime.now(IST)
                    .isoformat(
                        timespec="seconds"
                    )
                ),
                cleaned_name,
                rank_1,
            ],
            value_input_option="RAW",
        )


# ============================================================
# RESET ALL RESPONSES
# ============================================================

def reset_all_responses() -> None:
    """
    Permanently delete all saved student responses
    from Google Sheets while keeping the header row.
    """

    with csv_lock():

        worksheet = google_worksheet()

        worksheet.clear()

        worksheet.append_row(
            CSV_COLUMNS,
            value_input_option="RAW",
        )


# ============================================================
# RESULTS SUMMARY
# ============================================================

RANK_COLUMNS = [
    ("rank_1", "Rank 1"),
]


def valid_ranked_responses(
    responses: pd.DataFrame,
) -> pd.DataFrame:
    """
    Keep only rows with a non-blank student name and one valid
    Rank 1 bundle preference.
    """

    if responses.empty:
        return responses.copy()

    valid = responses.copy()

    valid["student_name"] = (
        valid["student_name"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    rank_columns = [
        column
        for column, _ in RANK_COLUMNS
    ]

    for column in rank_columns:
        valid[column] = (
            valid[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    valid_bundle_names = set(BUNDLES.keys())

    valid_mask = (
        valid["student_name"].ne("")
    )

    for column in rank_columns:
        valid_mask &= valid[column].isin(
            valid_bundle_names
        )

    valid_mask &= (
        valid[rank_columns]
        .nunique(axis=1)
        .eq(len(rank_columns))
    )

    return (
        valid.loc[valid_mask]
        .copy()
        .reset_index(drop=True)
    )


def results_summary(
    responses: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate the number and percentage of valid students selecting
    each bundle as their Rank 1 preference.

    The bundle percentages add up to 100% whenever at least one
    valid response exists.
    """

    valid = valid_ranked_responses(
        responses
    )

    total_students = len(valid)
    rows = []

    for rank_column, rank_label in RANK_COLUMNS:

        counts = (
            valid[rank_column]
            .value_counts()
            .reindex(
                BUNDLES.keys(),
                fill_value=0,
            )
            .astype(int)
        )

        for bundle in BUNDLES.keys():

            students = int(
                counts.loc[bundle]
            )

            if total_students:
                percentage = (
                    students
                    / total_students
                    * 100
                )
            else:
                percentage = 0.0

            rows.append(
                {
                    "Rank": rank_label,
                    "Bundle": bundle,
                    "Students": students,
                    "Percentage": round(
                        percentage,
                        1,
                    ),
                }
            )

    return pd.DataFrame(rows)


def detailed_results_summary(
    summary: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build an easy-to-read professor table.

    Each row is one rank and each bundle column shows both the
    number of students and the percentage for that rank. The final
    column identifies the bundle or bundles with the highest share.
    """

    rows = []

    for _, rank_label in RANK_COLUMNS:

        row = {
            "Rank": rank_label,
        }

        rank_data = summary[
            summary["Rank"] == rank_label
        ].copy()

        for bundle in BUNDLES.keys():

            match = rank_data[
                rank_data["Bundle"] == bundle
            ]

            if match.empty:
                students = 0
                percentage = 0.0
            else:
                students = int(
                    match.iloc[0]["Students"]
                )
                percentage = float(
                    match.iloc[0]["Percentage"]
                )

            row[bundle] = (
                f"{students} students ({percentage:.1f}%)"
            )

        if rank_data.empty:
            highest_text = "—"
        else:
            highest_percentage = float(
                rank_data["Percentage"].max()
            )

            winners = (
                rank_data.loc[
                    rank_data["Percentage"].eq(
                        highest_percentage
                    ),
                    "Bundle",
                ]
                .astype(str)
                .tolist()
            )

            highest_text = (
                f"{' & '.join(winners)} — "
                f"{highest_percentage:.1f}%"
            )

        row["Highest bundle"] = highest_text
        rows.append(row)

    return pd.DataFrame(rows)


# ============================================================
# SESSION STATE
# ============================================================

if (
    "professor_authenticated"
    not in st.session_state
):
    st.session_state[
        "professor_authenticated"
    ] = False


if (
    "reset_completed"
    not in st.session_state
):
    st.session_state[
        "reset_completed"
    ] = False


if (
    "confirm_reset"
    not in st.session_state
):
    st.session_state[
        "confirm_reset"
    ] = False


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>

        :root {
            --bitsom-navy: #18264a;
            --bitsom-red: #d9232e;
            --bitsom-orange: #f58220;
        }


        /* ----------------------------------------
           MAIN PAGE
        ---------------------------------------- */

        .block-container {
            max-width: 1550px;
            width: 96%;
            padding-top: 2.5rem;
            padding-left: 2rem;
            padding-right: 2rem;
            padding-bottom: 2rem;
        }


        /* ----------------------------------------
           TITLE
        ---------------------------------------- */

        h1 {
            color: var(--bitsom-navy);
            letter-spacing: -0.04em;
            font-size: 3rem !important;
        }

        h2,
        h3 {
            color: var(--bitsom-navy);
        }


        /* ----------------------------------------
           TABS
        ---------------------------------------- */

        div[data-baseweb="tab-list"] {
            gap: 0.65rem;

            /* Keep the underline/border away from the capsules. */
            padding-bottom: 12px !important;
            margin-bottom: 0.75rem !important;
        }

        button[data-baseweb="tab"] {
            min-height: 42px;
            padding: 0.45rem 1.15rem !important;
            border: 1.5px solid var(--bitsom-orange) !important;
            border-radius: 999px !important;
            background: #ffffff !important;
            color: var(--bitsom-navy) !important;
            font-size: 1rem;
            font-weight: 600;
            transition:
                background 0.15s ease,
                color 0.15s ease,
                border-color 0.15s ease;
        }

        button[data-baseweb="tab"][aria-selected="true"] {
            background: var(--bitsom-orange) !important;
            border-color: var(--bitsom-orange) !important;
            color: #ffffff !important;
        }

        button[data-baseweb="tab"][aria-selected="false"]:hover {
            background: #fff8f2 !important;
        }

        button[data-baseweb="tab"] p {
            color: inherit !important;
        }

        div[data-baseweb="tab-highlight"] {
            display: none;
        }


        /* ----------------------------------------
           FORM
        ---------------------------------------- */

        div[data-testid="stForm"] {
            width: 100%;
            border: 1px solid #d9dde7;
            border-radius: 14px;
            padding: 1.6rem;
        }

        /* Student preference form only:
           keep a natural compact height while using the full width. */
        div[data-testid="stForm"]:has(div[role="radiogroup"]) {
            width: 100% !important;
            min-height: auto !important;
            height: auto !important;
            box-sizing: border-box !important;

            padding:
                2rem
                2.2rem
                1.8rem
                2.2rem !important;
        }


        /* ----------------------------------------
           STUDENT NAME / PASSWORD INPUTS
        ---------------------------------------- */

        div[data-testid="stTextInput"] {
            width: 100%;
        }

        div[data-testid="stTextInput"] div[data-baseweb="input"] {
            min-height: 52px !important;
            height: 52px !important;
            display: flex !important;
            align-items: center !important;
            border-radius: 10px !important;
        }

        div[data-testid="stTextInput"] input {
            height: 52px !important;
            min-height: 52px !important;
            box-sizing: border-box !important;
            font-size: 1.05rem !important;
            border-radius: 10px !important;
            padding: 0 1rem !important;
            line-height: normal !important;
            display: flex !important;
            align-items: center !important;
        }

        div[data-testid="stTextInput"] input::placeholder {
            line-height: normal !important;
        }

        div[data-testid="stTextInput"]
        input:focus {
            border-color:
                var(--bitsom-orange);

            box-shadow:
                0 0 0 1px
                var(--bitsom-orange);
        }


        /* ----------------------------------------
           BUNDLE RADIO CARDS
        ---------------------------------------- */


        /* Force Streamlit's element wrapper for the radio widget
           to occupy the entire available form width. */
        div[data-testid="stElementContainer"]:has(div[data-testid="stRadio"]) {
            width: 100% !important;
            max-width: none !important;
        }

        div[data-testid="stElementContainer"]:has(div[data-testid="stRadio"]) > div {
            width: 100% !important;
            max-width: none !important;
        }

        /* Center the whole bundle-selection section in the form. */
        div[data-testid="stRadio"] {
            width: 100% !important;
            max-width: none !important;
        }

        div[data-testid="stRadio"] > div {
            width: 100% !important;
        }

        div[data-testid="stRadio"] div[role="radiogroup"] {
            width: 100% !important;
            max-width: none !important;
            margin-left: auto !important;
            margin-right: auto !important;
        }

        /* Center and strengthen the bundle-section heading. */
        div[data-testid="stRadio"] > label {
            width: 100% !important;
            display: flex !important;
            justify-content: center !important;
            text-align: center !important;
            margin-bottom: 0.75rem !important;
        }

        div[data-testid="stRadio"] > label p {
            width: 100% !important;
            text-align: center !important;
            font-size: 1.05rem !important;
            font-weight: 700 !important;
            color: var(--bitsom-navy) !important;
        }

        div[role="radiogroup"] {
            width: 100% !important;
            max-width: none !important;

            display: grid !important;
            grid-template-columns:
                repeat(3, minmax(0, 1fr)) !important;

            align-items: stretch !important;
            justify-content: stretch !important;

            gap: 1.2rem !important;
        }

        div[role="radiogroup"] > label {
            width: 100% !important;
            min-width: 0 !important;
            max-width: none !important;
            min-height: 112px;

            box-sizing: border-box;

            display: flex !important;
            align-items: center !important;
            justify-content: center !important;

            background: #ffffff;

            border:
                2px solid
                #d9dde7;

            border-radius: 12px;

            padding:
                1.4rem
                1.5rem;

            margin: 0;

            transition:
                border-color 0.15s ease,
                background 0.15s ease,
                transform 0.15s ease;
        }

        div[role="radiogroup"] > label p {
            color:
                var(--bitsom-navy);

            font-size: 1.02rem;

            font-weight: 600;
            line-height: 1.35;
            text-align: center !important;
        }

        div[role="radiogroup"] > label:hover {
            background: #fff8f2;

            border-color:
                var(--bitsom-orange);

            transform:
                translateY(-1px);
        }

        div[role="radiogroup"]
        > label:has(input:checked) {
            background: #fff8f2;

            border-color:
                var(--bitsom-orange);
        }

        div[role="radiogroup"] input {
            accent-color:
                var(--bitsom-red);

            transform:
                scale(1.3);
        }


        /* ----------------------------------------
           FORM SUBMIT
        ---------------------------------------- */

        div[data-testid="stFormSubmitButton"]
        button {
            min-height: 44px !important;
            height: 44px !important;
            padding: 0.45rem 1.25rem !important;

            background:
                var(--bitsom-red);

            border-color:
                var(--bitsom-red);

            border-radius:
                999px !important;

            font-size:
                0.98rem !important;

            font-weight:
                600;
        }

        div[data-testid="stFormSubmitButton"]
        button:hover {
            background:
                var(--bitsom-navy);

            border-color:
                var(--bitsom-navy);
        }


        /* ----------------------------------------
           GENERAL BUTTONS
        ---------------------------------------- */

        div[data-testid="stButton"] button {
            min-height: 48px;
            border-radius: 8px;
            font-weight: 600;
        }

        .st-key-join_game_button button {
            border-radius: 999px !important;
            padding-left: 1.4rem !important;
            padding-right: 1.4rem !important;
        }


        /* ----------------------------------------
           DOWNLOAD BUTTON
        ---------------------------------------- */

        div[data-testid="stDownloadButton"] {
            width: fit-content;
        }

        div[data-testid="stDownloadButton"] button {
            width: auto !important;
            min-height: 40px !important;
            padding: 0.45rem 0.9rem !important;
            border-radius: 8px !important;
            font-size: 0.92rem !important;
            font-weight: 600 !important;

            background:
                var(--bitsom-orange) !important;

            border-color:
                var(--bitsom-orange) !important;

            color:
                #ffffff !important;
        }

        div[data-testid="stDownloadButton"] button:hover {
            background:
                #dd6f12 !important;

            border-color:
                #dd6f12 !important;

            color:
                #ffffff !important;
        }


        /* ----------------------------------------
           METRIC CARDS
        ---------------------------------------- */

        div[data-testid="stMetric"] {
            border-left:
                5px solid
                var(--bitsom-orange);

            padding:
                1rem 1.2rem;

            background:
                #fff8f2;

            border-radius:
                10px;

            box-shadow:
                0 2px 10px
                rgba(24, 38, 74, 0.06);
        }

        div[data-testid="stMetric"] label,
        div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
            color:
                var(--bitsom-navy) !important;
        }

        div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color:
                var(--bitsom-orange) !important;
        }


        /* ----------------------------------------
           MOBILE
        ---------------------------------------- */

        @media (
            max-width: 900px
        ) {

            div[data-testid="stForm"]:has(div[role="radiogroup"]) {
                height: auto !important;
                min-height: auto !important;
                padding: 1.25rem !important;
            }

            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
            }

            h1 {
                font-size:
                    2.2rem !important;
            }

            div[data-testid="stRadio"] div[role="radiogroup"] {
                width: 100% !important;
                max-width: none !important;
                display: grid !important;
                grid-template-columns: 1fr !important;
            }

            div[role="radiogroup"]
            > label {
                width: 100% !important;
                flex: 1 1 auto !important;
                min-height: 78px;
            }
        }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# PAGE HEADER
# ============================================================

st.title(
    "Convex Preferences"
)


# ============================================================
# TABS
# ============================================================

def handle_main_tab_change() -> None:
    """
    Automatically lock professor results whenever the user
    returns to the student submission tab.
    """

    if st.session_state.get(
        "main_tabs"
    ) == "Submit preference":
        st.session_state[
            "professor_authenticated"
        ] = False


response_tab, results_tab = st.tabs(
    [
        "Submit preference",
        "Professor Results",
    ],
    key="main_tabs",
    on_change=handle_main_tab_change,
)


# ============================================================
# STUDENT SUBMISSION TAB
# ============================================================

def confirm_student_name() -> None:
    """
    Lock the typed student name when the text input is submitted
    with Enter. Blank names are not accepted.
    """

    entered_name = str(
        st.session_state.get(
            "student_name_input",
            "",
        )
    ).strip()

    if entered_name:
        st.session_state[
            "confirmed_student_name"
        ] = entered_name
        st.session_state[
            "student_name_error"
        ] = False
    else:
        st.session_state[
            "student_name_error"
        ] = True


with response_tab:

    # Clear the completed response only on the rerun after saving.
    if st.session_state.pop(
        "clear_preference_after_save",
        False,
    ):
        for key in [
            "student_name_input",
            "confirmed_student_name",
            "student_name_error",
            "rank_1_choice",
        ]:
            st.session_state.pop(
                key,
                None,
            )

    if st.session_state.pop(
        "preference_saved_message",
        False,
    ):
        st.success(
            "Your Rank 1 bundle preference has been recorded."
        )

    confirmed_student_name = (
        st.session_state.get(
            "confirmed_student_name"
        )
    )

    # --------------------------------------------------------
    # STUDENT NAME
    #
    # Until a non-blank name is entered and submitted with Enter,
    # the Rank 1 preference control is not shown.
    # --------------------------------------------------------

    if not confirmed_student_name:

        st.text_input(
            "Student Name",
            placeholder=(
                "Enter your name and press Enter"
            ),
            key="student_name_input",
            on_change=confirm_student_name,
        )

        st.button(
            "Join the game",
            key="join_game_button",
            type="primary",
            on_click=confirm_student_name,
        )

        if st.session_state.get(
            "student_name_error",
            False,
        ):
            st.error(
                "Please enter your name."
            )

    else:

        student_name = str(
            confirmed_student_name
        ).strip()

        st.success(
            f"**Student Name:** {student_name}"
        )

        st.write(
            "Select the bundle that is your "
            "**highest preference (Rank 1)**."
        )

        bundle_keys = list(
            BUNDLES.keys()
        )

        def format_bundle(
            bundle: str,
        ) -> str:
            return (
                f"{bundle}  —  "
                f"{BUNDLES[bundle]}"
            )

        rank_1_choice = st.radio(
            (
                "Rank 1 — Which bundle is "
                "your highest preference?"
            ),
            options=bundle_keys,
            index=None,
            format_func=format_bundle,
            key="rank_1_choice",
        )

        if rank_1_choice is not None:

            st.info(
                "Selected for Rank 1: "
                f"**{rank_1_choice}**  —  "
                f"{BUNDLES[rank_1_choice]}"
            )

            submit_left, submit_center, submit_right = (
                st.columns(
                    [
                        2,
                        1,
                        2,
                    ]
                )
            )

            with submit_center:

                submitted = st.button(
                    "Submit Preference",
                    type="primary",
                    use_container_width=True,
                )

            if submitted:

                save_response(
                    student_name,
                    rank_1_choice,
                )

                st.session_state[
                    "clear_preference_after_save"
                ] = True

                st.session_state[
                    "preference_saved_message"
                ] = True

                st.rerun()


# ============================================================
# PROFESSOR RESULTS TAB
# ============================================================

with results_tab:

    # ========================================================
    # NOT LOGGED IN
    # ========================================================

    if not st.session_state[
        "professor_authenticated"
    ]:

        st.subheader(
            "Professor Access"
        )

        st.info(
            "Class results are protected."
        )

        st.write(
            "Enter the professor password "
            "to view the results."
        )


        # ----------------------------------------------------
        # PASSWORD FORM
        # ----------------------------------------------------

        with st.form(
            "professor_login_form"
        ):

            entered_password = (
                st.text_input(
                    "Professor Password",
                    type="password",
                    placeholder=(
                        "Enter professor password"
                    ),
                )
            )

            login_clicked = (
                st.form_submit_button(
                    "Unlock Results",
                    type="primary",
                    use_container_width=True,
                )
            )


        # ----------------------------------------------------
        # CHECK PASSWORD
        # ----------------------------------------------------

        if login_clicked:

            password_correct = (
                hmac.compare_digest(
                    entered_password,
                    PROFESSOR_PASSWORD,
                )
            )

            if password_correct:

                st.session_state[
                    "professor_authenticated"
                ] = True

                st.rerun()

            else:

                st.error(
                    "Incorrect password."
                )


    # ========================================================
    # PROFESSOR LOGGED IN
    # ========================================================

    else:

        # ----------------------------------------------------
        # HEADER / LOCK BUTTON
        # ----------------------------------------------------

        header_left, header_right = (
            st.columns(
                [
                    5,
                    1,
                ]
            )
        )

        with header_left:

            st.success(
                "Professor view unlocked."
            )


        with header_right:

            if st.button(
                "🔒 Lock",
                use_container_width=True,
            ):

                st.session_state[
                    "professor_authenticated"
                ] = False

                st.rerun()


        # ----------------------------------------------------
        # RESET SUCCESS MESSAGE
        # ----------------------------------------------------

        if st.session_state.get(
            "reset_completed",
            False,
        ):

            # Clear the checkbox state BEFORE the checkbox widget
            # is instantiated later in this rerun.
            st.session_state[
                "confirm_reset"
            ] = False

            st.success(
                "All student responses "
                "have been deleted."
            )

            st.session_state[
                "reset_completed"
            ] = False


        # ----------------------------------------------------
        # LOAD DATA
        # ----------------------------------------------------

        with csv_lock():

            responses = (
                load_responses()
            )


        valid_responses = (
            valid_ranked_responses(
                responses
            )
        )

        summary = results_summary(
            valid_responses
        )

        total_students = len(
            valid_responses
        )


        # ====================================================
        # CLASS RESULTS
        # ====================================================

        st.subheader(
            "Total Responses"
        )

        st.metric(
            "Total valid responses",
              total_students,
        )

        # The table below uses valid Rank 1 preferences only.


        # ----------------------------------------------------
        # NO RESPONSES
        # ----------------------------------------------------

        if total_students == 0:

            st.info(
                "No valid student responses "
                "have been submitted yet."
            )


        # ----------------------------------------------------
        # RESULTS AVAILABLE
        # ----------------------------------------------------

        else:

            # =================================================
            # DETAILED RESULT TABLE
            # =================================================

            st.divider()

            st.subheader(
                "Rank 1 Distribution"
            )

            #st.caption(
             #   "Read each row from left to right. Each bundle cell shows "
              #  "student count and percentage for that rank. The final "
               # "column shows the highest-share bundle for that rank."
            #)

            display_summary = (
                detailed_results_summary(
                    summary
                )
            )

            # Render as HTML so the header and every result value
            # are reliably center-aligned in Streamlit.
            detailed_table_html = (
                display_summary.to_html(
                    index=False,
                    escape=True,
                    classes="detailed-results-table",
                    border=0,
                )
            )

            # Build the HTML with no leading Markdown indentation.
            # Otherwise Streamlit can display the <table> markup as text.
            detailed_table_css = (
                "<style>"
                "table.detailed-results-table {"
                "width:100%;"
                "border-collapse:separate;"
                "border-spacing:0;"
                "overflow:hidden;"
                "border:1px solid #f2b37f;"
                "border-radius:12px;"
                "background:#ffffff;"
                "box-shadow:0 2px 10px rgba(24,38,74,0.05);"
                "}"
                "table.detailed-results-table th {"
                "text-align:center !important;"
                "padding:0.9rem 1rem;"
                "color:#ffffff;"
                "background:#18264a;"
                "border-bottom:3px solid #f58220;"
                "font-weight:700;"
                "}"
                "table.detailed-results-table td {"
                "text-align:center !important;"
                "padding:0.9rem 1rem;"
                "color:#18264a;"
                "border-bottom:1px solid #f5ded0;"
                "font-weight:500;"
                "}"
                "table.detailed-results-table tbody tr:nth-child(odd) td {"
                "background:#fff8f2;"
                "}"
                "table.detailed-results-table tbody tr:nth-child(even) td {"
                "background:#ffffff;"
                "}"
                "table.detailed-results-table tbody tr:hover td {"
                "background:#fff1e6;"
                "}"
                "table.detailed-results-table td:first-child {"
                "font-weight:700;"
                "}"
                "table.detailed-results-table td:last-child {"
                "font-weight:700;"
                "color:#d9232e;"
                "}"
                "table.detailed-results-table tr:last-child td {"
                "border-bottom:none;"
                "}"
                "</style>"
            )

            st.markdown(
                detailed_table_css + detailed_table_html,
                unsafe_allow_html=True,
            )

            st.success(
                "**Poll Result:** Averages preferred to Extremes"
            )


            # =================================================
            # DOWNLOAD CSV
            # =================================================

            st.download_button(
                "⬇️ Download Responses as CSV",
                data=(
                    responses
                    .to_csv(
                        index=False
                    )
                    .encode(
                        "utf-8"
                    )
                ),
                file_name=(
                    "convex_preferences_responses.csv"
                ),
                mime="text/csv",
                use_container_width=False,
            )


        # ====================================================
        # REFRESH RESULTS
        # ====================================================

        st.divider()

        refresh_col, lock_col = (
            st.columns(2)
        )


        with refresh_col:

            if st.button(
                "🔄 Refresh Results",
                use_container_width=True,
            ):

                st.rerun()


        with lock_col:

            if st.button(
                "🔒 Lock Professor View",
                use_container_width=True,
            ):

                st.session_state[
                    "professor_authenticated"
                ] = False

                st.rerun()


        # ====================================================
        # RESET / DANGER ZONE
        # ====================================================

        st.divider()

        st.subheader(
            "⚠️ Reset Class Data"
        )

        st.error(
            """
            **Danger Zone**

            Resetting the class data will permanently
            delete every submitted student response.
            """
        )


        # ----------------------------------------------------
        # RESET CONFIRMATION
        # ----------------------------------------------------

        confirm_reset = (
            st.checkbox(
                (
                    "I understand that this "
                    "will permanently delete "
                    "all student responses."
                ),
                key="confirm_reset",
            )
        )


        # ----------------------------------------------------
        # RESET BUTTON
        # ----------------------------------------------------

        reset_clicked = st.button(
            "🗑️ Reset All Responses",
            disabled=(
                not confirm_reset
            ),
            type="primary",
            use_container_width=True,
        )


        # ----------------------------------------------------
        # EXECUTE RESET
        # ----------------------------------------------------

        if reset_clicked:

            reset_all_responses()

            st.session_state[
                "reset_completed"
            ] = True

            # Do not modify confirm_reset here. The checkbox with
            # this key has already been instantiated in this run.
            # It is cleared safely at the top of the next rerun.
            st.rerun()
