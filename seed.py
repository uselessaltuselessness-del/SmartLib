"""
seed.py  —  Run once to populate Firestore with test data.

Usage (pick one):
    python seed.py                            # reads .streamlit/secrets.toml
    python seed.py --json serviceAccount.json # reads Firebase JSON directly
"""

import sys
import os
import json

# ── Argument parsing ─────────────────────────────────────────────────────────
USE_JSON_FILE = "--json" in sys.argv
JSON_PATH     = sys.argv[sys.argv.index("--json") + 1] if USE_JSON_FILE else None

# ── Dependency check ─────────────────────────────────────────────────────────
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("❌  Missing: pip install firebase-admin")
    sys.exit(1)

# ── Load credentials ─────────────────────────────────────────────────────────
cred_dict = None

if USE_JSON_FILE:
    # ── Option A: Firebase service-account JSON file ─────────────────────────
    if not os.path.exists(JSON_PATH):
        print(f"❌  File not found: {JSON_PATH}")
        sys.exit(1)
    try:
        with open(JSON_PATH, "r", encoding="utf-8") as f:
            cred_dict = json.load(f)
        print(f"✅  Loaded credentials from {JSON_PATH}")
    except json.JSONDecodeError as e:
        print(f"❌  Could not parse JSON file: {e}")
        sys.exit(1)

else:
    # ── Option B: .streamlit/secrets.toml ────────────────────────────────────
    SECRETS_PATH = ".streamlit/secrets.toml"

    if not os.path.exists(SECRETS_PATH):
        print(f"❌  Cannot find {SECRETS_PATH}")
        print("    Run this script from your project root, or use:")
        print("    python seed.py --json path/to/serviceAccount.json")
        sys.exit(1)

    # Try tomllib (built-in Python 3.11+) first, then fall back to toml library
    secrets = None
    parse_error = None

    # Attempt 1: tomllib (Python ≥ 3.11, no install needed)
    try:
        import tomllib                          # type: ignore
        with open(SECRETS_PATH, "rb") as f:
            secrets = tomllib.load(f)
        print("✅  Parsed secrets.toml with tomllib")
    except ImportError:
        pass                                    # Python < 3.11, try next
    except Exception as e:
        parse_error = e

    # Attempt 2: tomli (pip install tomli) — identical API to tomllib
    if secrets is None and parse_error is None:
        try:
            import tomli                        # type: ignore
            with open(SECRETS_PATH, "rb") as f:
                secrets = tomli.load(f)
            print("✅  Parsed secrets.toml with tomli")
        except ImportError:
            pass
        except Exception as e:
            parse_error = e

    # Attempt 3: toml (pip install toml) — older library, text mode
    if secrets is None and parse_error is None:
        try:
            import toml                         # type: ignore
            secrets = toml.load(SECRETS_PATH)
            print("✅  Parsed secrets.toml with toml")
        except ImportError:
            pass
        except Exception as e:
            parse_error = e

    if secrets is None:
        print()
        print("❌  Could not parse .streamlit/secrets.toml")
        if parse_error:
            print(f"    Error: {parse_error}")
        print()
        print("    Common causes:")
        print("    1. Your secrets.toml contains raw Firebase JSON (colons instead of =)")
        print("       Fix: use the TOML format shown below, or run with --json instead:")
        print()
        print("         python seed.py --json path/to/serviceAccount.json")
        print()
        print("    2. No TOML parser installed. Run:")
        print("         pip install tomli")
        print()
        print("    ── Correct secrets.toml format ──────────────────────────────")
        print("    [firebase]")
        print('    type                        = "service_account"')
        print('    project_id                  = "your-project-id"')
        print('    private_key_id              = "abc123"')
        print('    private_key                 = "-----BEGIN PRIVATE KEY-----\\nMIIE...\\n-----END PRIVATE KEY-----\\n"')
        print('    client_email               = "firebase-adminsdk@your-project.iam.gserviceaccount.com"')
        print('    client_id                  = "123456789"')
        print('    auth_uri                   = "https://accounts.google.com/o/oauth2/auth"')
        print('    token_uri                  = "https://oauth2.googleapis.com/token"')
        print('    auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"')
        print('    client_x509_cert_url       = "https://www.googleapis.com/robot/v1/metadata/x509/..."')
        print("    ─────────────────────────────────────────────────────────────")
        sys.exit(1)

    if "firebase" not in secrets:
        print("❌  secrets.toml is missing the [firebase] section.")
        print("    Make sure your file starts with [firebase] before the keys.")
        sys.exit(1)

    cred_dict = dict(secrets["firebase"])
    # TOML stores \n as two characters — convert to real newlines
    cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

# ── Firebase init ────────────────────────────────────────────────────────────
try:
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("🚀  Connected to Firestore.\n")
except Exception as e:
    print(f"❌  Firebase connection failed: {e}")
    print("    Check that your credentials are correct.")
    sys.exit(1)

# ── Seed: Users ──────────────────────────────────────────────────────────────
users = {
    "student_good@univ.edu": {
        "email": "student_good@univ.edu",
        "role":  "Student",
        "fines": 0.0,
    },
    "student_blocked@univ.edu": {
        "email": "student_blocked@univ.edu",
        "role":  "Student",
        "fines": 18.50,           # > $10 → borrowing locked
    },
    "librarian@univ.edu": {
        "email": "librarian@univ.edu",
        "role":  "Librarian",
        "fines": 0.0,
    },
    "admin@univ.edu": {
        "email": "admin@univ.edu",
        "role":  "System Administrator",
        "fines": 0.0,
    },
}

for doc_id, data in users.items():
    db.collection("users").document(doc_id).set(data)
    print(f"✅  User : {doc_id}  ({data['role']})")

print()

# ── Seed: Books ──────────────────────────────────────────────────────────────
books = {
    "9780143111597": {
        "isbn":      "9780143111597",
        "title":     "White Noise",
        "author":    "Don DeLillo",
        "available": True,
    },
    "0451524934": {
        "isbn":      "0451524934",
        "title":     "1984",
        "author":    "George Orwell",
        "available": True,
    },
    "9780451526342": {
        "isbn":      "9780451526342",
        "title":     "Animal Farm",
        "author":    "George Orwell",
        "available": True,
    },
}

for isbn, data in books.items():
    db.collection("books").document(isbn).set(data)
    print(f"📚  Book : {data['title']} — {data['author']}")

print()
print("🎉  Database seeded successfully!")
print("    Run:  streamlit run app.py")
