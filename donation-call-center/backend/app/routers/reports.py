import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import outcomes as oc
from ..db import get_db
from ..models import CallLog, Donor, User, utcnow
from ..schemas import to_naive_utc
from ..security import current_user, require_manager
from ..services import FINAL_STATUSES, donor_out

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _range(date_from: datetime | None, date_to: datetime | None) -> tuple[datetime, datetime]:
    """Default range: today. date_to is exclusive."""
    date_from, date_to = to_naive_utc(date_from), to_naive_utc(date_to)
    now = utcnow()
    start = date_from or now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = date_to or (start + timedelta(days=1) if date_from is None else now + timedelta(seconds=1))
    return start, end


def _calls(db: Session, start, end, agent_id=None) -> list[CallLog]:
    q = (select(CallLog).options(selectinload(CallLog.donor), selectinload(CallLog.agent))
         .where(CallLog.created_at >= start, CallLog.created_at < end))
    if agent_id:
        q = q.where(CallLog.agent_id == agent_id)
    return list(db.scalars(q.order_by(CallLog.created_at)).all())


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


def agent_rows(db: Session, start, end, agent_id: int | None = None) -> list[dict]:
    agents_q = select(User).where(User.role == "agent")
    if agent_id:
        agents_q = agents_q.where(User.id == agent_id)
    agents = db.scalars(agents_q.order_by(User.name)).all()
    calls = _calls(db, start, end, agent_id)
    donors = db.scalars(select(Donor).where(Donor.assigned_agent_id.is_not(None))).all()
    now = utcnow()

    by_agent: dict[int, list[CallLog]] = defaultdict(list)
    for c in calls:
        by_agent[c.agent_id].append(c)
    snap: dict[int, dict] = defaultdict(lambda: defaultdict(float))
    for d in donors:
        s = snap[d.assigned_agent_id]
        s["assigned"] += 1
        if d.status not in FINAL_STATUSES:
            s["open"] += 1
        if d.status == "new":
            s["untouched"] += 1
        if d.next_action_at and d.next_action_at < now and d.status not in FINAL_STATUSES:
            s["overdue"] += 1
        if d.status == "pledged":
            s["open_pledges"] += 1
            s["open_pledge_amount"] += d.pledge_amount or 0

    rows = []
    for a in agents:
        cs = by_agent.get(a.id, [])
        count = defaultdict(int)
        for c in cs:
            count[c.outcome] += 1
        reached_calls = [c for c in cs if oc.BY_CODE[c.outcome].reached]
        reached_donors = {c.donor_id for c in reached_calls}
        donated = [c for c in cs if c.outcome == "donated"]
        pledged = [c for c in cs if c.outcome == "pledged"]
        # pledge fulfilled = donor pledged (any time) and donated within the range
        fulfilled = 0
        for c in donated:
            if any(x.outcome == "pledged" and x.created_at < c.created_at for x in c.donor.calls):
                fulfilled += 1
        durations = [c.duration_sec for c in cs if c.duration_sec]
        s = snap[a.id]
        rows.append({
            "agent_id": a.id, "agent_name": a.name, "active": a.active, "daily_target": a.daily_target,
            "assigned": int(s["assigned"]), "open": int(s["open"]), "untouched": int(s["untouched"]),
            "overdue_followups": int(s["overdue"]),
            "open_pledges": int(s["open_pledges"]), "open_pledge_amount": s["open_pledge_amount"],
            "calls": len(cs),
            "donors_contacted": len({c.donor_id for c in cs}),
            "reached": len(reached_calls),
            "donated": len(donated),
            "donated_amount": sum(c.amount or 0 for c in donated),
            "pledged": len(pledged),
            "pledged_amount": sum(c.amount or 0 for c in pledged),
            "pledges_fulfilled": fulfilled,
            "interested": count["interested"],
            "callbacks": count["callback"] + count["send_info"],
            "unreachable": sum(count[k] for k in ("no_answer", "busy", "phone_off")),
            "phone_off": count["phone_off"],
            "not_interested": count["not_interested"] + count["donated_elsewhere"] + count["do_not_call"],
            "invalid": count["wrong_number"] + count["not_in_service"],
            "complaints": count["complaint"],
            "contact_rate": _pct(len(reached_calls), len(cs)),
            "conversion_rate": _pct(len({c.donor_id for c in donated}), len(reached_donors)),
            "avg_duration_sec": round(sum(durations) / len(durations)) if durations else 0,
            "outcomes": dict(count),
        })
    return rows


@router.get("/overview")
def overview(date_from: datetime | None = None, date_to: datetime | None = None,
             db: Session = Depends(get_db), _: User = Depends(require_manager)):
    start, end = _range(date_from, date_to)
    rows = agent_rows(db, start, end)
    total_donors = db.scalar(select(func.count(Donor.id)))
    unassigned = db.scalar(select(func.count(Donor.id)).where(Donor.assigned_agent_id.is_(None)))
    calls = sum(r["calls"] for r in rows)
    reached = sum(r["reached"] for r in rows)
    return {
        "range": {"from": start, "to": end},
        "total_donors": total_donors or 0,
        "unassigned": unassigned,
        "calls": calls,
        "reached": reached,
        "contact_rate": _pct(reached, calls),
        "donated": sum(r["donated"] for r in rows),
        "donated_amount": sum(r["donated_amount"] for r in rows),
        "pledged": sum(r["pledged"] for r in rows),
        "pledged_amount": sum(r["pledged_amount"] for r in rows),
        "open_pledge_amount": sum(r["open_pledge_amount"] for r in rows),
        "overdue_followups": sum(r["overdue_followups"] for r in rows),
        "agents": rows,
    }


