from pydantic import BaseModel, EmailStr
from typing import Optional

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    phone: Optional[str] = None

class UserCreate(UserBase):
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    profile_picture: Optional[str] = None
    username: Optional[str] = None
    email: Optional[EmailStr] = None

class UserOut(UserBase):
    id: int
    is_active: bool
    profile_picture: Optional[str] = None
    app_role: Optional[str] = None
    is_creator: Optional[bool] = False
    onboarding_step: Optional[int] = None
    onboarding_data: Optional[dict] = None

    class Config:
        from_attributes = True
        
    @classmethod
    def from_user(cls, user):
        """Create UserOut from User model with computed fields"""
        return cls(
            id=user.id,
            email=user.email,
            username=user.username,
            full_name=user.full_name,
            phone=user.phone,
            is_active=user.is_active,
            profile_picture=user.profile_picture,
            app_role=user.app_role,
            is_creator=user.is_creator(),
            onboarding_step=user.onboarding_step,
            onboarding_data=user.onboarding_data
        )

class UserInDB(UserBase):
    hashed_password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenUserInfo(BaseModel):
    id: int
    email: str
    username: str
    subscription_tier: Optional[str] = "free"

class TokenWithUser(BaseModel):
    access_token: str
    token_type: str
    user: TokenUserInfo

class TokenData(BaseModel):
    email: str | None = None