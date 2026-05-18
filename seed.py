"""
seed.py  —  Run once to populate Firestore with test data.

Usage:
    python seed.py

Reads credentials from .streamlit/secrets.toml using the `toml` library,
exactly mirroring how Streamlit loads st.secrets in app.py.
"""

import sys

# ── Dependency check ────────────────────────────────────────────────────────
try:
    import toml
except ImportError:
    print("❌ Missing dependency: run  pip install toml  then try again.")
    sys.exit(1)

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("❌ Missing dependency: run  pip install firebase-admin  then try again.")
    sys.exit(1)

# ── Load secrets the same way Streamlit does ────────────────────────────────
SECRETS_PATH = ".streamlit/secrets.toml"

try:
    secrets = toml.load(SECRETS_PATH)
except FileNotFoundError:
    print(f"❌ Cannot find {SECRETS_PATH}. Make sure you run this script from "
          "your project root (the folder that contains the .streamlit folder).")
    sys.exit(1)
except toml.TomlDecodeError as e:
    print(f"❌ secrets.toml is malformed: {e}")
    sys.exit(1)

if "firebase" not in secrets:
    print("❌ No [firebase] section found in secrets.toml.")
    sys.exit(1)

# toml loads \n literally inside strings — convert to real newlines,
# same as the replace() call in app.py
cred_dict = dict(secrets["firebase"])
cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

# ── Firebase init ────────────────────────────────────────────────────────────
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db = firestore.client()

print("🚀 Connected to SmartLib Firestore database.")
print()

# ── Seed: Users ──────────────────────────────────────────────────────────────
users = {
    "student_good@univ.edu": {
        "email" : "student_good@univ.edu",
        "role"  : "Student",
        "fines" : 0.0,
    },
    "student_blocked@univ.edu": {
        "email" : "student_blocked@univ.edu",
        "role"  : "Student",
        "fines" : 18.50,          # exceeds $10 → borrowing blocked
    },
    "librarian@univ.edu": {
        "email" : "librarian@univ.edu",
        "role"  : "Librarian",
        "fines" : 0.0,
    },
    "admin@univ.edu": {
        "email" : "admin@univ.edu",
        "role"  : "System Administrator",
        "fines" : 0.0,
    },
}

for doc_id, data in users.items():
    db.collection("users").document(doc_id).set(data)
    print(f"✅ User: {doc_id}  ({data['role']})")

print()

# ── Seed: Books ──────────────────────────────────────────────────────────────
books = {
    "9780143111597": {
        "isbn"      : "9780143111597",
        "title"     : "White Noise",
        "author"    : "Don DeLillo",
        "available" : True,
    },
    "0451524934": {
        "isbn"      : "0451524934",
        "title"     : "1984",
        "author"    : "George Orwell",
        "available" : True,
    },
    "9780451526342": {
        "isbn"      : "9780451526342",
        "title"     : "Animal Farm",
        "author"    : "George Orwell",
        "available" : True,
    },
}

for isbn, data in books.items():
    db.collection("books").document(isbn).set(data)
    print(f"📚 Book: {data['title']} by {data['author']}")

print()
print("🎉 Database seeded successfully!")
print("    You can now run:  streamlit run app.py")
