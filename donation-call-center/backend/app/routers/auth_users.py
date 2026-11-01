from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..schemas import LoginIn, TokenOut, UserCreate, UserOut, UserUpdate
from ..security import create_token, current_user, hash_password, require_manager, verify_password

router = APIRouter(prefix="/api", tags=["auth & users"])


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username.strip()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "اسم المستخدم أو كلمة المرور غير صحيحة")
    if not user.active:
        raise HTTPException(403, "هذا الحساب موقوف")
    return {"token": create_token(user.id), "user": user}


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/users", response_model=list[UserOut])
def list_users(role: str | None = None, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    q = select(User).order_by(User.role.desc(), User.name)
    if role:
        q = q.where(User.role == role)
    return db.scalars(q).all()


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "اسم المستخدم مستخدم بالفعل")
    user = User(name=body.name, username=body.username, role=body.role,
                daily_target=body.daily_target, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                manager: User = Depends(require_manager)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "المستخدم غير موجود")
    if body.active is False and user.id == manager.id:
        raise HTTPException(422, "لا يمكنك إيقاف حسابك")
    for field in ("name", "active", "daily_target"):
        val = getattr(body, field)
        if val is not None:
            setattr(user, field, val)
    if body.password:
        user.password_hash = hash_password(body.password)
    db.commit()
    return user
