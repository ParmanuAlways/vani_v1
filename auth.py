from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import RedirectResponse
from typing import Optional, Dict
import secrets
from datetime import datetime, timedelta
from database import verify_user, get_user

# Session management
SESSIONS = {}
SESSION_TIMEOUT = timedelta(hours=2)  # Sessions expire after 2 hours

def create_session(user_data: Dict) -> str:
    """Create a new session for a user and return the session token."""
    token = secrets.token_hex(16)
    SESSIONS[token] = {
        "user": user_data,
        "expires": datetime.now() + SESSION_TIMEOUT
    }
    return token

def get_session(token: str) -> Optional[Dict]:
    """Get the session data for a token if it exists and hasn't expired."""
    if token not in SESSIONS:
        return None
    
    session = SESSIONS[token]
    if datetime.now() > session["expires"]:
        # Session has expired
        del SESSIONS[token]
        return None
    
    # Refresh the session expiration
    session["expires"] = datetime.now() + SESSION_TIMEOUT
    return session

def delete_session(token: str) -> None:
    """Delete a session."""
    if token in SESSIONS:
        del SESSIONS[token]

def get_current_user(request: Request) -> Optional[Dict]:
    """Get the current user from the session cookie."""
    token = request.cookies.get("session")
    if not token:
        return None
    
    session = get_session(token)
    if not session:
        return None
    
    return session["user"]

async def authenticate_user(request: Request):
    """Authentication dependency for FastAPI routes."""
    user = get_current_user(request)
    if not user:
        # Instead of returning a RedirectResponse, raise an HTTPException
        # This will be caught by FastAPI and handled appropriately
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            detail="Not authenticated",
            headers={"Location": "/login"}
        )
    return user

async def pilot_required(user: Dict = Depends(authenticate_user)):
    """Role authorization: require pilot role."""
    if not user.get("isPilot"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Pilot role required"
        )
    return user

async def flt_cdr_required(user: Dict = Depends(authenticate_user)):
    """Role authorization: require flight commander role."""
    if not user.get("isFltCdr"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Flight Commander role required"
        )
    return user

async def co_required(user: Dict = Depends(authenticate_user)):
    """Role authorization: require commanding officer role."""
    if not user.get("isCO"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Commanding Officer role required"
        )
    return user