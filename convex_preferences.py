from __future__ import annotations

import hmac
import json
import threading
from datetime import datetime

import altair as alt
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
    "student_id",
    "selected_bundle",
]


# ============================================================
# BUNDLES
# ============================================================

BUNDLES = {
    "Bundle X": "10 Samosas  ·  0 Coffees",
    "Bundle Y": "0 Samosas  ·  10 Coffees",
    "Bundle Z": "5 Samosas  ·  5 Coffees",
}


# Coordinates used for the convex graph
BUNDLE_POINTS = pd.DataFrame(
    {
        "Bundle": [
            "Bundle Y",
            "Bundle Z",
            "Bundle X",
        ],
        "Samosas": [
            0,
            5,
            10,
        ],
        "Coffees": [
            10,
            5,
            0,
        ],
    }
)


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
    Make sure the worksheet has the expected header row.
    """

    worksheet = google_worksheet()

    first_row = worksheet.row_values(1)

    if not first_row:
        worksheet.append_row(
            CSV_COLUMNS,
            value_input_option="RAW",
        )


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

    headers = values[0]

    rows = values[1:]

    responses = pd.DataFrame(
        rows,
        columns=headers,
    )

    # Make sure all required columns exist
    for column in CSV_COLUMNS:

        if column not in responses.columns:
            responses[column] = ""

    return responses[CSV_COLUMNS]


# ============================================================
# SAVE RESPONSE
# ============================================================

def save_response(
    student_id: str,
    selected_bundle: str,
) -> bool:
    """
    Save one student response to Google Sheets.

    Returns:
        True  -> response saved
        False -> student ID already exists
    """

    cleaned_id = student_id.strip()

    with csv_lock():

        responses = load_responses()

        existing_ids = (
            responses["student_id"]
            .fillna("")
            .astype(str)
            .str.strip()
            .str.casefold()
        )

        if (
            cleaned_id.casefold()
            in existing_ids.values
        ):
            return False

        worksheet = google_worksheet()

        worksheet.append_row(
            [
                (
                    datetime.now()
                    .astimezone()
                    .isoformat(
                        timespec="seconds"
                    )
                ),
                cleaned_id,
                selected_bundle,
            ],
            value_input_option="RAW",
        )

    return True


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

def results_summary(
    responses: pd.DataFrame,
) -> pd.DataFrame:
    """
    Calculate number and percentage of students
    choosing each bundle.
    """

    counts = (
        responses["selected_bundle"]
        .value_counts()
        .reindex(
            BUNDLES.keys(),
            fill_value=0,
        )
        .astype(int)
    )

    total = int(
        counts.sum()
    )

    if total:

        percentages = (
            counts / total * 100
        )

    else:

        percentages = (
            counts.astype(float)
        )

    return pd.DataFrame(
        {
            "Bundle": list(
                BUNDLES.keys()
            ),
            "Students": counts.values,
            "Percentage": (
                percentages
                .round(1)
                .values
            ),
        }
    )


# ============================================================
# CONVEX GRAPH
# ============================================================

def convex_bundle_graph(
    summary: pd.DataFrame,
) -> alt.Chart:
    """
    Create a clean convex-style preference graph.

    The horizontal order is:
        Bundle Y -> Bundle Z -> Bundle X

    This keeps Bundle Z visually between the two extreme bundles.
    The vertical position of each point is determined by the actual
    percentage of students who selected that bundle.

    Every point uses the same circle size. Percentage is represented
    only by the point's vertical position, not by bubble size.
    """

    graph_data = summary.copy()

    graph_data["Students"] = (
        graph_data["Students"]
        .fillna(0)
        .astype(int)
    )

    graph_data["Percentage"] = (
        graph_data["Percentage"]
        .fillna(0)
        .astype(float)
    )

    # Keep Z visually between the two extreme bundles.
    bundle_order = [
        "Bundle Y",
        "Bundle Z",
        "Bundle X",
    ]

    graph_data["Bundle"] = pd.Categorical(
        graph_data["Bundle"],
        categories=bundle_order,
        ordered=True,
    )

    graph_data = (
        graph_data
        .sort_values("Bundle")
        .reset_index(drop=True)
    )

    graph_data["Order"] = range(len(graph_data))

    graph_data["PercentageText"] = (
        graph_data["Percentage"]
        .map(lambda value: f"{value:.1f}%")
    )

    graph_data["PointLabel"] = (
        graph_data["Bundle"].astype(str)
        + "  •  "
        + graph_data["PercentageText"]
    )

    # --------------------------------------------------------
    # VERY LIGHT AREA UNDER THE PREFERENCE LINE
    # --------------------------------------------------------

    area = (
        alt.Chart(graph_data)
        .mark_area(
            color="#dfe8f3",
            opacity=0.28,
            interpolate="monotone",
        )
        .encode(
            x=alt.X(
                "Bundle:N",
                title=None,
                sort=bundle_order,
                axis=alt.Axis(
                    labelAngle=0,
                    labelFontSize=14,
                    labelFontWeight=600,
                    labelPadding=12,
                    domain=False,
                    ticks=False,
                ),
            ),
            y=alt.Y(
                "Percentage:Q",
                title="Percentage of students",
                scale=alt.Scale(
                    domain=[0, 100],
                    nice=False,
                ),
                axis=alt.Axis(
                    values=[0, 20, 40, 60, 80, 100],
                    labelExpr="datum.value + '%'",
                    grid=True,
                    gridColor="#f3e7df",
                    gridOpacity=1,
                    domain=False,
                    ticks=False,
                    labelPadding=8,
                ),
            ),
        )
    )

    # --------------------------------------------------------
    # CONNECTING LINE
    # --------------------------------------------------------

    line = (
        alt.Chart(graph_data)
        .mark_line(
            color="#18264a",
            strokeWidth=4,
            interpolate="monotone",
        )
        .encode(
            x=alt.X(
                "Bundle:N",
                sort=bundle_order,
            ),
            y=alt.Y(
                "Percentage:Q",
                scale=alt.Scale(
                    domain=[0, 100],
                    nice=False,
                ),
            ),
            order=alt.Order(
                "Order:Q",
            ),
        )
    )

    # --------------------------------------------------------
    # SAME-SIZED LIGHT COLORED CIRCLES
    # --------------------------------------------------------

    points = (
        alt.Chart(graph_data)
        .mark_circle(
            size=650,
            stroke="#f58220",
            strokeWidth=2,
            opacity=0.95,
        )
        .encode(
            x=alt.X(
                "Bundle:N",
                sort=bundle_order,
            ),
            y=alt.Y(
                "Percentage:Q",
                scale=alt.Scale(
                    domain=[0, 100],
                    nice=False,
                ),
            ),
            color=alt.value("#ffd2ad"),
            tooltip=[
                alt.Tooltip(
                    "Bundle:N",
                    title="Bundle",
                ),
                alt.Tooltip(
                    "Students:Q",
                    title="Students",
                ),
                alt.Tooltip(
                    "Percentage:Q",
                    title="Selected",
                    format=".1f",
                ),
            ],
        )
    )

    # --------------------------------------------------------
    # PERCENTAGE LABELS ABOVE THE CIRCLES
    # --------------------------------------------------------

    labels = (
        alt.Chart(graph_data)
        .mark_text(
            dy=-28,
            fontSize=15,
            fontWeight="bold",
            color="#d9232e",
        )
        .encode(
            x=alt.X(
                "Bundle:N",
                sort=bundle_order,
            ),
            y=alt.Y(
                "Percentage:Q",
                scale=alt.Scale(
                    domain=[0, 100],
                    nice=False,
                ),
            ),
            text=alt.Text(
                "PercentageText:N",
            ),
        )
    )

    # --------------------------------------------------------
    # FINAL CHART
    # --------------------------------------------------------

    chart = (
        area
        + line
        + points
        + labels
    ).properties(
        height=500,
        title="Convex Preference Pattern by Class Share",
    ).configure_title(
        fontSize=21,
        fontWeight=600,
        anchor="middle",
        color="#18264a",
        offset=18,
    ).configure_axis(
        labelColor="#18264a",
        titleColor="#18264a",
        titleFontSize=14,
        titlePadding=14,
    ).configure_view(
        stroke=None,
    )

    return chart


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
           STUDENT ID / PASSWORD INPUTS
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

st.write(
    "Select the **one bundle you prefer most**."
)


# ============================================================
# TABS
# ============================================================

response_tab, results_tab = st.tabs(
    [
        "Submit preference",
        "Professor Results",
    ]
)


# ============================================================
# STUDENT SUBMISSION TAB
# ============================================================

with response_tab:

    with st.form(
        "preference_form",
        clear_on_submit=True,
    ):

        student_id = st.text_input(
            "Student ID",
            placeholder=(
                "Enter your student ID"
            ),
            help=(
                "The ID is used to prevent "
                "duplicate submissions."
            ),
        )

        selected_bundle = st.radio(
            "Choose your preferred bundle",
            options=list(
                BUNDLES.keys()
            ),
            index=None,
            format_func=lambda bundle: (
                f"{bundle}  —  "
                f"{BUNDLES[bundle]}"
            ),
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

            submitted = (
                st.form_submit_button(
                    "Submit preference",
                    type="primary",
                    use_container_width=True,
                )
            )


    # --------------------------------------------------------
    # PROCESS STUDENT RESPONSE
    # --------------------------------------------------------

    if submitted:

        if not student_id.strip():

            st.error(
                "Please enter your student ID."
            )

        elif selected_bundle is None:

            st.error(
                "Please select one bundle "
                "before submitting."
            )

        elif save_response(
            student_id,
            selected_bundle,
        ):

            st.success(
                f"Your preference for "
                f"{selected_bundle} "
                f"has been recorded."
            )

        else:

            st.warning(
                "This student ID has already "
                "submitted a response."
            )


    st.caption(
        "Select one option. "
        "Each Student ID can submit once."
    )


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


        summary = results_summary(
            responses
        )

        total_students = int(
            summary[
                "Students"
            ].sum()
        )


        # ====================================================
        # CLASS RESULTS
        # ====================================================

        st.subheader(
            "Class Preference Results"
        )

        st.metric(
            "Total responses",
            total_students,
        )


        # ----------------------------------------------------
        # NO RESPONSES
        # ----------------------------------------------------

        if total_students == 0:

            st.info(
                "No student responses "
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
                "Detailed Results"
            )

            display_summary = (
                summary.copy()
            )

            display_summary[
                "Percentage"
            ] = (
                display_summary[
                    "Percentage"
                ]
                .map(
                    lambda value:
                    f"{value:.1f}%"
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
                "table.detailed-results-table tr:last-child td {"
                "border-bottom:none;"
                "}"
                "</style>"
            )

            st.markdown(
                detailed_table_css + detailed_table_html,
                unsafe_allow_html=True,
            )


            # =================================================
            # PERCENTAGE CHOOSING EACH BUNDLE
            # =================================================

            st.divider()

            st.subheader(
                "Percentage Choosing Each Bundle"
            )

            percentage_data = summary.copy()
            percentage_data["PercentageText"] = (
                percentage_data["Percentage"]
                .map(lambda value: f"{value:.1f}%")
            )

            percentage_base = (
                alt.Chart(percentage_data)
                .encode(
                    x=alt.X(
                        "Bundle:N",
                        title=None,
                        sort=[
                            "Bundle X",
                            "Bundle Y",
                            "Bundle Z",
                        ],
                        axis=alt.Axis(
                            labelAngle=0,
                            labelFontSize=13,
                        ),
                    ),
                    y=alt.Y(
                        "Percentage:Q",
                        title="Percentage",
                        scale=alt.Scale(
                            domain=[0, 100],
                            nice=False,
                        ),
                        axis=alt.Axis(
                            values=[0, 20, 40, 60, 80, 100],
                            labelExpr="datum.value + '%'",
                            gridColor="#f3e7df",
                        ),
                    ),
                    tooltip=[
                        alt.Tooltip(
                            "Bundle:N",
                            title="Bundle",
                        ),
                        alt.Tooltip(
                            "Students:Q",
                            title="Students",
                        ),
                        alt.Tooltip(
                            "Percentage:Q",
                            title="Percentage",
                            format=".1f",
                        ),
                    ],
                )
            )

            percentage_bars = (
                percentage_base
                .mark_bar(
                    cornerRadiusTopLeft=8,
                    cornerRadiusTopRight=8,
                    color="#f58220",
                )
            )

            percentage_labels = (
                percentage_base
                .mark_text(
                    dy=-10,
                    fontSize=13,
                    fontWeight="bold",
                    color="#18264a",
                )
                .encode(
                    text="PercentageText:N",
                )
            )

            percentage_chart = (
                percentage_bars
                + percentage_labels
            ).properties(
                height=380,
            ).configure_axis(
                labelColor="#18264a",
                titleColor="#18264a",
                titleFontSize=14,
                labelFontSize=13,
            ).configure_view(
                stroke=None,
            )

            st.altair_chart(
                percentage_chart,
                use_container_width=True,
            )


            # =================================================
            # CONVEX PREFERENCE GRAPH
            # =================================================

            st.divider()

            st.subheader(
                "Convex Preference Graph"
            )

            st.write(
                "The graph places **Bundle Z between Bundle Y and "
                "Bundle X**, while the vertical position of each "
                "circle is based on the **percentage of students** "
                "who selected that bundle. All circles are the same "
                "size."
            )

            st.altair_chart(
                convex_bundle_graph(
                    summary
                ),
                use_container_width=True,
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
