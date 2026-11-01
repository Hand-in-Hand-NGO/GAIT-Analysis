"""Business rules: applying a call outcome to a donor, and distribution."""
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import outcomes as oc
from .models import AssignmentLog, CallLog, Donor, User, utcnow
from .schemas import CallIn, DonorFilter

FINAL_STATUSES = {o.code for o in oc.OUTCOMES if o.final} | {"exhausted"}


def normalize_phone(phone: str) -> str:
    # Arabic-Indic digits -> ASCII
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
    phone = phone.translate(trans)
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0020"):
        digits = "0" + digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def donor_out(d: Donor) -> dict:
    data = {c: getattr(d, c) for c in (
        "id", "name", "phone", "alt_phone", "city", "source", "last_donation_amount", "notes",
        "assigned_agent_id", "status", "attempts", "next_action_at", "last_call_at", "pledge_amount",
        "pledge_due", "total_donated", "do_not_call", "created_at")}
    data["agent_name"] = d.agent.name if d.agent else None
    data["status_label"] = oc.status_label(d.status)
    return data


def call_out(c: CallLog) -> dict:
    data = {k: getattr(c, k) for k in (
        "id", "donor_id", "agent_id", "outcome", "notes", "amount", "payment_method",
        "follow_up_at", "duration_sec", "created_at")}
    data["donor_name"] = c.donor.name if c.donor else ""
    data["agent_name"] = c.agent.name if c.agent else ""
    data["outcome_label"] = oc.status_label(c.outcome)
    return data


def log_call(db: Session, donor: Donor, agent: User, data: CallIn) -> CallLog:
    outcome = oc.BY_CODE.get(data.outcome)
    if not outcome:
        raise HTTPException(422, f"نتيجة مكالمة غير معروفة: {data.outcome}")
    if donor.do_not_call and agent.role != "manager":
        raise HTTPException(409, "هذا المتبرع طلب عدم الاتصال")
    if outcome.code == "donated" and not data.amount:
        raise HTTPException(422, "اكتب مبلغ التبرع")
    if outcome.needs_follow_up and not data.follow_up_at:
        raise HTTPException(422, "حدد موعد المتابعة")

    now = utcnow()
    call = CallLog(
        donor_id=donor.id, agent_id=agent.id, outcome=outcome.code, notes=data.notes,
        amount=data.amount, payment_method=data.payment_method,
        follow_up_at=data.follow_up_at, duration_sec=data.duration_sec, created_at=now,
    )
    db.add(call)

    donor.attempts += 1
    donor.last_call_at = now
    donor.status = outcome.code
    donor.next_action_at = data.follow_up_at

    if outcome.reached:
        donor.unreachable_streak = 0
    elif outcome.category == "unreachable":
        donor.unreachable_streak += 1
        if donor.unreachable_streak >= oc.MAX_UNREACHABLE_ATTEMPTS:
            donor.status = "exhausted"
            donor.next_action_at = None
        elif not data.follow_up_at:
            donor.next_action_at = now + timedelta(hours=outcome.retry_hours)

    if outcome.code == "donated":
        donor.total_donated = (donor.total_donated or 0) + (data.amount or 0)
        donor.last_donation_amount = data.amount
        donor.next_action_at = None
    elif outcome.code == "pledged":
        donor.pledge_amount = data.amount
        donor.pledge_due = data.follow_up_at
    elif outcome.code == "do_not_call":
        donor.do_not_call = True
    if outcome.final:
        donor.next_action_at = None

    db.commit()
    db.refresh(call)
    return call


# ---------------- distribution ----------------

def _open_load(db: Session, agent_ids: list[int]) -> dict[int, int]:
    rows = db.execute(
        select(Donor.assigned_agent_id, func.count())
        .where(Donor.assigned_agent_id.in_(agent_ids), Donor.status.not_in(FINAL_STATUSES))
        .group_by(Donor.assigned_agent_id)
    ).all()
    load = {a: 0 for a in agent_ids}
    load.update({a: n for a, n in rows})
    return load


def _check_agents(db: Session, agent_ids: list[int]) -> list[User]:
    agents = db.scalars(select(User).where(User.id.in_(agent_ids))).all()
    if len(agents) != len(set(agent_ids)) or any(
        a.role != "agent" or not a.active for a in agents
    ):
        raise HTTPException(422, "اختر ايجنتس نشطين فقط")
    return list(agents)


def _assign(db: Session, donor: Donor, agent_id: int | None, by: User, reason: str):
    db.add(AssignmentLog(donor_id=donor.id, from_agent_id=donor.assigned_agent_id,
                         to_agent_id=agent_id, by_user_id=by.id, reason=reason))
    donor.assigned_agent_id = agent_id
    donor.assigned_at = utcnow() if agent_id else None


def auto_distribute(db: Session, by: User, agent_ids: list[int], mode: str,
                    per_agent: int | None, limit: int | None, flt: DonorFilter) -> dict[int, int]:
    _check_agents(db, agent_ids)
    q = select(Donor).where(Donor.assigned_agent_id.is_(None), Donor.do_not_call.is_(False))
    if flt.statuses:
        q = q.where(Donor.status.in_(flt.statuses))
    if flt.city:
        q = q.where(Donor.city == flt.city)
    if flt.source:
        q = q.where(Donor.source == flt.source)
    q = q.order_by(Donor.created_at, Donor.id)
    pool = list(db.scalars(q).all())

    if mode == "fixed":
        if not per_agent:
            raise HTTPException(422, "حدد عدد المتبرعين لكل ايجنت")
        cap = per_agent * len(agent_ids)
        limit = min(limit, cap) if limit else cap
    if limit:
        pool = pool[:limit]

    given = {a: 0 for a in agent_ids}
    if mode == "balanced":
        # fill whoever currently has the smallest open queue first
        load = _open_load(db, agent_ids)
        for donor in pool:
            target = min(agent_ids, key=lambda a: (load[a], a))
            _assign(db, donor, target, by, "auto")
            load[target] += 1
            given[target] += 1
    else:  # equal / fixed: plain round robin
        for i, donor in enumerate(pool):
            target = agent_ids[i % len(agent_ids)]
            _assign(db, donor, target, by, "auto")
            given[target] += 1
    db.commit()
    return given


def assign(db: Session, by: User, donor_ids: list[int], agent_id: int) -> int:
    _check_agents(db, [agent_id])
    donors = db.scalars(select(Donor).where(Donor.id.in_(donor_ids))).all()
    for d in donors:
        _assign(db, d, agent_id, by, "manual")
    db.commit()
    return len(donors)


def unassign(db: Session, by: User, donor_ids: list[int]) -> int:
    donors = db.scalars(select(Donor).where(Donor.id.in_(donor_ids))).all()
    for d in donors:
        _assign(db, d, None, by, "unassign")
    db.commit()
    return len(donors)


def transfer(db: Session, by: User, from_id: int, to_ids: list[int], only_open: bool) -> dict[int, int]:
    if from_id in to_ids:
        raise HTTPException(422, "لا يمكن النقل لنفس الايجنت")
    _check_agents(db, to_ids)
    q = select(Donor).where(Donor.assigned_agent_id == from_id)
    if only_open:
        q = q.where(Donor.status.not_in(FINAL_STATUSES))
    donors = db.scalars(q.order_by(Donor.id)).all()
    given = {a: 0 for a in to_ids}
    for i, d in enumerate(donors):
        target = to_ids[i % len(to_ids)]
        _assign(db, d, target, by, "transfer")
        given[target] += 1
    db.commit()
    return given
