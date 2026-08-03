from fastapi import APIRouter, Depends

from ... import schemas
from ...config import settings
from ...database import get_db_context
from ...models import User, UserRole
from ...security.api_key import require_phrolova_sso_key
from ...security.tickets import consume_login_ticket


router = APIRouter(dependencies=[Depends(require_phrolova_sso_key)])


@router.post("/exchange", response_model=schemas.SSOIdentityResponse)
def exchange_phrolova_ticket(payload: schemas.SSOExchangeRequest):
    """Atomically consume a Phrolova ticket and return authoritative QQ identity."""
    with get_db_context() as db:
        ticket = consume_login_ticket(db, payload.ticket, "phrolova")
        qq_number = ticket.qq_number
        user = db.query(User).filter(User.qq_number == qq_number).first()
        target_role = UserRole.ROOT.value if qq_number == settings.ROOT_QQ else UserRole.USER.value

        if user is None:
            user = User(
                qq_number=qq_number,
                role=target_role,
                password_hash=None,
                nickname=f"QQ用户{qq_number[-4:]}",
                avatar_url=f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640",
            )
            db.add(user)
        else:
            if qq_number == settings.ROOT_QQ:
                user.role = UserRole.ROOT.value
            elif user.role == UserRole.ROOT.value:
                user.role = UserRole.USER.value
            user.password_hash = None
            if not user.nickname:
                user.nickname = f"QQ用户{qq_number[-4:]}"
            if not user.avatar_url:
                user.avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq_number}&s=640"

        db.commit()
        db.refresh(user)
        return schemas.SSOIdentityResponse(
            qq_number=user.qq_number,
            nickname=user.nickname,
            avatar_url=user.avatar_url,
            role=user.role,
        )
