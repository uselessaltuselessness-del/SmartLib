import streamlit as st

# ────────────────────────────────────────────────
# MUST BE THE VERY FIRST STREAMLIT CALL
# ────────────────────────────────────────────────
st.set_page_config(page_title="SmartLib System", layout="wide")

import firebase_admin
from firebase_admin import credentials, firestore
import requests
import pandas as pd
import qrcode
from PIL import Image
import io

# ────────────────────────────────────────────────
# 1. FIREBASE INITIALIZATION
# ────────────────────────────────────────────────
db = None

if not firebase_admin._apps:
    try:
        secret_dict = dict(st.secrets["firebase"])
        secret_dict["private_key"] = secret_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(secret_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Failed to connect to Firebase. Error: {e}")
        st.stop()

try:
    db = firestore.client()
except Exception as e:
    st.error(f"Failed to create Firestore client. Error: {e}")
    st.stop()

# ────────────────────────────────────────────────
# 2. QR CODE HELPER
# ────────────────────────────────────────────────
def generate_qr_bytes(payload: str) -> bytes:
    """
    Generates a QR code PNG from a string payload.
    Returns raw bytes ready for st.image() or download_button().
    Uses pil_wrapper.get_image() to access the underlying PIL Image
    directly, which guarantees .save(buf, format="PNG") works on
    all versions of the qrcode + Pillow combination.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    pil_wrapper = qr.make_image(fill_color="black", back_color="white")
    pil_img: Image.Image = pil_wrapper.get_image()   # unwrap to real PIL Image

    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

# ────────────────────────────────────────────────
# 3. SESSION STATE DEFAULTS
# ────────────────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None
if "latest_hold" not in st.session_state:
    # Stores {"hold_id": str, "title": str, "student": str} after a hold is placed
    st.session_state.latest_hold = None

def logout():
    st.session_state.user = None
    st.session_state.latest_hold = None
    st.rerun()

# ────────────────────────────────────────────────
# 4. HEADER & SIDEBAR AUTH
# ────────────────────────────────────────────────
st.title("📚 SmartLib University Library System")
st.sidebar.header("🔐 University CAS Gateway")

if st.session_state.user is None:
    st.sidebar.subheader("Login to Access Personal Features")
    login_email = st.sidebar.text_input("University Email (e.g., student_good@univ.edu)")
    login_role  = st.sidebar.selectbox("Role", ["Student", "Librarian", "System Administrator"])

    if st.sidebar.button("Login via CAS"):
        if login_email:
            user_ref = db.collection("users").document(login_email)
            user_doc = user_ref.get()
            if user_doc.exists:
                user_data = user_doc.to_dict()
            else:
                user_data = {"email": login_email, "role": login_role, "fines": 0.0}
                user_ref.set(user_data)
            st.session_state.user = user_data
            st.success(f"Logged in as {user_data['email']}")
            st.rerun()
        else:
            st.sidebar.error("Please enter an email.")
else:
    st.sidebar.write(f"**Logged in as:** {st.session_state.user['email']}")
    st.sidebar.write(f"**Role:** {st.session_state.user['role']}")

    if st.session_state.user["role"] == "Student":
        live_doc = db.collection("users").document(st.session_state.user["email"]).get()
        live     = live_doc.to_dict() if live_doc.exists else {}
        st.sidebar.warning(f"Active Fines: ${live.get('fines', 0.0):.2f}")

    if st.sidebar.button("Logout"):
        logout()

# ────────────────────────────────────────────────
# 5. TAB NAVIGATION
# ────────────────────────────────────────────────
tabs = ["🔍 Public Catalog Search"]
if st.session_state.user:
    role = st.session_state.user["role"]
    if role == "Student":
        tabs += ["📖 Book Borrowing & Holds", "💻 Digital Resources", "🔑 Room Reservations"]
    elif role == "Librarian":
        tabs += ["📋 Catalog Management", "💸 Fine Management", "🚫 Override Controls"]
    elif role == "System Administrator":
        tabs += ["📊 Usage Reports", "⚙️ Permissions Engine"]

active_tab = st.radio("Navigate System Engine:", tabs, horizontal=True)

# ════════════════════════════════════════════════
# TAB 1 — PUBLIC CATALOG SEARCH
# ════════════════════════════════════════════════
if active_tab == "🔍 Public Catalog Search":
    st.header("Global Catalog Discovery")
    search_query = st.text_input("Search by Title, Author, or ISBN")

    books = [doc.to_dict() for doc in db.collection("books").stream()]
    if books:
        df = pd.DataFrame(books)
        if search_query:
            df = df[
                df["title"].str.contains(search_query, case=False, na=False)  |
                df["author"].str.contains(search_query, case=False, na=False) |
                df["isbn"].str.contains(search_query, case=False, na=False)
            ]
        st.dataframe(df[["isbn", "title", "author", "available"]], use_container_width=True)
    else:
        st.info("The catalog is currently empty. Ask a librarian to add books.")

# ════════════════════════════════════════════════
# TAB 2 — STUDENT: BORROWING & HOLDS
# ════════════════════════════════════════════════
elif active_tab == "📖 Book Borrowing & Holds":
    st.header("Physical Book Placements")

    # Always fetch a fresh fine balance
    live_doc  = db.collection("users").document(st.session_state.user["email"]).get()
    live_user = live_doc.to_dict() if live_doc.exists else {}
    current_fines = live_user.get("fines", 0.0)

    # ── BUSINESS RULE: block if fines > $10 ────────────────────────────────
    if current_fines > 10.0:
        st.error(
            f"❌ Access Denied: Your account has an unpaid fine of **${current_fines:.2f}**. "
            "Borrowing is locked until fines are cleared."
        )
    else:
        st.success("✅ Account Status Clear — Eligible to place holds.")

        books_ref       = db.collection("books").where("available", "==", True)
        available_books = {doc.to_dict()["title"]: doc.id for doc in books_ref.stream()}

        if available_books:
            selected_title = st.selectbox("Select an available book:", list(available_books.keys()))

            if st.button("📌 Place a Hold"):
                book_id  = available_books[selected_title]
                # .add() returns (update_time, DocumentReference)
                hold_ref = db.collection("holds").add({
                    "student" : st.session_state.user["email"],
                    "book_id" : book_id,
                    "title"   : selected_title,
                    "status"  : "Active",
                })
                new_hold_id = hold_ref[1].id

                db.collection("books").document(book_id).update({"available": False})

                # ── Persist hold info BEFORE rerun so QR renders immediately ──
                st.session_state.latest_hold = {
                    "hold_id" : new_hold_id,
                    "title"   : selected_title,
                    "student" : st.session_state.user["email"],
                }
                st.rerun()
        else:
            st.info("No books are currently physically available.")

    # ── IMMEDIATE QR CODE shown right after hold is placed ─────────────────
    if st.session_state.latest_hold:
        lh = st.session_state.latest_hold
        st.divider()
        st.subheader("🎉 Hold Confirmed — Your Self-Checkout QR Pass")

        qr_payload = f"HOLD_ID:{lh['hold_id']}|USER:{lh['student']}"
        qr_bytes   = generate_qr_bytes(qr_payload)

        col_img, col_info = st.columns([1, 2])
        col_img.image(qr_bytes, width=200, caption="Scan at the self-checkout kiosk")
        col_info.markdown(f"""
**Book:** {lh['title']}  
**Token ID:** `{lh['hold_id']}`  
**Student:** {lh['student']}  

Scan this QR code at any self-checkout kiosk to collect your book.
        """)
        col_info.download_button(
            label     = "💾 Download QR Pass (PNG)",
            data      = qr_bytes,
            file_name = f"SmartLib_QR_{lh['hold_id']}.png",
            mime      = "image/png",
            key       = "latest_qr_download",
        )
        if st.button("✅ Done — Dismiss QR"):
            st.session_state.latest_hold = None
            st.rerun()

    # ── ALL ACTIVE HOLDS ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Your Active Hold Vouchers")
    my_holds = list(
        db.collection("holds").where("student", "==", st.session_state.user["email"]).stream()
    )

    if not my_holds:
        st.info("You have no active holds.")
    else:
        for hold in my_holds:
            h = hold.to_dict()
            with st.expander(f"📘 {h['title']}  —  ID: `{hold.id}`"):
                qr_payload = f"HOLD_ID:{hold.id}|USER:{h['student']}"
                qr_bytes   = generate_qr_bytes(qr_payload)

                c1, c2 = st.columns([1, 3])
                c1.image(qr_bytes, width=150, caption="Scan at Kiosk")
                c2.write(f"**Token ID:** `{hold.id}`")
                c2.write(f"**Status:** {h.get('status', 'Active')}")
                c2.download_button(
                    label     = "💾 Download QR Pass (PNG)",
                    data      = qr_bytes,
                    file_name = f"SmartLib_QR_{hold.id}.png",
                    mime      = "image/png",
                    key       = f"dl_{hold.id}",
                )

# ════════════════════════════════════════════════
# TAB 3 — STUDENT: DIGITAL RESOURCES
# ════════════════════════════════════════════════
elif active_tab == "💻 Digital Resources":
    st.header("Institutional Research Repository")

    mock_papers = [
        {"title": "Quantum Computation Elements",   "size": "2.4 MB"},
        {"title": "Database Schemas Analysis",       "size": "1.1 MB"},
        {"title": "Modern Cryptography Principles",  "size": "3.7 MB"},
    ]
    for paper in mock_papers:
        col1, col2 = st.columns([3, 1])
        col1.write(f"📄 **{paper['title']}** ({paper['size']})")
        col2.download_button(
            label     = "📥 Download PDF",
            data      = f"Mock PDF content for: {paper['title']}",
            file_name = f"{paper['title']}.pdf",
            key       = f"pdf_{paper['title']}",
        )

# ════════════════════════════════════════════════
# TAB 4 — STUDENT: ROOM RESERVATIONS
# ════════════════════════════════════════════════
elif active_tab == "🔑 Room Reservations":
    st.header("Smart Study Room Booking")

    with st.form("room_form"):
        room_selection = st.selectbox("Room", ["Room A — 4 seats", "Room B — 8 seats", "Room C — 12 seats"])
        time_slot      = st.selectbox("Time Slot", [
            "09:00 AM – 11:00 AM",
            "11:00 AM – 01:00 PM",
            "01:00 PM – 03:00 PM",
            "03:00 PM – 05:00 PM",
        ])
        group_invites = st.text_area(
            "Invite Group Members (optional — comma-separated university emails)"
        )
        if st.form_submit_button("Confirm Reservation"):
            invite_list = (
                [e.strip() for e in group_invites.split(",") if e.strip()]
                if group_invites else []
            )
            db.collection("reservations").add({
                "room"            : room_selection,
                "slot"            : time_slot,
                "reserved_by"     : st.session_state.user["email"],
                "invited_members" : invite_list,
            })
            st.success(f"✅ **{room_selection}** locked for **{time_slot}**!")
            if invite_list:
                st.info(f"Invites sent to: {', '.join(invite_list)}")

# ════════════════════════════════════════════════
# TAB 5 — LIBRARIAN: CATALOG MANAGEMENT
# ════════════════════════════════════════════════
elif active_tab == "📋 Catalog Management":
    st.header("Catalog Management — National Bibliographic API")

    isbn_input = st.text_input("Enter Book ISBN to auto-fetch metadata (e.g., 9780143111597)")
    if st.button("🔎 Fetch Metadata from National Database"):
        if isbn_input:
            try:
                resp = requests.get(
                    f"https://openlibrary.org/api/books"
                    f"?bibkeys=ISBN:{isbn_input}&jscmd=data&format=json",
                    timeout=10,
                ).json()
                key = f"ISBN:{isbn_input}"
                if key in resp:
                    st.session_state.fetched_title  = resp[key].get("title", "Unknown Title")
                    st.session_state.fetched_author = resp[key].get(
                        "authors", [{"name": "Unknown"}]
                    )[0]["name"]
                    st.session_state.fetched_isbn   = isbn_input
                    st.success("✅ Metadata fetched successfully!")
                else:
                    st.error("No metadata found for that ISBN.")
            except Exception as e:
                st.error(f"API error: {e}")

    title_field  = st.text_input("Book Title",  value=st.session_state.get("fetched_title",  ""))
    author_field = st.text_input("Author Name", value=st.session_state.get("fetched_author", ""))
    isbn_field   = st.text_input("ISBN",        value=st.session_state.get("fetched_isbn",   ""))

    col_add, col_remove = st.columns(2)
    with col_add:
        if st.button("➕ Commit to Catalog"):
            if isbn_field and title_field:
                db.collection("books").document(isbn_field).set({
                    "isbn": isbn_field, "title": title_field,
                    "author": author_field, "available": True,
                })
                st.success(f"📚 *{title_field}* catalogued successfully.")
            else:
                st.error("ISBN and Title are required.")
    with col_remove:
        remove_isbn = st.text_input("ISBN to Remove")
        if st.button("🗑️ Remove from Catalog"):
            if remove_isbn:
                db.collection("books").document(remove_isbn).delete()
                st.success(f"Removed ISBN `{remove_isbn}` from catalog.")

# ════════════════════════════════════════════════
# TAB 6 — LIBRARIAN: FINE MANAGEMENT
# ════════════════════════════════════════════════
elif active_tab == "💸 Fine Management":
    st.header("Student Fine Management")

    user_list = [u.to_dict() for u in db.collection("users").stream()]
    students  = [u for u in user_list if u.get("role") == "Student"]

    if students:
        st.dataframe(
            pd.DataFrame(students)[["email", "fines"]].rename(
                columns={"email": "Student Email", "fines": "Outstanding Fines ($)"}
            ),
            use_container_width=True,
        )
        target_user    = st.selectbox("Select Student Account", [u["email"] for u in students])
        fine_increment = st.number_input("Fine Amount to Issue ($)", min_value=0.0, step=0.50)

        if st.button("💸 Issue Fine"):
            user_ref  = db.collection("users").document(target_user)
            cur_fines = user_ref.get().to_dict().get("fines", 0.0)
            new_fines = cur_fines + fine_increment
            user_ref.update({"fines": new_fines})
            st.success(f"Fine issued. **{target_user}** now owes **${new_fines:.2f}**.")
            st.rerun()
    else:
        st.info("No student accounts found.")

# ════════════════════════════════════════════════
# TAB 7 — LIBRARIAN: OVERRIDE CONTROLS
# ════════════════════════════════════════════════
elif active_tab == "🚫 Override Controls":
    st.header("Room Reservation Override")

    res_list = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("reservations").stream()]
    if res_list:
        for res in res_list:
            col1, col2 = st.columns([4, 1])
            col1.write(
                f"🏢 **{res['room']}** · {res['slot']} · "
                f"Booked by **{res['reserved_by']}**"
            )
            if res.get("invited_members"):
                col1.caption(f"Group: {', '.join(res['invited_members'])}")
            if col2.button("🚫 Cancel", key=f"cancel_{res['id']}"):
                db.collection("reservations").document(res["id"]).delete()
                st.rerun()
    else:
        st.info("No active room reservations.")

# ════════════════════════════════════════════════
# TAB 8 — ADMIN: USAGE REPORTS
# ════════════════════════════════════════════════
elif active_tab == "📊 Usage Reports":
    st.header("Monthly Usage Analytics")

    total_books = len(list(db.collection("books").stream()))
    total_holds = len(list(db.collection("holds").stream()))
    total_rooms = len(list(db.collection("reservations").stream()))
    total_users = len(list(db.collection("users").stream()))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📚 Catalog Books",    total_books)
    c2.metric("📌 Active Holds",     total_holds)
    c3.metric("🏢 Room Bookings",    total_rooms)
    c4.metric("👤 Registered Users", total_users)

    st.divider()
    st.subheader("All Holds Log")
    holds_data = [{"hold_id": d.id, **d.to_dict()} for d in db.collection("holds").stream()]
    if holds_data:
        st.dataframe(pd.DataFrame(holds_data), use_container_width=True)
    else:
        st.info("No holds have been placed yet.")

# ════════════════════════════════════════════════
# TAB 9 — ADMIN: PERMISSIONS ENGINE
# ════════════════════════════════════════════════
elif active_tab == "⚙️ Permissions Engine":
    st.header("User Permission Management")

    all_users = [u.to_dict() for u in db.collection("users").stream()]
    if all_users:
        st.dataframe(
            pd.DataFrame(all_users)[["email", "role", "fines"]],
            use_container_width=True,
        )
        selected_target = st.selectbox("Target User", [u["email"] for u in all_users])
        new_role        = st.selectbox("Assign Role", ["Student", "Librarian", "System Administrator"])

        if st.button("💾 Save Role Assignment"):
            db.collection("users").document(selected_target).update({"role": new_role})
            st.success(f"✅ **{selected_target}** is now a **{new_role}**.")
            st.rerun()
    else:
        st.info("No users registered yet.")
