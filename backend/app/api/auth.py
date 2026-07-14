from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.db import get_db, User
from app.schemas.requests import RegisterRequest, LoginRequest
from app.schemas.responses import AuthResponse
from app.core.security import hash_password, verify_password, create_jwt

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # Check if user already exists
    result = await db.execute(select(User).where(User.email == request.email))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists"
        )
    
    # Create new user
    new_user = User(
        email=request.email,
        name=request.name,
        password_hash=hash_password(request.password)
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    
    token = create_jwt(new_user.id)
    return AuthResponse(user_id=new_user.id, token=token)

@router.post("/login", response_model=AuthResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Find user by email
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalars().first()
    
    # Validate credentials
    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password"
        )
        
    token = create_jwt(user.id)
    return AuthResponse(user_id=user.id, token=token)
