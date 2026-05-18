import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import requests
import pandas as pd
import urllib.parse

# ----------------------------------------------------
# 1. DATABASE & FIREBASE INITIALIZATION (SECURE)
# ----------------------------------------------------
if not firebase_admin._apps:
    try:
        # Fetching credentials securely from Streamlit Secrets
        secret_dict = dict(st.secrets["firebase"])
        # Ensure newlines in private key are parsed correctly
        secret_dict["private_key"] = secret_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(secret_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Failed to connect to Firebase. Check your secrets configuration. Error: {e}")

db = firestore.client()

# ----------------------------------------------------
# 2. SESSION STATE MANAGEMENT (MOCK CAS AUTH)
# ----------------------------------------------------
if "user" not in st.session_state:
    st.session_state.user = None  # None means anonymous visitor

def logout():
    st.session_state.user = None
    st.rerun()

# ----------------------------------------------------
# APP HEADER & GLOBAL NAVIGATION
# ----------------------------------------------------
st.set_page_config(page_title="SmartLib System", layout="wide")
st.title("📚 SmartLib University Library System")

# CAS Authentication Simulator Sidebar
st.sidebar.header("🔐 University CAS Gateway")
if st.session_state.user is None:
    st.sidebar.subheader("Login to Access Personal Features")
    login_email = st.sidebar.text_input("University Email")
    login_role = st.sidebar.selectbox("Role", ["Student", "Librarian", "System Administrator"])
    
    if st.sidebar.button("Login via CAS"):
        if login_email:
            # Fetch user or create a mock record if they don't exist yet
            user_ref = db.collection("users").document(login_email)
            user_doc = user_ref.get()
            
            if user_doc.exists:
                user_data = user_doc.to_dict()
            else:
                # Seed a default user if brand new
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
    
    # Live Fine Tracking for Students
    if st.session_state.user['role'] == "Student":
        # Pull latest fine structure live from DB
        live_user = db.collection("users").document(st.session_state.user['email']).get().to_dict()
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

# --- TAB 1: PUBLIC CATALOG SEARCH (No Auth Required) ---
if active_tab == "🔍 Public Catalog Search":
    st.header("Global Catalog Discovery")
    search_query = st.text_input("Search by Title, Author, or ISBN")
    
    books_ref = db.collection("books")
    books = [doc.to_dict() for doc in books_ref.stream()]
    
    if books:
        df = pd.DataFrame(books)
        if search_query:
            # Simple case-insensitive search filter
            df = df[df['title'].str.contains(search_query, case=False) | 
                    df['author'].str.contains(search_query, case=False) | 
                    df['isbn'].str.contains(search_query, case=False)]
        st.dataframe(df[["isbn", "title", "author", "available"]], use_container_width=True)
    else:
        st.info("The catalog is currently empty.")

# --- TAB 2: STUDENT BORROWING & HOLDS ---
elif active_tab == "📖 Book Borrowing & Holds":
    st.header("Physical Book Placements")
    
    # Strict Business Rule check
    live_user = db.collection("users").document(st.session_state.user['email']).get().to_dict()
    if live_user.get('fines', 0.0) > 10.0:
        st.error("❌ Access Denied: Your account holds unpaid fines exceeding $10.00. Borrowing is locked.")
    else:
        st.success("✅ Account Status Clear: Eligible to hold books.")
        
        books_ref = db.collection("books").where("available", "==", True)
        available_books = {doc.to_dict()['title']: doc.id for doc in books_ref.stream()}
        
        if available_books:
            selected_book_title = st.selectbox("Select an available book to place on hold:", list(available_books.keys()))
            if st.button("Place a Hold"):
                book_id = available_books[selected_book_title]
                
                # Transactional Logic
                hold_data = {
                    "student": st.session_state.user['email'],
                    "book_id": book_id,
                    "title": selected_book_title,
                    "status": "Active"
                }
                # Create Hold record
                db.collection("holds").add(hold_data)
                # Mark book unavailable
                db.collection("books").document(book_id).update({"available": False})
                
                st.balloons()
                st.success("Hold successfully created! See your active kiosk QR access keys below.")
                st.rerun()
        else:
            st.info("No books are currently physically available on shelves.")
            
    # Display Existing Holds & Generate QR Code Keys
    st.subheader("Your Active Self-Checkout QR Access Tokens")
    my_holds = db.collection("holds").where("student", "==", st.session_state.user['email']).stream()
    
    for hold in my_holds:
        h_data = hold.to_dict()
        with st.expander(f"Hold Voucher: {h_data['title']}"):
            # Zero-dependency QR generation via external secure API
            qr_payload = f"HOLD_ID:{hold.id}|USER:{h_data['student']}"
            encoded_url = urllib.parse.quote(qr_payload)
            qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=150x150&data={encoded_url}"
            
            col1, col2 = st.columns([1, 3])
            col1.image(qr_url, caption="Scan at Kiosk")
            col2.write(f"**Token ID:** `{hold.id}`")
            col2.write("Bring this generated pass to any SmartLib Self-Checkout Hub to collect your item.")

# --- TAB 3: STUDENT DIGITAL ACCESS ---
elif active_tab == "💻 Digital Resources":
    st.header("Institutional Research Repo")
    st.write("Instant electronic processing downloads:")
    
    mock_papers = [
        {"title": "Quantum Computation Elements in Linear Libraries", "size": "2.4 MB"},
        {"title": "An Empirical Evaluation of Cloud Firestore Database Schemas", "size": "1.1 MB"},
        {"title": "Automated Metadata Parsing Protocols via National APIs", "size": "4.7 MB"}
    ]
    
    for paper in mock_papers:
        col1, col2 = st.columns([3, 1])
        col1.write(f"📄 **{paper['title']}** ({paper['size']})")
        # Simulating secure file downloads safely
        col2.download_button(label="📥 Download PDF", data="Mock PDF Payload Content", file_name=f"{paper['title']}.pdf")

# --- TAB 4: STUDENT ROOM RESERVATIONS ---
elif active_tab == "🔑 Room Reservations":
    st.header("Book Smart Study Rooms")
    
    with st.form("room_form"):
        room_selection = st.selectbox("Choose Room Asset", ["Room A - Alpha Labs", "Room B - Quiet Zones", "Room C - Colloquium Space"])
        time_slot = st.selectbox("Time Slot Window", ["09:00 AM - 11:00 AM", "11:00 AM - 01:00 PM", "01:00 PM - 03:00 PM", "03:00 PM - 05:00 PM"])
        group_invites = st.text_area("Invite Group Members (Optional)", help="Enter valid university emails separated by commas.")
        
        submit_booking = st.form_submit_button("Confirm Reservation Instance")
        if submit_booking:
            invite_list = [email.strip() for email in group_invites.split(",") if email.strip()] if group_invites else []
            
            reservation_record = {
                "room": room_selection,
                "slot": time_slot,
                "reserved_by": st.session_state.user['email'],
                "invited_members": invite_list
            }
            db.collection("reservations").add(reservation_record)
            st.success(f"Successfully locked {room_selection} for {time_slot}!")

# --- TAB 5: LIBRARIAN CATALOG MANAGEMENT ---
elif active_tab == "📋 Catalog Management":
    st.header("Librarian Institutional Inventory Controls")
    
    st.subheader("Add Records via National Bibliographic Database API Integration")
    isbn_input = st.text_input("Enter Book ISBN (e.g., 9780143111597 or 0451524934)")
    
    # Internal variables to persist data across actions
    if st.button("Fetch Metadata"):
        if isbn_input:
            with st.spinner("Querying open national API repositories..."):
                # Hit OpenLibrary open API endpoint
                api_url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn_input}&jscmd=data&format=json"
                response = requests.get(api_url).json()
                key = f"ISBN:{isbn_input}"
                
                if key in response:
                    st.session_state.fetched_title = response[key].get("title", "Unknown Title")
                    st.session_state.fetched_author = response[key].get("authors", [{"name": "Unknown Author"}])[0]["name"]
                    st.session_state.fetched_isbn = isbn_input
                    st.success("Metadata mapped successfully!")
                else:
                    st.error("No global registration metadata logs found for this ISBN. Enter fields manually.")
        else:
            st.error("Provide an ISBN lookup vector.")
            
    # Form to commit to DB
    title_field = st.text_input("Validated Book Title", value=st.session_state.get('fetched_title', ''))
    author_field = st.text_input("Validated Author Name", value=st.session_state.get('fetched_author', ''))
    isbn_field = st.text_input("Target ISBN Registry", value=st.session_state.get('fetched_isbn', ''))
    
    if st.button("Commit New Asset to Active Catalog"):
        if title_field and author_field and isbn_field:
            db.collection("books").document(isbn_field).set({
                "isbn": isbn_field,
                "title": title_field,
                "author": author_field,
                "available": True
            })
            st.success(f"Catalogued: '{title_field}' has been safely inventoried.")
            # Reset fetched variables
            if 'fetched_title' in st.session_state: del st.session_state.fetched_title
            if 'fetched_author' in st.session_state: del st.session_state.fetched_author
            if 'fetched_isbn' in st.session_state: del st.session_state.fetched_isbn
        else:
            st.error("Ensure database structural requirements are met.")

