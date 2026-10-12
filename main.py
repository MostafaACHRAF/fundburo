from datetime import datetime

from fastapi import Depends, FastAPI
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal
from models import AppUser, Item


app = FastAPI(title="LostAndFound API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ClaimCreate(BaseModel):
    username: str
    email: EmailStr
    description: str
    color: str | None = None
    size: str | None = None
    usage: str | None = None
    address_text: str | None = None
    lat: float | None = None
    lng: float | None = None
    event_time: datetime | None = None
    feel: str | None = None
    smell: str | None = None
    model: str | None = None
    image_url: str | None = None


class ClaimCreateResponse(BaseModel):
    user_id: int
    item_id: int
    status: str


@app.post("/claims", response_model=ClaimCreateResponse)
def submit_claim(payload: ClaimCreate, db: Session = Depends(get_db)):
    user_stmt = select(AppUser).where(
        AppUser.email == payload.email,
        AppUser.role == "claimer",
    )
    user = db.scalar(user_stmt)

    if user is None:
        user = AppUser(username=payload.username, email=payload.email, role="claimer")
        db.add(user)
        db.flush()

    item = Item(
        user_id=user.id,
        item_type="lost",
        description=payload.description,
        color=payload.color,
        size=payload.size,
        usage=payload.usage,
        address_text=payload.address_text,
        lat=payload.lat,
        lng=payload.lng,
        event_time=payload.event_time,
        feel=payload.feel,
        smell=payload.smell,
        model=payload.model,
        image_url=payload.image_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    return ClaimCreateResponse(user_id=user.id, item_id=item.id, status=item.status)
