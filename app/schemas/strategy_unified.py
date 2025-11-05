"""
Unified strategy schemas for handling both webhook and engine strategies.
This replaces the separate webhook/engine strategy schemas with a single unified approach.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from datetime import datetime
from decimal import Decimal


class StrategyType(str, Enum):
    """Strategy account configuration type"""
    SINGLE = "single"
    MULTIPLE = "multiple"


class ExecutionType(str, Enum):
    """Strategy execution method"""
    WEBHOOK = "webhook"
    ENGINE = "engine"


class FollowerAccount(BaseModel):
    """Schema for follower account in multiple strategies"""
    account_id: str = Field(..., description="Follower account ID")
    quantity: int = Field(..., gt=0, description="Trading quantity for this follower")


class UnifiedStrategyBase(BaseModel):
    """Base fields shared by all strategy operations"""
    strategy_type: StrategyType = Field(..., description="Single or multiple account strategy")
    execution_type: ExecutionType = Field(..., description="Webhook or engine execution")
    ticker: str = Field(..., min_length=1, max_length=10, description="Trading symbol")
    is_active: bool = Field(default=True, description="Whether strategy is active")
    market_schedule: Optional[List[str]] = Field(None, description="Market hours schedule")
    description: Optional[str] = Field(None, description="Strategy description")


class UnifiedStrategyCreate(UnifiedStrategyBase):
    """Schema for creating any type of strategy"""

    # Execution source (one required based on execution_type)
    webhook_id: Optional[str] = Field(None, description="Webhook token for webhook strategies")
    strategy_code_id: Optional[int] = Field(None, description="Strategy code ID for engine strategies")

    # Single strategy fields (required when strategy_type=SINGLE)
    account_id: Optional[str] = Field(None, description="Trading account for single strategy")
    quantity: Optional[int] = Field(None, gt=0, description="Trading quantity for single strategy")

    # Multiple strategy fields (required when strategy_type=MULTIPLE)
    leader_account_id: Optional[str] = Field(None, description="Leader account for multiple strategy")
    leader_quantity: Optional[int] = Field(None, gt=0, description="Leader quantity for multiple strategy")
    follower_accounts: Optional[List[FollowerAccount]] = Field(None, description="Follower accounts")
    group_name: Optional[str] = Field(None, max_length=100, description="Group name for multiple strategy")

    @model_validator(mode='after')
    def validate_execution_source(self):
        """Ensure correct execution source is provided based on execution_type"""
        if self.execution_type == ExecutionType.WEBHOOK and not self.webhook_id:
            raise ValueError("webhook_id is required for webhook execution type")
        elif self.execution_type == ExecutionType.ENGINE and not self.strategy_code_id:
            raise ValueError("strategy_code_id is required for engine execution type")
        return self

    @model_validator(mode='after')
    def validate_single_fields(self):
        """Validate single strategy required fields"""
        if self.strategy_type == StrategyType.SINGLE:
            if not self.account_id:
                raise ValueError("account_id is required for single strategy")
            if not self.quantity:
                raise ValueError("quantity is required for single strategy")
        return self

    @model_validator(mode='after')
    def validate_multiple_fields(self):
        """Validate multiple strategy required fields"""
        if self.strategy_type == StrategyType.MULTIPLE:
            if not self.leader_account_id:
                raise ValueError("leader_account_id is required for multiple strategy")
            if not self.leader_quantity:
                raise ValueError("leader_quantity is required for multiple strategy")
            if not self.follower_accounts or len(self.follower_accounts) == 0:
                raise ValueError("At least one follower account is required for multiple strategy")

            # Check for duplicate account IDs
            account_ids = [f.account_id for f in self.follower_accounts]
            if len(account_ids) != len(set(account_ids)):
                raise ValueError("Duplicate account IDs in follower accounts")

            # Ensure leader account is not in followers
            if self.leader_account_id in account_ids:
                raise ValueError("Leader account cannot be in follower accounts")
        return self

    # Combined all validations into the model validators above for Pydantic v2 compatibility

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_type": "single",
                "execution_type": "webhook",
                "webhook_id": "abc123webhook",
                "ticker": "ES",
                "account_id": "12345",
                "quantity": 2,
                "is_active": True
            }
        }


class UnifiedStrategyUpdate(BaseModel):
    """Schema for updating any strategy - only updatable fields"""

    # These fields can be updated
    is_active: Optional[bool] = None
    quantity: Optional[int] = Field(None, gt=0, description="For single strategies")
    leader_quantity: Optional[int] = Field(None, gt=0, description="For multiple strategies")
    follower_quantities: Optional[List[int]] = Field(None, description="Update all follower quantities")
    market_schedule: Optional[List[str]] = None
    description: Optional[str] = None
    group_name: Optional[str] = Field(None, max_length=100, description="For multiple strategies")

    # Note: Core fields CANNOT be updated (ticker, execution_type, accounts, webhook_id, strategy_code_id)
    # If these need to change, the strategy must be deleted and recreated

    class Config:
        json_schema_extra = {
            "example": {
                "quantity": 3,
                "is_active": True,
                "description": "Updated strategy description"
            }
        }


class UnifiedStrategyResponse(UnifiedStrategyBase):
    """Schema for strategy responses"""

    # Identity fields
    id: int
    user_id: int

    # Execution sources
    webhook_id: Optional[str]
    strategy_code_id: Optional[int]

    # Single strategy fields
    account_id: Optional[str]
    quantity: Optional[int]

    # Multiple strategy fields
    leader_account_id: Optional[str]
    leader_quantity: Optional[int]
    follower_account_ids: Optional[List[str]]
    follower_quantities: Optional[List[int]]
    group_name: Optional[str]

    # Timestamps
    created_at: datetime
    updated_at: Optional[datetime]
    last_triggered: Optional[datetime]

    # Performance stats (optional, can be expanded)
    total_trades: Optional[int] = 0
    successful_trades: Optional[int] = 0
    failed_trades: Optional[int] = 0
    win_rate: Optional[float] = None

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            Decimal: lambda v: float(v)
        }
    )


class StrategyValidationRequest(BaseModel):
    """Schema for validating strategy data before creation"""
    strategy_data: UnifiedStrategyCreate

    class Config:
        json_schema_extra = {
            "example": {
                "strategy_data": {
                    "strategy_type": "single",
                    "execution_type": "webhook",
                    "webhook_id": "test123",
                    "ticker": "ES",
                    "account_id": "12345",
                    "quantity": 1
                }
            }
        }


class StrategyValidationResponse(BaseModel):
    """Schema for validation response"""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    class Config:
        json_schema_extra = {
            "example": {
                "valid": True,
                "errors": [],
                "warnings": ["Close to subscription limit"]
            }
        }


class StrategyListFilters(BaseModel):
    """Schema for filtering strategy list"""
    execution_type: Optional[ExecutionType] = None
    strategy_type: Optional[StrategyType] = None
    is_active: Optional[bool] = None
    ticker: Optional[str] = None
    account_id: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "execution_type": "webhook",
                "is_active": True,
                "ticker": "ES"
            }
        }


class StrategyToggleResponse(BaseModel):
    """Response for toggle operation"""
    id: int
    is_active: bool
    message: str = "Strategy toggled successfully"


class StrategyBatchOperation(BaseModel):
    """Schema for batch operations on strategies"""
    strategy_ids: List[int] = Field(..., min_items=1, description="List of strategy IDs")
    operation: str = Field(..., description="Operation to perform: activate, deactivate, delete")

    @field_validator('operation')
    def validate_operation(cls, v):
        allowed = ['activate', 'deactivate', 'delete']
        if v not in allowed:
            raise ValueError(f"Operation must be one of: {', '.join(allowed)}")
        return v