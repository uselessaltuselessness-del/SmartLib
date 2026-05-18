import streamlit as st

# ── Must be the very first Streamlit call ────────────────────────────────────
st.set_page_config(page_title="SmartLib System", layout="wide")

import firebase_admin
from firebase_admin import credentials, firestore
import requests
import pandas as pd
import qrcode
from PIL import Image
import io

# ────────────────────────────────────────────────────────────────────────────
# 1. FIREBASE  —  initialised from st.secrets (mirrors .streamlit/secrets.toml)
# ────────────────────────────────────────────────────────────────────────────
db = None

if not firebase_admin._apps:
    try:
        cred_dict = dict(st.secrets["firebase"])
        # TOML stores the private key with literal \n — convert to real newlines
        cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"❌ Firebase initialisation failed: {e}")
        st.stop()

try:
    db = firestore.client()
except Exception as e:
    st.error(f"❌ Firestore client error: {e}")
    st.stop()

# ────────────────────────────────────────────────────────────────────────────
# 2. QR CODE HELPER
# ────────────────────────────────────────────────────────────────────────────
def generate_qr_bytes(payload: str) -> bytes:
    """
    Returns a PNG QR code as raw bytes.
    Unwraps qrcode's PilImage wrapper to get the real PIL Image before
    saving — this is reliable across all qrcode + Pillow version combos.
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

# ────────────────────────────────────────────────────────────────────────────
# 3. SESSION STATE DEFAULTS
# ────────────────────────────────────────────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None
if "latest_hold" not in st.session_state:
    st.session_state.latest_hold = None   # {"hold_id", "title", "student"}

def logout():
    st.session_state.user = None
    st.session_state.latest_hold = None
    st.rerun()

# ────────────────────────────────────────────────────────────────────────────
# 4. PAGE HEADER + SIDEBAR (CAS GATEWAY)
# ────────────────────────────────────────────────────────────────────────────
st.title("📚 SmartLib University Library System")
st.sidebar.header("🔐 University CAS Gateway")

if st.session_state.user is None:
    st.sidebar.subheader("Login to Access Personal Features")
    login_email = st.sidebar.text_input("University Email")
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
            st.rerun()
        else:
            st.sidebar.error("Please enter your university email.")
else:
    st.sidebar.write(f"**Logged in as:** {st.session_state.user['email']}")
    st.sidebar.write(f"**Role:** {st.session_state.user['role']}")

    if st.session_state.user["role"] == "Student":
        doc = db.collection("users").document(st.session_state.user["email"]).get()
        live = doc.to_dict() if doc.exists else {}
        fines = live.get("fines", 0.0)
        if fines > 0:
            st.sidebar.warning(f"Outstanding fines: **${fines:.2f}**")
        else:
            st.sidebar.success("No outstanding fines ✅")

    if st.sidebar.button("Logout"):
        logout()

# ────────────────────────────────────────────────────────────────────────────
# 5. TAB NAVIGATION
# ────────────────────────────────────────────────────────────────────────────
tabs = ["🔍 Public Catalog Search"]
if st.session_state.user:
    role = st.session_state.user["role"]
    if role == "Student":
        tabs += ["📖 Book Borrowing & Holds", "💻 Digital Resources", "🔑 Room Reservations"]
    elif role == "Librarian":
        tabs += ["📋 Catalog Management", "💸 Fine Management", "🚫 Override Controls"]
    elif role == "System Administrator":
        tabs += ["📊 Usage Reports", "⚙️ Permissions Engine"]

active_tab = st.radio("Navigate:", tabs, horizontal=True)

# ════════════════════════════════════════════════════════════════════════════
# TAB 1 — PUBLIC CATALOG SEARCH  (no login required)
# ════════════════════════════════════════════════════════════════════════════
if active_tab == "🔍 Public Catalog Search":
    st.header("Global Catalog Discovery")
    query = st.text_input("Search by Title, Author, or ISBN")

    books = [d.to_dict() for d in db.collection("books").stream()]
    if books:
        df = pd.DataFrame(books)
        if query:
            mask = (
                df["title"].str.contains(query, case=False, na=False) |
                df["author"].str.contains(query, case=False, na=False) |
                df["isbn"].str.contains(query, case=False, na=False)
            )
            df = df[mask]
        st.dataframe(df[["isbn", "title", "author", "available"]], use_container_width=True)
    else:
        st.info("The catalog is empty. Ask a librarian to add books.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 2 — STUDENT: BORROWING & HOLDS
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "📖 Book Borrowing & Holds":
    st.header("Physical Book Placements")

    # Always fetch a live fine balance (never rely on session state cache)
    live_doc  = db.collection("users").document(st.session_state.user["email"]).get()
    live_user = live_doc.to_dict() if live_doc.exists else {}
    fines     = live_user.get("fines", 0.0)

    # Business rule: block if fines > $10
    if fines > 10.0:
        st.error(
            f"❌ Borrowing locked — outstanding fine: **${fines:.2f}**. "
            "Please visit the library desk to clear your balance."
        )
    else:
        st.success("✅ Account clear — you may place a hold.")

        avail_docs  = db.collection("books").where("available", "==", True).stream()
        avail_books = {d.to_dict()["title"]: d.id for d in avail_docs}

        if avail_books:
            selected = st.selectbox("Select a book:", list(avail_books.keys()))

            if st.button("📌 Place a Hold"):
                book_id  = avail_books[selected]
                # .add() → (WriteResult, DocumentReference)
                hold_ref = db.collection("holds").add({
                    "student" : st.session_state.user["email"],
                    "book_id" : book_id,
                    "title"   : selected,
                    "status"  : "Active",
                })
                hold_id = hold_ref[1].id
                db.collection("books").document(book_id).update({"available": False})

                # Store in session state BEFORE rerun so QR renders immediately
                st.session_state.latest_hold = {
                    "hold_id" : hold_id,
                    "title"   : selected,
                    "student" : st.session_state.user["email"],
                }
                st.rerun()
        else:
            st.info("No books currently available for physical loan.")

    # ── QR banner shown immediately after a successful hold ─────────────────
    if st.session_state.latest_hold:
        lh = st.session_state.latest_hold
        st.divider()
        st.subheader("🎉 Hold Confirmed — Self-Checkout QR Pass")

        payload  = f"HOLD_ID:{lh['hold_id']}|USER:{lh['student']}"
        qr_bytes = generate_qr_bytes(payload)

        c_img, c_info = st.columns([1, 2])
        c_img.image(qr_bytes, width=200, caption="Scan at the self-checkout kiosk")
        c_info.markdown(f"""
