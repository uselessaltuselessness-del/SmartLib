# seed.py
import firebase_admin
from firebase_admin import credentials, firestore
import re

# Read your local secrets file manually to avoid Streamlit dependencies
secrets = {}
with open(".streamlit/secrets.toml", "r") as f:
    content = f.read()
    # Basic regex parsing of the toml file
    for line in content.split("\n"):
        if "=" in line and not line.startswith("["):
            key, val = line.split("=", 1)
            secrets[key.strip()] = val.strip().strip('"').replace("\\n", "\n")

# Initialize Firebase Connection
if not firebase_admin._apps:
    cred = credentials.Certificate(secrets)
    firebase_admin.initialize_app(cred)

db = firestore.client()

print("🚀 Connecting to SmartLib Database...")

# 1. Inject Test Users
users = {
    "student_good@univ.edu": {"email": "student_good@univ.edu", "role": "Student", "fines": 0.0},
    "student_blocked@univ.edu": {"email": "student_blocked@univ.edu", "role": "Student", "fines": 18.50},
    "librarian@univ.edu": {"email": "librarian@univ.edu", "role": "Librarian", "fines": 0.0},
    "admin@univ.edu": {"email": "admin@univ.edu", "role": "System Administrator", "fines": 0.0}
}

for doc_id, data in users.items():
    db.collection("users").document(doc_id).set(data)
    print(f"✅ Created User Profile: {doc_id} ({data['role']})")

# 2. Inject Test Books
books = {
    "9780143111597": {"isbn": "9780143111597", "title": "White Noise", "author": "Don DeLillo", "available": True},
    "0451524934": {"isbn": "0451524934", "title": "1984", "author": "George Orwell", "available": True},
    "9780451526342": {"isbn": "9780451526342", "title": "Animal Farm", "author": "George Orwell", "available": True}
}

for isbn, data in books.items():
    db.collection("books").document(isbn).set(data)
    print(f"📚 Added Book to Catalog: {data['title']}")

print("\n🎉 Database successfully seeded! You are ready to test.")
