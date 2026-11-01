import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import outcomes as oc
from ..db import get_db
from ..models import CallLog, Donor, User, utcnow
from ..schemas import CallIn, CallOut, DonorDetail, DonorIn, DonorOut, DonorUpdate, Page, to_naive_utc
from ..security import current_user, require_manager
from ..services import FINAL_STATUSES, call_out, donor_out, log_call, normalize_phone

router = APIRouter(prefix="/api", tags=["donors & calls"])


@router.get("/meta/outcomes")
def list_outcomes(_: User = Depends(current_user)):
    return {"outcomes": oc.as_dicts(), "extra_statuses": oc.EXTRA_STATUSES,
            "max_unreachable_attempts": oc.MAX_UNREACHABLE_ATTEMPTS}


@router.get("/meta/filters")
def filter_values(db: Session = Depends(get_db), _: User = Depends(current_user)):
    cities = db.scalars(select(Donor.city).where(Donor.city.is_not(None)).distinct().order_by(Donor.city)).all()
    sources = db.scalars(select(Donor.source).where(Donor.source.is_not(None)).distinct().order_by(Donor.source)).all()
    return {"cities": cities, "sources": sources}


def _get_donor(db: Session, donor_id: int, user: User) -> Donor:
    donor = db.get(Donor, donor_id)
    if not donor:
        raise HTTPException(404, "المتبرع غير موجود")
    if user.role != "manager" and donor.assigned_agent_id != user.id:
        raise HTTPException(403, "هذا المتبرع غير مخصص لك")
    return donor


