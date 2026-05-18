import streamlit as st

# ----------------------------------------------------
# MUST BE THE VERY FIRST STREAMLIT CALL
# ----------------------------------------------------
st.set_page_config(page_title="SmartLib System", layout="wide")

import firebase_admin
from firebase_admin import credentials, firestore
import requests
import pandas as pd
import qrcode
import io

# ----------------------------------------------------
# 1. DATABASE & FIREBASE INITIALIZATION (SECURE)
# ----------------------------------------------------
db = None  # Default to None so we can guard against uninitialized use

if not firebase_admin._apps:
    try:
        secret_dict = dict(st.secrets["firebase"])
        secret_dict["private_key"] = secret_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(secret_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Failed to connect to Firebase. Error: {e}")
        st.stop()  # Halt the app cleanly if Firebase fails

try:
    db = firestore.client()
except Exception as e:
    st.error(f"Failed to create Firestore client. Error: {e}")
    st.stop()

# ----------------------------------------------------
# 2. SESSION STATE MANAGEMENT (MOCK CAS AUTH)
# ----------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None

def logout():
    st.session_state.user = None
    st.rerun()

# ----------------------------------------------------
# APP HEADER & GLOBAL NAVIGATION
# ----------------------------------------------------
st.title("📚 SmartLib University Library System")

st.sidebar.header("🔐 University CAS Gateway")
if st.session_state.user is None:
    st.sidebar.subheader("Login to Access Personal Features")
    login_email = st.sidebar.text_input("University Email (e.g., student_good@univ.edu)")
    login_role = st.sidebar.selectbox("Role", ["Student", "Librarian", "System Administrator"])

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

    if st.session_state.user['role'] == "Student":
        live_user_doc = db.collection("users").document(st.session_state.user['email']).get()
        live_user = live_user_doc.to_dict() if live_user_doc.exists else {}
        if live_user:
            st.sidebar.warning(f"Active Fines: ${live_user.get('fines', 0.0):.2f}")

    if st.sidebar.button("Logout"):
        logout()

# ----------------------------------------------------
# FUNCTIONALITY ARCHITECTURE (ROLES & USE CASES)
# ----------------------------------------------------
tabs = ["🔍 Public Catalog Search"]
if st.session_state.user:
    if st.session_state.user["role"] == "Student":
        tabs += ["📖 Book Borrowing & Holds", "💻 Digital Resources", "🔑 Room Reservations"]
    elif st.session_state.user["role"] == "Librarian":
        tabs += ["📋 Catalog Management", "💸 Fine Management", "🚫 Override Controls"]
    elif st.session_state.user["role"] == "System Administrator":
        tabs += ["📊 Usage Reports", "⚙️ Permissions Engine"]

active_tab = st.radio("Navigate System Engine:", tabs, horizontal=True)

# --- TAB 1: PUBLIC CATALOG SEARCH ---
if active_tab == "🔍 Public Catalog Search":
    st.header("Global Catalog Discovery")
    search_query = st.text_input("Search by Title, Author, or ISBN")

    books = [doc.to_dict() for doc in db.collection("books").stream()]

    if books:
        df = pd.DataFrame(books)
        if search_query:
            df = df[
                df['title'].str.contains(search_query, case=False, na=False) |
                df['author'].str.contains(search_query, case=False, na=False) |
                df['isbn'].str.contains(search_query, case=False, na=False)
            ]
        st.dataframe(df[["isbn", "title", "author", "available"]], use_container_width=True)
    else:
        st.info("The catalog is currently empty.")

# --- TAB 2: STUDENT BORROWING & HOLDS ---
elif active_tab == "📖 Book Borrowing & Holds":
    st.header("Physical Book Placements")

    live_user_doc = db.collection("users").document(st.session_state.user['email']).get()
    live_user = live_user_doc.to_dict() if live_user_doc.exists else {}

    if live_user.get('fines', 0.0) > 10.0:
        st.error("❌ Access Denied: Your account holds unpaid fines exceeding $10.00. Borrowing is locked.")
    else:
        st.success("✅ Account Status Clear: Eligible to hold books.")

        books_ref = db.collection("books").where("available", "==", True)
        available_books = {doc.to_dict()['title']: doc.id for doc in books_ref.stream()}

        if available_books:
            selected_book_title = st.selectbox("Select an available book:", list(available_books.keys()))
            if st.button("Place a Hold"):
                book_id = available_books[selected_book_title]
                hold_data = {
                    "student": st.session_state.user['email'],
                    "book_id": book_id,
                    "title": selected_book_title,
                    "status": "Active"
                }
                db.collection("holds").add(hold_data)
                db.collection("books").document(book_id).update({"available": False})
                st.balloons()
                st.success("Hold successfully created!")
                st.rerun()
        else:
            st.info("No books are currently physically available.")

    st.subheader("Your Active Self-Checkout QR Access Tokens")
    my_holds = db.collection("holds").where("student", "==", st.session_state.user['email']).stream()

    for hold in my_holds:
        h_data = hold.to_dict()
        with st.expander(f"Hold Voucher: {h_data['title']}"):
            qr_payload = f"HOLD_ID:{hold.id}|USER:{h_data['student']}"
            qr = qrcode.QRCode(version=1, box_size=10, border=2)
            qr.add_data(qr_payload)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            byte_im = buf.getvalue()

            col1, col2 = st.columns([1, 3])
            col1.image(byte_im, width=150, caption="Scan at Kiosk")
            col2.write(f"**Token ID:** `{hold.id}`")
            col2.download_button(
                label="💾 Download QR Pass (PNG)",
                data=byte_im,
                file_name=f"SmartLib_QR_{hold.id}.png",
                mime="image/png",
                key=f"dl_{hold.id}"
            )

# --- TAB 3: STUDENT DIGITAL ACCESS ---
elif active_tab == "💻 Digital Resources":
    st.header("Institutional Research Repo")

    mock_papers = [
        {"title": "Quantum Computation Elements", "size": "2.4 MB"},
        {"title": "Database Schemas Analysis", "size": "1.1 MB"}
    ]

    for paper in mock_papers:
        col1, col2 = st.columns([3, 1])
        col1.write(f"📄 **{paper['title']}** ({paper['size']})")
        col2.download_button(label="📥 Download PDF", data="Mock PDF Content", file_name=f"{paper['title']}.pdf")

# --- TAB 4: STUDENT ROOM RESERVATIONS ---
elif active_tab == "🔑 Room Reservations":
    st.header("Book Smart Study Rooms")

    with st.form("room_form"):
        room_selection = st.selectbox("Room", ["Room A", "Room B", "Room C"])
        time_slot = st.selectbox("Time", ["09:00 AM - 11:00 AM", "11:00 AM - 01:00 PM"])
        group_invites = st.text_area("Invite Group Members (Comma separated emails)")

        if st.form_submit_button("Confirm Reservation"):
            invite_list = [e.strip() for e in group_invites.split(",") if e.strip()] if group_invites else []
            db.collection("reservations").add({
                "room": room_selection, "slot": time_slot,
                "reserved_by": st.session_state.user['email'], "invited_members": invite_list
            })
            st.success(f"Successfully locked {room_selection} for {time_slot}!")

# --- TAB 5: LIBRARIAN CATALOG MANAGEMENT ---
elif active_tab == "📋 Catalog Management":
    st.header("Add Records via National API")
    isbn_input = st.text_input("Enter Book ISBN (e.g., 9780143111597)")

    if st.button("Fetch Metadata"):
        if isbn_input:
            response = requests.get(
                f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn_input}&jscmd=data&format=json"
            ).json()
            key = f"ISBN:{isbn_input}"
            if key in response:
                st.session_state.fetched_title = response[key].get("title", "Unknown Title")
                st.session_state.fetched_author = response[key].get("authors", [{"name": "Unknown"}])[0]["name"]
                st.session_state.fetched_isbn = isbn_input
                st.success("Metadata mapped successfully!")
            else:
                st.error("No metadata found.")

    title_field = st.text_input("Book Title", value=st.session_state.get('fetched_title', ''))
    author_field = st.text_input("Author Name", value=st.session_state.get('fetched_author', ''))
    isbn_field = st.text_input("ISBN", value=st.session_state.get('fetched_isbn', ''))

    if st.button("Commit to Catalog"):
        db.collection("books").document(isbn_field).set({
            "isbn": isbn_field, "title": title_field, "author": author_field, "available": True
        })
        st.success("Catalogued successfully.")

