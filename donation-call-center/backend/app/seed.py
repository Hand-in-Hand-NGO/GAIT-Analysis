"""Bootstrap data.

`ensure_admin()` runs at startup: creates the first manager account if no
users exist (username/password from env, default admin / admin123).

`python -m app.seed --demo` fills the DB with sample agents, donors and calls.
"""
import os
import random
import sys
from datetime import timedelta

from sqlalchemy import func, select

from .db import Base, SessionLocal, engine
from .models import User, Donor, utcnow
from .schemas import CallIn
from .security import hash_password
from . import services


def ensure_admin():
    with SessionLocal() as db:
        if db.scalar(select(func.count(User.id))):
            return
        db.add(User(name="مدير الكول سنتر", username=os.environ.get("CALLCENTER_ADMIN_USER", "admin"),
                    role="manager",
                    password_hash=hash_password(os.environ.get("CALLCENTER_ADMIN_PASSWORD", "admin123"))))
        db.commit()


FIRST = ["أحمد", "محمد", "محمود", "مصطفى", "سارة", "منى", "هبة", "علي", "يوسف", "نورا", "خالد", "إيمان",
         "عمرو", "دينا", "طارق", "ريم", "حسن", "ياسمين", "كريم", "مريم"]
LAST = ["عبد الله", "السيد", "حسين", "إبراهيم", "فؤاد", "سالم", "الشريف", "منصور", "رشدي", "عثمان"]
CITIES = ["القاهرة", "الجيزة", "الإسكندرية", "المنصورة", "طنطا", "أسيوط"]
SOURCES = ["حملة رمضان", "متبرعين سابقين", "فيسبوك", "زكاة المال"]


def demo(n_donors: int = 300):
    rnd = random.Random(7)
    Base.metadata.create_all(engine)
    ensure_admin()
    with SessionLocal() as db:
        manager = db.scalar(select(User).where(User.role == "manager"))
        agents = []
        for i, name in enumerate(["سارة علي", "محمد حسن", "منى إبراهيم", "يوسف خالد"], start=1):
            u = db.scalar(select(User).where(User.username == f"agent{i}"))
            if not u:
                u = User(name=name, username=f"agent{i}", role="agent", password_hash=hash_password("agent123"))
                db.add(u)
            agents.append(u)
        db.commit()
        start = db.scalar(select(func.count(Donor.id)))
        for i in range(n_donors):
            phone = f"010{rnd.randint(10_000_000, 99_999_999)}"
            if db.scalar(select(Donor.id).where(Donor.phone == phone)):
                continue
            db.add(Donor(name=f"{rnd.choice(FIRST)} {rnd.choice(LAST)}", phone=phone,
                         city=rnd.choice(CITIES), source=rnd.choice(SOURCES),
                         last_donation_amount=rnd.choice([None, 100, 200, 500, 1000])))
        db.commit()
        services.auto_distribute(db, manager, [a.id for a in agents], "balanced", None,
                                 int(n_donors * 0.8), services.DonorFilter())
        weights = {"donated": 12, "pledged": 8, "interested": 8, "callback": 8, "send_info": 4,
                   "no_answer": 22, "busy": 6, "phone_off": 12, "not_interested": 12, "donated_elsewhere": 2,
                   "do_not_call": 1, "wrong_number": 3, "not_in_service": 2}
        codes, w = list(weights), list(weights.values())
        for donor in db.scalars(select(Donor).where(Donor.assigned_agent_id.is_not(None))).all():
            if rnd.random() < 0.3:
                continue
            agent = db.get(User, donor.assigned_agent_id)
            code = rnd.choices(codes, w)[0]
            data = CallIn(outcome=code, duration_sec=rnd.randint(20, 400),
                          amount=rnd.choice([100, 200, 300, 500, 1000]) if code in ("donated", "pledged") else None,
                          payment_method="فودافون كاش" if code == "donated" else None,
                          follow_up_at=utcnow() + timedelta(days=rnd.randint(-1, 5))
                          if code in ("pledged", "callback") else None)
            call = services.log_call(db, donor, agent, data)
            # spread demo calls over the last 10 days, office hours
            call.created_at = utcnow().replace(hour=rnd.randint(10, 20)) - timedelta(days=rnd.randint(0, 9))
            db.commit()
        print(f"demo data ready: {db.scalar(select(func.count(Donor.id))) - start} new donors, "
              f"agents agent1..agent4 / agent123, manager admin / admin123")


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        ensure_admin()