**Book:** {lh['title']}  
**Token ID:** `{lh['hold_id']}`  
**Student:** {lh['student']}  

Scan this QR code at any self-checkout kiosk to collect your book.
        """)
        c_info.download_button(
            label     = "💾 Download QR Pass (PNG)",
            data      = qr_bytes,
            file_name = f"SmartLib_QR_{lh['hold_id']}.png",
            mime      = "image/png",
            key       = "latest_qr_dl",
        )
        if st.button("✅ Done — Dismiss"):
            st.session_state.latest_hold = None
            st.rerun()

    # ── All active holds for this student ───────────────────────────────────
    st.divider()
    st.subheader("Your Active Hold Vouchers")
    my_holds = list(
        db.collection("holds")
          .where("student", "==", st.session_state.user["email"])
          .stream()
    )

    if not my_holds:
        st.info("You have no active holds.")
    else:
        for hold in my_holds:
            h = hold.to_dict()
            with st.expander(f"📘 {h['title']}  —  `{hold.id}`"):
                payload  = f"HOLD_ID:{hold.id}|USER:{h['student']}"
                qr_bytes = generate_qr_bytes(payload)
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

# ════════════════════════════════════════════════════════════════════════════
# TAB 3 — STUDENT: DIGITAL RESOURCES
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "💻 Digital Resources":
    st.header("Institutional Research Repository")

    papers = [
        {"title": "Quantum Computation Elements",   "size": "2.4 MB"},
        {"title": "Database Schemas Analysis",       "size": "1.1 MB"},
        {"title": "Modern Cryptography Principles",  "size": "3.7 MB"},
    ]
    for p in papers:
        c1, c2 = st.columns([3, 1])
        c1.write(f"📄 **{p['title']}** ({p['size']})")
        c2.download_button(
            label     = "📥 Download PDF",
            data      = f"Mock PDF content: {p['title']}",
            file_name = f"{p['title']}.pdf",
            key       = f"pdf_{p['title']}",
        )

# ════════════════════════════════════════════════════════════════════════════
# TAB 4 — STUDENT: ROOM RESERVATIONS
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "🔑 Room Reservations":
    st.header("Smart Study Room Booking")

    with st.form("room_form"):
        room   = st.selectbox("Room", ["Room A — 4 seats", "Room B — 8 seats", "Room C — 12 seats"])
        slot   = st.selectbox("Time Slot", [
            "09:00 AM – 11:00 AM",
            "11:00 AM – 01:00 PM",
            "01:00 PM – 03:00 PM",
            "03:00 PM – 05:00 PM",
        ])
        invites = st.text_area("Invite Group Members (optional — comma-separated emails)")

        if st.form_submit_button("Confirm Reservation"):
            invite_list = [e.strip() for e in invites.split(",") if e.strip()] if invites else []
            db.collection("reservations").add({
                "room"            : room,
                "slot"            : slot,
                "reserved_by"     : st.session_state.user["email"],
                "invited_members" : invite_list,
            })
            st.success(f"✅ **{room}** reserved for **{slot}**.")
            if invite_list:
                st.info(f"Group members invited: {', '.join(invite_list)}")

# ════════════════════════════════════════════════════════════════════════════
# TAB 5 — LIBRARIAN: CATALOG MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "📋 Catalog Management":
    st.header("Catalog Management — National Bibliographic API")

    isbn_input = st.text_input("Enter ISBN to fetch metadata (e.g. 9780143111597)")
    if st.button("🔎 Fetch from National Database"):
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
                    st.success("✅ Metadata fetched.")
                else:
                    st.error("No record found for that ISBN.")
            except Exception as e:
                st.error(f"API error: {e}")

    title_f  = st.text_input("Book Title",  value=st.session_state.get("fetched_title",  ""))
    author_f = st.text_input("Author Name", value=st.session_state.get("fetched_author", ""))
    isbn_f   = st.text_input("ISBN",        value=st.session_state.get("fetched_isbn",   ""))

    c_add, c_del = st.columns(2)
    with c_add:
        if st.button("➕ Add to Catalog"):
            if isbn_f and title_f:
                db.collection("books").document(isbn_f).set({
                    "isbn": isbn_f, "title": title_f,
                    "author": author_f, "available": True,
                })
                st.success(f"📚 *{title_f}* added.")
            else:
                st.error("ISBN and Title are required.")
    with c_del:
        rm_isbn = st.text_input("ISBN to remove")
        if st.button("🗑️ Remove from Catalog"):
            if rm_isbn:
                db.collection("books").document(rm_isbn).delete()
                st.success(f"Removed `{rm_isbn}` from catalog.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 6 — LIBRARIAN: FINE MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "💸 Fine Management":
    st.header("Student Fine Management")

    all_users = [u.to_dict() for u in db.collection("users").stream()]
    students  = [u for u in all_users if u.get("role") == "Student"]

    if students:
        st.dataframe(
            pd.DataFrame(students)[["email", "fines"]].rename(
                columns={"email": "Student Email", "fines": "Outstanding Fines ($)"}
            ),
            use_container_width=True,
        )
        target = st.selectbox("Select student", [u["email"] for u in students])
        amount = st.number_input("Fine amount ($)", min_value=0.0, step=0.50)

        if st.button("💸 Issue Fine"):
            ref      = db.collection("users").document(target)
            cur      = ref.get().to_dict().get("fines", 0.0)
            new_fine = cur + amount
            ref.update({"fines": new_fine})
            st.success(f"Fine issued. **{target}** now owes **${new_fine:.2f}**.")
            st.rerun()
    else:
        st.info("No student accounts found.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 7 — LIBRARIAN: OVERRIDE CONTROLS
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "🚫 Override Controls":
    st.header("Room Reservation Override")

    res_list = [{"id": d.id, **d.to_dict()} for d in db.collection("reservations").stream()]
    if res_list:
        for res in res_list:
            c1, c2 = st.columns([4, 1])
            c1.write(f"🏢 **{res['room']}** · {res['slot']} · booked by **{res['reserved_by']}**")
            if res.get("invited_members"):
                c1.caption(f"Group: {', '.join(res['invited_members'])}")
            if c2.button("🚫 Cancel", key=f"cancel_{res['id']}"):
                db.collection("reservations").document(res["id"]).delete()
                st.rerun()
    else:
        st.info("No active reservations.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 8 — ADMIN: USAGE REPORTS
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "📊 Usage Reports":
    st.header("Monthly Usage Analytics")

    total_books = len(list(db.collection("books").stream()))
    total_holds = len(list(db.collection("holds").stream()))
    total_rooms = len(list(db.collection("reservations").stream()))
    total_users = len(list(db.collection("users").stream()))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📚 Books in Catalog", total_books)
    c2.metric("📌 Active Holds",     total_holds)
    c3.metric("🏢 Room Bookings",    total_rooms)
    c4.metric("👤 Registered Users", total_users)

    st.divider()
    st.subheader("All Holds Log")
    holds = [{"hold_id": d.id, **d.to_dict()} for d in db.collection("holds").stream()]
    if holds:
        st.dataframe(pd.DataFrame(holds), use_container_width=True)
    else:
        st.info("No holds placed yet.")

# ════════════════════════════════════════════════════════════════════════════
# TAB 9 — ADMIN: PERMISSIONS ENGINE
# ════════════════════════════════════════════════════════════════════════════
elif active_tab == "⚙️ Permissions Engine":
    st.header("User Permission Management")

    all_users = [u.to_dict() for u in db.collection("users").stream()]
    if all_users:
        st.dataframe(
            pd.DataFrame(all_users)[["email", "role", "fines"]],
            use_container_width=True,
        )
        target  = st.selectbox("Target user", [u["email"] for u in all_users])
        new_role = st.selectbox("Assign role", ["Student", "Librarian", "System Administrator"])

        if st.button("💾 Save Assignment"):
            db.collection("users").document(target).update({"role": new_role})
            st.success(f"✅ **{target}** is now a **{new_role}**.")
            st.rerun()
    else:
        st.info("No users found.")
