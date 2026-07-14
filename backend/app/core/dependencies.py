from fastapi import Header, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.db import get_db, User
from app.core.security import decode_jwt

async def get_current_user(
    authorization: str = Header(..., description="Bearer JWT token"),
    db: AsyncSession = Depends(get_db)
) -> User:
    # Validate authorization header format
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with 'Bearer '",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = decode_jwt(authorization)
    
    # Fetch user from DB
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    return user
