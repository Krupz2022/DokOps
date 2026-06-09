from datetime import datetime, timedelta
from typing import Any, Union
import bcrypt
from jose import jwt
from app.core.config import settings

ALGORITHM = "HS256"

# Use bcrypt directly — passlib 1.7.4 is incompatible with bcrypt 5.x
def get_password_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

# Keep pwd_context as a shim so any code that calls pwd_context.hash/verify still works
class _PwdContextShim:
    def hash(self, password: str) -> str:
        return get_password_hash(password)
    def verify(self, plain: str, hashed: str) -> bool:
        return verify_password(plain, hashed)

pwd_context = _PwdContextShim()

def create_access_token(subject: Union[str, Any], expires_delta: timedelta = None) -> str:
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(to_encode, settings.AUTH_SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
