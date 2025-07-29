# auth.py ---------------------------------------------------------------
"""Very small, hard-coded credential check.
   Replace with a DB or proper auth in production!"""

USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "user":  {"password": "user123",  "role": "user"},
}

def authenticate(username: str, password: str) -> str | None:
    info = USERS.get(username.lower())
    if info and password == info["password"]:
        return info["role"]            # "admin" or "user"
    return None