# --- TAB 6: LIBRARIAN FINE MANAGEMENT ---
elif active_tab == "💸 Fine Management":
    st.header("Account Fine Auditing")
    user_list = [u.to_dict() for u in db.collection("users").stream()]
    st.dataframe(pd.DataFrame(user_list)[["email", "role", "fines"]], use_container_width=True)

    target_user = st.selectbox("Select Account", [u['email'] for u in user_list if u['role'] == 'Student'])
    fine_assessment = st.number_input("Incremental Fine ($)", min_value=0.0, step=0.50)

    if st.button("Apply Fine"):
        user_ref = db.collection("users").document(target_user)
        new_fine = user_ref.get().to_dict().get('fines', 0.0) + fine_assessment
        user_ref.update({"fines": new_fine})
        st.success(f"Updated {target_user} Balance: ${new_fine:.2f}")
        st.rerun()

# --- TAB 7: LIBRARIAN OVERRIDE CONTROLS ---
elif active_tab == "🚫 Override Controls":
    st.header("Active Room Bookings Engine Logs")
    res_list = [{"id": doc.id, **doc.to_dict()} for doc in db.collection("reservations").stream()]

    if res_list:
        for res in res_list:
            col1, col2 = st.columns([3, 1])
            col1.write(f"🏢 **{res['room']}** by **{res['reserved_by']}** at `{res['slot']}`")
            if col2.button("Force Cancel", key=res['id']):
                db.collection("reservations").document(res['id']).delete()
                st.rerun()
    else:
        st.info("No room allocations registered.")

# --- TAB 8: ADMIN METRIC ENGINE ---
elif active_tab == "📊 Usage Reports":
    st.header("Monthly Analytical Metrics")
    total_books = len(list(db.collection("books").stream()))
    total_holds = len(list(db.collection("holds").stream()))
    total_rooms = len(list(db.collection("reservations").stream()))

    col1, col3, col4 = st.columns(3)
    col1.metric("Catalog Books", total_books)
    col3.metric("Active Holds", total_holds)
    col4.metric("Active Bookings", total_rooms)

# --- TAB 9: ADMIN PERMISSIONS ENGINE ---
elif active_tab == "⚙️ Permissions Engine":
    st.header("Authorization Management")
    all_users = [u.to_dict() for u in db.collection("users").stream()]

    selected_target = st.selectbox("Target User", [u['email'] for u in all_users])
    new_role = st.selectbox("Assign Role", ["Student", "Librarian", "System Administrator"])

    if st.button("Save Privilege Assignment"):
        db.collection("users").document(selected_target).update({"role": new_role})
        st.success("System permission updated.")
        st.rerun()