@router.get("/agents")
def agents_report(date_from: datetime | None = None, date_to: datetime | None = None,
                  agent_id: int | None = None, db: Session = Depends(get_db),
                  user: User = Depends(current_user)):
    if user.role != "manager":
        agent_id = user.id
    start, end = _range(date_from, date_to)
    return {"range": {"from": start, "to": end}, "agents": agent_rows(db, start, end, agent_id)}


@router.get("/outcomes")
def outcomes_report(date_from: datetime | None = None, date_to: datetime | None = None,
                    agent_id: int | None = None, db: Session = Depends(get_db),
                    user: User = Depends(current_user)):
    if user.role != "manager":
        agent_id = user.id
    start, end = _range(date_from, date_to)
    count = defaultdict(int)
    for c in _calls(db, start, end, agent_id):
        count[c.outcome] += 1
    total = sum(count.values())
    return {"total": total, "items": [
        {"code": o.code, "label": o.label, "category": o.category, "count": count[o.code],
         "pct": _pct(count[o.code], total)} for o in oc.OUTCOMES]}


@router.get("/daily")
def daily_report(date_from: datetime | None = None, date_to: datetime | None = None,
                 agent_id: int | None = None, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    if user.role != "manager":
        agent_id = user.id
    date_from, date_to = to_naive_utc(date_from), to_naive_utc(date_to)
    start = date_from or (utcnow() - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = date_to or utcnow() + timedelta(seconds=1)
    days: dict[str, dict] = {}
    d = start
    while d < end:
        days[d.date().isoformat()] = {"date": d.date().isoformat(), "calls": 0, "reached": 0,
                                      "donated": 0, "amount": 0.0, "pledged": 0}
        d += timedelta(days=1)
    hours = defaultdict(lambda: {"calls": 0, "reached": 0})
    for c in _calls(db, start, end, agent_id):
        row = days.setdefault(c.created_at.date().isoformat(), {
            "date": c.created_at.date().isoformat(), "calls": 0, "reached": 0,
            "donated": 0, "amount": 0.0, "pledged": 0})
        row["calls"] += 1
        h = hours[c.created_at.hour]
        h["calls"] += 1
        if oc.BY_CODE[c.outcome].reached:
            row["reached"] += 1
            h["reached"] += 1
        if c.outcome == "donated":
            row["donated"] += 1
            row["amount"] += c.amount or 0
        if c.outcome == "pledged":
            row["pledged"] += 1
    return {
        "days": sorted(days.values(), key=lambda r: r["date"]),
        "hours": [{"hour": h, **v, "reach_rate": _pct(v["reached"], v["calls"])}
                  for h, v in sorted(hours.items())],
    }


@router.get("/pledges")
def pledges_report(agent_id: int | None = None, db: Session = Depends(get_db),
                   user: User = Depends(current_user)):
    if user.role != "manager":
        agent_id = user.id
    q = select(Donor).options(selectinload(Donor.agent)).where(Donor.status == "pledged")
    if agent_id:
        q = q.where(Donor.assigned_agent_id == agent_id)
    now = utcnow()
    items = []
    for d in db.scalars(q.order_by(Donor.pledge_due)).all():
        row = donor_out(d)
        row["overdue"] = bool(d.pledge_due and d.pledge_due < now)
        items.append(row)
    return {"total_amount": sum(i["pledge_amount"] or 0 for i in items), "items": items}


def _csv(rows: list[dict], headers: list[tuple[str, str]], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel shows Arabic correctly
    w = csv.writer(buf)
    w.writerow([label for _, label in headers])
    for r in rows:
        w.writerow([r.get(k, "") for k, _ in headers])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/export/agents.csv")
def export_agents(date_from: datetime | None = None, date_to: datetime | None = None,
                  db: Session = Depends(get_db), _: User = Depends(require_manager)):
    start, end = _range(date_from, date_to)
    headers = [("agent_name", "الايجنت"), ("assigned", "المخصص"), ("open", "مفتوح"),
               ("calls", "مكالمات"), ("reached", "تم الوصول"), ("contact_rate", "نسبة الوصول %"),
               ("donated", "تبرعات"), ("donated_amount", "مبلغ التبرعات"), ("pledged", "وعود"),
               ("pledged_amount", "مبلغ الوعود"), ("pledges_fulfilled", "وعود تم تحصيلها"),
               ("interested", "عنده نية"), ("callbacks", "معاودة اتصال"), ("unreachable", "لم يرد/مغلق/مشغول"),
               ("phone_off", "مغلق"), ("not_interested", "رفض"), ("invalid", "رقم خطأ"),
               ("conversion_rate", "نسبة التحويل %"), ("overdue_followups", "متابعات متأخرة")]
    return _csv(agent_rows(db, start, end), headers, "agents-report.csv")


@router.get("/export/calls.csv")
def export_calls(date_from: datetime | None = None, date_to: datetime | None = None,
                 agent_id: int | None = None, db: Session = Depends(get_db),
                 _: User = Depends(require_manager)):
    start, end = _range(date_from, date_to)
    rows = [{"at": c.created_at.strftime("%Y-%m-%d %H:%M"), "agent": c.agent.name, "donor": c.donor.name,
             "phone": c.donor.phone, "outcome": oc.status_label(c.outcome), "amount": c.amount or "",
             "payment": c.payment_method or "", "follow_up": c.follow_up_at or "", "notes": c.notes or ""}
            for c in _calls(db, start, end, agent_id)]
    headers = [("at", "الوقت"), ("agent", "الايجنت"), ("donor", "المتبرع"), ("phone", "الموبايل"),
               ("outcome", "النتيجة"), ("amount", "المبلغ"), ("payment", "طريقة الدفع"),
               ("follow_up", "موعد المتابعة"), ("notes", "ملاحظات")]
    return _csv(rows, headers, "calls-log.csv")
