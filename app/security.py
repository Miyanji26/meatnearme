import hmac

from fastapi import Header, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app import config

_serializer = URLSafeTimedSerializer(config.SECRET_KEY, salt="freshcut-ops")
OPS_SESSION_MAX_AGE = 12 * 60 * 60


def check_ops_password(candidate: str) -> bool:
    return hmac.compare_digest((candidate or "").encode(), config.OPS_PASSWORD.encode())


def issue_ops_token() -> str:
    return _serializer.dumps("ops")


def is_ops(request: Request) -> bool:
    token = request.cookies.get(config.OPS_COOKIE)
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=OPS_SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return True


def require_agent_key(x_agent_key: str = Header(None, alias="X-Agent-Key")) -> str:
    if not config.AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AGENT_API_KEY is not configured",
        )
    if not x_agent_key or not hmac.compare_digest(x_agent_key, config.AGENT_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Agent-Key"
        )
    return x_agent_key