# --- TAB 6: LIBRARIAN FINE MANAGEMENT ---
elif active_tab == "💸 Fine Management":
    st.header("Account Fine Auditing & Penalties")
    
    users_ref = db.collection("users").stream()
    user_list = [u.to_dict() for u in users_ref]
    
    st.subheader("Current User Ledgers")
    st.dataframe(pd.DataFrame(user_list)[["email", "role", "fines"]], use_container_width=True)
    
    st.subheader("Issue Overdue Penalty Assessments")
    target_user = st.selectbox("Select Account", [u['email'] for u in user_list if u['role'] == 'Student'])
    fine_assessment = st.number_input("Incremental Fine Amount ($)", min_value=0.0, step=0.50)
    
    if st.button("Apply Fine to Profile"):
        user_ref = db.collection("users").document(target_user)
        current_fine = user_ref.get().to_dict().get('fines', 0.0)
        new_fine = current_fine + fine_assessment
        user_ref.update({"fines": new_fine})
        st.warning(f"Updated account ledger for {target_user}. New Balance: ${new_fine:.2f}")
        st.rerun()

# --- TAB 7: LIBRARIAN OVERRIDE CONTROLS ---
elif active_tab == "🚫 Override Controls":
    st.header("Librarian Administrative Facility Interventions")
    st.subheader("Active Room Bookings Engine Logs")
    
    reservations_ref = db.collection("reservations").stream()
    res_list = [{"id": doc.id, **doc.to_dict()} for doc in reservations_ref]
    
    if res_list:
        for res in res_list:
            col1, col2 = st.columns([3, 1])
            col1.write(f"🏢 **{res['room']}** assigned to **{res['reserved_by']}** during slot `{res['slot']}`")
            if col2.button("Force Cancel Booking", key=res['id']):
                db.collection("reservations").document(res['id']).delete()
                st.error(f"Reservation structural reference `{res['id']}` evicted dynamically.")
                st.rerun()
    else:
        st.info("No room allocations registered in system registers.")

