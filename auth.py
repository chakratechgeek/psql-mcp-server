from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

import jwt
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# =========================
# CONFIG
# =========================
SECRET_KEY = "CHANGE_ME_TO_A_LONG_RANDOM_SECRET"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Demo users
USERS: Dict[str, Dict[str, str]] = {
    "chakra": {"password": "P@ssw0rd123", "role": "user"},
    "admin": {"password": "Admin#123", "role": "admin"},
}

app = FastAPI(title="JWT Bearer Auth Demo")

# ✅ ADDED: CORS middleware to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")


# =========================
# MODELS
# =========================
class LoginRequest(BaseModel):
    """✅ ADDED: Model for JSON login request"""
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int


# =========================
# JWT HELPERS
# =========================
def create_access_token(subject: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp())
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_and_verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# =========================
# AUTH DEPENDENCY
# =========================
def get_current_user(token: str = Depends(oauth2_scheme)):
    claims = decode_and_verify_token(token)
    username = claims.get("sub")
    if not username or username not in USERS:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return {"username": username, "role": claims.get("role")}


# =========================
# ROUTES
# =========================
@app.post("/login", response_model=TokenResponse)
def login(credentials: LoginRequest):  # ✅ FIXED: Now accepts JSON data
    """Login endpoint that accepts JSON credentials"""
    user = USERS.get(credentials.username)
    if not user or user["password"] != credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Bad credentials"
        )

    token = create_access_token(subject=credentials.username, role=user["role"])
    return TokenResponse(
        access_token=token,
        expires_in_seconds=ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )


@app.get("/me")
def me(current_user=Depends(get_current_user)):
    """Get current user information"""
    return {"message": "Authorized", "user": current_user}


# ✅ ADDED: Health check endpoint
@app.get("/health")
def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
