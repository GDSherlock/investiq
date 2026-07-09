"""Auth router — login, register, me endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, AuditLog
from ..auth import verify_password, get_password_hash, create_access_token, require_auth

router = APIRouter()


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str = "analyst"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    """Authenticate user and return JWT token."""
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.commit()

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role})

    db.add(AuditLog(
        action="user_login",
        entity_type="User",
        entity_id=str(user.id),
        user_id=str(user.id),
        payload={"email": user.email},
    ))
    db.commit()

    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "persona_default": user.persona_default,
        },
    )


@router.post("/auth/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user."""
    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        id=str(uuid.uuid4()),
        name=req.name,
        email=req.email,
        role=req.role,
        password_hash=get_password_hash(req.password),
    )
    db.add(user)

    db.add(AuditLog(
        action="user_register",
        entity_type="User",
        entity_id=user.id,
        user_id=user.id,
        payload={"email": req.email, "name": req.name},
    ))
    db.commit()

    token = create_access_token(data={"sub": str(user.id), "email": user.email, "role": user.role})

    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "persona_default": user.persona_default,
        },
    )


@router.get("/auth/me")
async def get_me(user: User = Depends(require_auth)):
    """Get current authenticated user."""
    return {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "persona_default": user.persona_default,
        "team_id": user.team_id,
    }
