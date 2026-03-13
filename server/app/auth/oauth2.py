"""
OAuth2 with JWT tokens for authentication.
Replaces hardcoded credentials with token-based auth.
"""

from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel

from app.config.settings import settings

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_PREFIX}/auth/token")


# Pydantic models
class Token(BaseModel):
    """Access token response."""
    access_token: str
    token_type: str


class TokenData(BaseModel):
    """Data stored in JWT token."""
    username: Optional[str] = None
    user_id: Optional[str] = None
    role: Optional[str] = None


class UserInDB(BaseModel):
    """User model from database."""
    id: str
    username: str
    email: str
    hashed_password: str
    role: str  # doctor, nurse, admin, medical_assistant
    is_active: bool = True


class User(BaseModel):
    """Public user model (without password)."""
    id: str
    username: str
    email: str
    role: str
    is_active: bool


# Password utilities
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    # Convert strings to bytes
    password_bytes = plain_password.encode('utf-8')
    hash_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hash_bytes)


def get_password_hash(password: str) -> str:
    """Hash a password for storing."""
    # Convert password to bytes
    password_bytes = password.encode('utf-8')
    # Generate salt and hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    # Return as string
    return hashed.decode('utf-8')


# JWT token utilities
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token
        expires_delta: Optional expiration time delta

    Returns:
        Encoded JWT token
    """
    to_encode = data.copy()

    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    return encoded_jwt


def decode_access_token(token: str) -> TokenData:
    """
    Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        TokenData with user information

    Raises:
        HTTPException: If token is invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        role: str = payload.get("role")

        if username is None:
            raise credentials_exception

        token_data = TokenData(username=username, user_id=user_id, role=role)
        return token_data

    except JWTError:
        raise credentials_exception


# Database interaction (temporary - will be replaced by repository pattern)
# TODO: Replace with actual database queries using SQLAlchemy
async def get_user_from_db(username: str) -> Optional[UserInDB]:
    """
    Get user from database by username.
    This is a temporary implementation - will be replaced with repository pattern.

    For MVP, this uses a hardcoded demo user.
    Post-MVP: Replace with actual database query.
    """
    # Temporary demo user for MVP
    # Password is "demo123" hashed
    demo_users = {
        "demo_doctor": UserInDB(
            id="user_001",
            username="demo_doctor",
            email="doctor@medscribe.com",
            hashed_password=get_password_hash("demo123"),
            role="doctor",
            is_active=True
        ),
        "demo_nurse": UserInDB(
            id="user_002",
            username="demo_nurse",
            email="nurse@medscribe.com",
            hashed_password=get_password_hash("demo123"),
            role="nurse",
            is_active=True
        )
    }

    return demo_users.get(username)


async def authenticate_user(username: str, password: str) -> Optional[UserInDB]:
    """
    Authenticate a user by username and password.

    Args:
        username: User's username
        password: User's plain text password

    Returns:
        UserInDB if authentication successful, None otherwise
    """
    user = await get_user_from_db(username)

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


# FastAPI dependencies
async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """
    FastAPI dependency to get the current authenticated user.

    Args:
        token: JWT token from Authorization header

    Returns:
        Current user

    Raises:
        HTTPException: If authentication fails
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token_data = decode_access_token(token)

    user = await get_user_from_db(token_data.username)
    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )

    # Return public user model (without password)
    return User(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active
    )


async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """
    Get current active user (additional check).

    Args:
        current_user: Current user from get_current_user dependency

    Returns:
        Current user if active

    Raises:
        HTTPException: If user is not active
    """
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_user


# Role-based access control helpers
def require_role(required_role: str):
    """
    Decorator/dependency to require specific user role.

    Args:
        required_role: Required role (doctor, nurse, admin, etc.)

    Returns:
        FastAPI dependency function
    """
    async def check_role(current_user: User = Depends(get_current_user)):
        if current_user.role != required_role and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {required_role} role"
            )
        return current_user

    return check_role


def require_any_role(allowed_roles: list[str]):
    """
    Decorator/dependency to require any of the specified roles.

    Args:
        allowed_roles: List of allowed roles

    Returns:
        FastAPI dependency function
    """
    async def check_role(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles and current_user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of these roles: {', '.join(allowed_roles)}"
            )
        return current_user

    return check_role