# --- TAB 8: ADMIN METRIC ENGINE ---
elif active_tab == "📊 Usage Reports":
    st.header("Monthly SmartLib Analytical Performance Metrics")
    
    # Calculate dataset stats from backend collections
    total_books = len([b for b in db.collection("books").stream()])
    total_holds = len([h for h in db.collection("holds").stream()])
    total_rooms = len([r for r in db.collection("reservations").stream()])
    
    col1, col3, col4 = st.columns(3)
    col1.metric("Catalog Books Tracked", total_books)
    col3.metric("Active Holds Triggered", total_holds)
    col4.metric("Active Facility Bookings", total_rooms)
    
    st.subheader("Resource Usage Analysis Summary")
    chart_data = pd.DataFrame({
        'Resource Metrics': ['Physical Book Inventory', 'Circulation Holds', 'Room Allocations'],
        'Total Operations Count': [total_books, total_holds, total_rooms]
    })
    st.bar_chart(chart_data.set_index('Resource Metrics'))

# --- TAB 9: ADMIN PERMISSIONS ENGINE ---
elif active_tab == "⚙️ Permissions Engine":
    st.header("Global Authorization Matrix Management")
    
    all_users = [u.to_dict() for u in db.collection("users").stream()]
    st.dataframe(pd.DataFrame(all_users)[["email", "role"]], use_container_width=True)
    
    st.subheader("Modify Security Privilege Group Access")
    selected_target = st.selectbox("Target Core User Email Anchor", [u['email'] for u in all_users])
    new_role_assignment = st.selectbox("Assign Authorization Access Layer", ["Student", "Librarian", "System Administrator"])
    
    if st.button("Save Privilege Assignment Changes"):
        db.collection("users").document(selected_target).update({"role": new_role_assignment})
        st.success(f"System permission updated. {selected_target} mapped to role tier: {new_role_assignment}")
        st.rerun()
