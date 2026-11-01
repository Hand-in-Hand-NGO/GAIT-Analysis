from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AssignmentLog, Donor, User
from ..schemas import AssignIn, AutoDistributeIn, TransferIn, UnassignIn
from ..security import require_manager
from .. import services

router = APIRouter(prefix="/api/distribution", tags=["distribution"])


@router.get("/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(require_manager)):
    """Current workload of every agent plus the unassigned pool."""
    agents = db.scalars(select(User).where(User.role == "agent").order_by(User.name)).all()
    total = dict(db.execute(select(Donor.assigned_agent_id, func.count()).group_by(Donor.assigned_agent_id)).all())
    open_ = dict(db.execute(
        select(Donor.assigned_agent_id, func.count())
        .where(Donor.status.not_in(services.FINAL_STATUSES)).group_by(Donor.assigned_agent_id)).all())
    new = dict(db.execute(
        select(Donor.assigned_agent_id, func.count())
        .where(Donor.status == "new").group_by(Donor.assigned_agent_id)).all())
    unassigned_new = db.scalar(select(func.count()).where(
        Donor.assigned_agent_id.is_(None), Donor.status == "new", Donor.do_not_call.is_(False)))
    return {
        "unassigned_total": total.get(None, 0),
        "unassigned_new": unassigned_new,
        "agents": [{"id": a.id, "name": a.name, "active": a.active,
                    "assigned": total.get(a.id, 0), "open": open_.get(a.id, 0), "new": new.get(a.id, 0)}
                   for a in agents],
    }


@router.post("/auto")
def auto(body: AutoDistributeIn, db: Session = Depends(get_db), manager: User = Depends(require_manager)):
    given = services.auto_distribute(db, manager, body.agent_ids, body.mode, body.per_agent, body.limit, body.filter)
    return {"assigned": sum(given.values()), "per_agent": given}


@router.post("/assign")
def assign(body: AssignIn, db: Session = Depends(get_db), manager: User = Depends(require_manager)):
    return {"assigned": services.assign(db, manager, body.donor_ids, body.agent_id)}


@router.post("/unassign")
def unassign(body: UnassignIn, db: Session = Depends(get_db), manager: User = Depends(require_manager)):
    return {"unassigned": services.unassign(db, manager, body.donor_ids)}


@router.post("/transfer")
def transfer(body: TransferIn, db: Session = Depends(get_db), manager: User = Depends(require_manager)):
    given = services.transfer(db, manager, body.from_agent_id, body.to_agent_ids, body.only_open)
    return {"moved": sum(given.values()), "per_agent": given}


@router.get("/history")
def history(donor_id: int | None = None, limit: int = 200, db: Session = Depends(get_db),
            _: User = Depends(require_manager)):
    q = select(AssignmentLog).order_by(AssignmentLog.created_at.desc()).limit(limit)
    if donor_id:
        q = q.where(AssignmentLog.donor_id == donor_id)
    names = dict(db.execute(select(User.id, User.name)).all())
    return [{"donor_id": r.donor_id, "from": names.get(r.from_agent_id), "to": names.get(r.to_agent_id),
             "by": names.get(r.by_user_id), "reason": r.reason, "at": r.created_at}
            for r in db.scalars(q).all()]
