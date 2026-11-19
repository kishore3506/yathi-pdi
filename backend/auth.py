from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

try:
    from .database import get_db
except ImportError:
    from database import get_db


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
password_hasher = PasswordHasher()
ROLES = {"inspector", "approver", "administrator"}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=1024)
    role: str


class UserStatusRequest(BaseModel):
    is_active: bool


@router.get("/setup/status")
def setup_status():
    conn = get_db()
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS count FROM users WHERE role = 'administrator' AND is_active = 1"
        ).fetchone()["count"]
    finally:
        conn.close()
    return {"administrator_configured": bool(count)}


@router.post("/login")
def login(request: Request, credentials: LoginRequest):
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (credentials.email.strip().lower(),),
        ).fetchone()
    finally:
        conn.close()

    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    try:
        password_hasher.verify(user["password_hash"], credentials.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    request.session.clear()
    request.session["user_id"] = user["id"]
    request.session["issued_at"] = int(datetime.now(timezone.utc).timestamp())
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "role": user["role"],
    }


@router.get("/me")
def current_user(request: Request):
    if isinstance(request.state.user, dict) and request.state.user.get("local_access"):
        return request.state.user
    return {
        "id": request.state.user["id"],
        "email": request.state.user["email"],
        "display_name": request.state.user["display_name"],
        "role": request.state.user["role"],
    }


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"success": True}


@router.get("/users")
def list_users():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, email, display_name, role, is_active, created_at, updated_at "
            "FROM users ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


@router.post("/users", status_code=201)
def create_user(user: UserCreateRequest):
    role = user.role.strip().lower()
    email = user.email.strip().lower()
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Choose a valid employee role.")
    if "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid employee email address.")

    now = datetime.utcnow().isoformat()
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO users (email, display_name, password_hash, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                email,
                user.display_name.strip(),
                password_hasher.hash(user.password),
                role,
                now,
                now,
            ),
        )
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "email": email,
            "display_name": user.display_name.strip(),
            "role": role,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        }
    except Exception as exc:
        conn.rollback()
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status_code=409, detail="An employee with that email already exists.")
        raise
    finally:
        conn.close()


@router.patch("/users/{user_id}/status")
def update_user_status(user_id: int, status: UserStatusRequest, request: Request):
    if user_id == request.state.user["id"] and not status.is_active:
        raise HTTPException(status_code=400, detail="You cannot disable your own administrator account.")
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE users SET is_active = ?, updated_at = ? WHERE id = ?",
            (int(status.is_active), datetime.utcnow().isoformat(), user_id),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Employee account not found.")
        conn.commit()
    finally:
        conn.close()
    return {"id": user_id, "is_active": status.is_active}