@router.get("/donors", response_model=Page)
def list_donors(
    q: str | None = None,
    status: str | None = None,
    agent_id: int | None = None,
    unassigned: bool = False,
    city: str | None = None,
    source: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    query = select(Donor).options(selectinload(Donor.agent))
    if user.role != "manager":
        query = query.where(Donor.assigned_agent_id == user.id)
    elif unassigned:
        query = query.where(Donor.assigned_agent_id.is_(None))
    elif agent_id:
        query = query.where(Donor.assigned_agent_id == agent_id)
    if status:
        query = query.where(Donor.status.in_(status.split(",")))
    if city:
        query = query.where(Donor.city == city)
    if source:
        query = query.where(Donor.source == source)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Donor.name.ilike(like), Donor.phone.like(f"%{normalize_phone(q) or q}%")))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(query.order_by(Donor.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [donor_out(d) for d in items]}


@router.post("/donors", response_model=DonorOut, status_code=201)
def create_donor(body: DonorIn, db: Session = Depends(get_db), _: User = Depends(require_manager)):
    phone = normalize_phone(body.phone)
    if db.scalar(select(Donor).where(Donor.phone == phone)):
        raise HTTPException(409, "رقم الموبايل مسجل لمتبرع آخر")
    donor = Donor(**body.model_dump(exclude={"phone"}), phone=phone)
    db.add(donor)
    db.commit()
    return donor_out(donor)


CSV_ALIASES = {
    "name": {"name", "الاسم", "اسم", "اسم المتبرع"},
    "phone": {"phone", "mobile", "الموبايل", "الهاتف", "رقم", "رقم الموبايل", "التليفون"},
    "alt_phone": {"alt_phone", "phone2", "موبايل 2", "رقم آخر", "رقم اخر"},
    "city": {"city", "المدينة", "المحافظة"},
    "source": {"source", "campaign", "المصدر", "الحملة"},
    "last_donation_amount": {"last_donation_amount", "amount", "آخر تبرع", "اخر تبرع", "المبلغ"},
    "notes": {"notes", "ملاحظات"},
}


@router.post("/donors/import")
async def import_donors(file: UploadFile = File(...), db: Session = Depends(get_db),
                        _: User = Depends(require_manager)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1256")  # Excel Arabic CSVs
    reader = csv.DictReader(io.StringIO(text))
    colmap = {}
    for col in reader.fieldnames or []:
        key = col.strip().lower()
        for field, names in CSV_ALIASES.items():
            if key in {n.lower() for n in names}:
                colmap[col] = field
    if "name" not in colmap.values() or "phone" not in colmap.values():
        raise HTTPException(422, "الملف لازم يحتوي على عمود الاسم (name) وعمود الموبايل (phone)")

    existing = set(db.scalars(select(Donor.phone)).all())
    created, duplicates, invalid = 0, 0, []
    for line_no, row in enumerate(reader, start=2):
        rec = {colmap[c]: (v or "").strip() for c, v in row.items() if c in colmap}
        phone = normalize_phone(rec.get("phone", ""))
        if not rec.get("name") or len(phone) < 6:
            invalid.append(line_no)
            continue
        if phone in existing:
            duplicates += 1
            continue
        amount = rec.get("last_donation_amount")
        try:
            amount = float(amount) if amount else None
        except ValueError:
            amount = None
        db.add(Donor(name=rec["name"], phone=phone, alt_phone=rec.get("alt_phone") or None,
                     city=rec.get("city") or None, source=rec.get("source") or None,
                     last_donation_amount=amount, notes=rec.get("notes") or None))
        existing.add(phone)
        created += 1
    db.commit()
    return {"created": created, "duplicates": duplicates, "invalid_rows": invalid}


@router.get("/donors/{donor_id}", response_model=DonorDetail)
def get_donor(donor_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    donor = _get_donor(db, donor_id, user)
    data = donor_out(donor)
    data["calls"] = [call_out(c) for c in donor.calls]
    return data


@router.patch("/donors/{donor_id}", response_model=DonorOut)
def update_donor(donor_id: int, body: DonorUpdate, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    donor = _get_donor(db, donor_id, user)
    changes = body.model_dump(exclude_unset=True)
    if user.role != "manager":
        # agents may only correct contact details and notes
        changes = {k: v for k, v in changes.items() if k in {"alt_phone", "notes"}}
    if "status" in changes:
        if changes["status"] != "new":
            raise HTTPException(422, "يمكن فقط إعادة فتح المتبرع (new)")
        donor.unreachable_streak = 0
        donor.next_action_at = None
    for k, v in changes.items():
        setattr(donor, k, v)
    db.commit()
    return donor_out(donor)


@router.post("/donors/{donor_id}/calls", response_model=CallOut, status_code=201)
def add_call(donor_id: int, body: CallIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    donor = _get_donor(db, donor_id, user)
    call = log_call(db, donor, user, body)
    return call_out(call)


@router.get("/calls", response_model=list[CallOut])
def list_calls(
    agent_id: int | None = None,
    outcome: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(200, le=2000),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = select(CallLog).options(selectinload(CallLog.donor), selectinload(CallLog.agent))
    if user.role != "manager":
        agent_id = user.id
    if agent_id:
        q = q.where(CallLog.agent_id == agent_id)
    if outcome:
        q = q.where(CallLog.outcome.in_(outcome.split(",")))
    if date_from:
        q = q.where(CallLog.created_at >= to_naive_utc(date_from))
    if date_to:
        q = q.where(CallLog.created_at < to_naive_utc(date_to))
    return [call_out(c) for c in db.scalars(q.order_by(CallLog.created_at.desc()).limit(limit)).all()]


@router.get("/agent/queue", response_model=list[DonorOut])
def my_queue(agent_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """The agent's work list in priority order.

    1. overdue / due follow-ups (callbacks, pledges, retries)  2. new donors
    3. positive leads with no date  4. future follow-ups (shown last)
    """
    aid = agent_id if (user.role == "manager" and agent_id) else user.id
    now = utcnow()
    priority = case(
        (Donor.next_action_at <= now, 0),
        (Donor.status == "new", 1),
        (Donor.next_action_at.is_(None), 2),
        else_=3,
    )
    q = (select(Donor).options(selectinload(Donor.agent))
         .where(Donor.assigned_agent_id == aid, Donor.status.not_in(FINAL_STATUSES),
                Donor.do_not_call.is_(False))
         .order_by(priority, Donor.next_action_at, Donor.id))
    return [donor_out(d) for d in db.scalars(q).all()]


@router.get("/agent/followups", response_model=list[DonorOut])
def followups(days: int = 1, agent_id: int | None = None, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    """Follow-ups due up to N days from now (includes everything overdue)."""
    until = utcnow() + timedelta(days=days)
    q = (select(Donor).options(selectinload(Donor.agent))
         .where(Donor.next_action_at.is_not(None), Donor.next_action_at <= until,
                Donor.status.not_in(FINAL_STATUSES)))
    if user.role != "manager":
        q = q.where(Donor.assigned_agent_id == user.id)
    elif agent_id:
        q = q.where(Donor.assigned_agent_id == agent_id)
    return [donor_out(d) for d in db.scalars(q.order_by(Donor.next_action_at)).all()]
