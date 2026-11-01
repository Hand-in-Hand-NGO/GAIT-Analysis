"""Call outcome catalog (dispositions).

Each outcome describes what the agent learned on a call, and drives how the
donor record moves forward (follow-up date, final state, attempts counting).
"""
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Outcome:
    code: str
    label: str
    category: str  # success | positive | pending | unreachable | negative | invalid
    final: bool = False  # donor leaves the agent's active queue
    needs_amount: bool = False
    needs_follow_up: bool = False
    reached: bool = True  # a real conversation happened
    retry_hours: int = 0  # auto-reschedule for unreachable outcomes


OUTCOMES: list[Outcome] = [
    Outcome("donated", "اتبرع", "success", final=True, needs_amount=True),
    Outcome("pledged", "وعد بالتبرع (هيتبرع)", "positive", needs_amount=True, needs_follow_up=True),
    Outcome("interested", "عنده نية / مهتم", "positive"),
    Outcome("callback", "طلب معاودة الاتصال", "pending", needs_follow_up=True),
    Outcome("send_info", "طلب تفاصيل (واتساب / رسالة)", "pending"),
    Outcome("no_answer", "لا يرد", "unreachable", reached=False, retry_hours=4),
    Outcome("busy", "مشغول", "unreachable", reached=False, retry_hours=2),
    Outcome("phone_off", "الموبايل مغلق", "unreachable", reached=False, retry_hours=6),
    Outcome("not_interested", "معندوش نية للتبرع", "negative", final=True),
    Outcome("donated_elsewhere", "اتبرع لجهة أخرى / مؤخراً", "negative", final=True),
    Outcome("do_not_call", "طلب عدم الاتصال مرة أخرى", "negative", final=True),
    Outcome("complaint", "شكوى / يحتاج مراجعة المدير", "pending"),
    Outcome("wrong_number", "رقم خطأ / شخص آخر", "invalid", final=True, reached=False),
    Outcome("not_in_service", "الرقم غير موجود بالخدمة", "invalid", final=True, reached=False),
]

BY_CODE = {o.code: o for o in OUTCOMES}

# After this many unreachable attempts the donor is marked "exhausted".
MAX_UNREACHABLE_ATTEMPTS = 5

# Statuses that are not call outcomes.
EXTRA_STATUSES = {"new": "جديد (لم يتم الاتصال)", "exhausted": "استنفد المحاولات"}


def status_label(code: str) -> str:
    if code in BY_CODE:
        return BY_CODE[code].label
    return EXTRA_STATUSES.get(code, code)


def as_dicts() -> list[dict]:
    return [asdict(o) for o in OUTCOMES]
