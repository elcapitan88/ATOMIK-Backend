"""
Unified strategy schemas for handling both webhook and engine strategies.
This replaces the separate webhook/engine strategy schemas with a single unified approach.
"""

from enum import Enum
from typing import Optional, List, Dict, Any, Union, Literal
from pydantic import BaseModel, Field, field_validator, model_validator, ConfigDict
from datetime import datetime
from decimal import Decimal


class AccessType(str, Enum):
    """How the user has access to the strategy"""
    OWNED = "owned"
    SUBSCRIBED = "subscribed"
    PURCHASED = "purchased"


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
    """Schema for strategy responses with full enrichment"""

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

    # ============================================================================
    # ENRICHED FIELDS (from webhook/strategy_code lookups)
    # ============================================================================

    # Strategy identification (enriched from webhook or strategy_code)
    name: Optional[str] = None  # Strategy name
    category: Optional[str] = None  # "TradingView Webhook", "Strategy Engine", "Unknown"

    # Webhook enrichment fields
    source_type: Optional[str] = None  # webhook.source_type
    webhook_token: Optional[str] = None  # webhook.token
    creator_id: Optional[int] = None  # webhook.user_id or strategy_code.user_id
    subscriber_count: Optional[int] = None  # webhook.subscriber_count

    # Engine strategy enrichment fields
    symbols: Optional[List[str]] = None  # strategy_code.symbols_list
    is_validated: Optional[bool] = None  # strategy_code.is_validated
    signals_generated: Optional[int] = None  # strategy_code.signals_generated

    # Nested broker account objects (enriched)
    broker_account: Optional[Dict[str, Any]] = None  # {account_id, name, broker_id}
    leader_broker_account: Optional[Dict[str, Any]] = None  # For multiple strategies
    follower_accounts: Optional[List[Dict[str, Any]]] = None  # Full follower details

    # Schedule management fields
    schedule_active_state: Optional[bool] = None  # Current schedule state
    last_scheduled_toggle: Optional[datetime] = None  # Last auto-toggle time

    # ============================================================================
    # PERFORMANCE METRICS (expanded)
    # ============================================================================

    total_trades: Optional[int] = 0
    successful_trades: Optional[int] = 0
    failed_trades: Optional[int] = 0
    total_pnl: Optional[float] = 0.0  # Total profit/loss
    win_rate: Optional[float] = None  # Win rate percentage
    max_drawdown: Optional[float] = None  # Maximum drawdown
    sharpe_ratio: Optional[float] = None  # Risk-adjusted return
    average_win: Optional[float] = None  # Average winning trade
    average_loss: Optional[float] = None  # Average losing trade

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


class StrategyScheduleInfo(BaseModel):
    """Schema for strategy schedule information"""
    scheduled: bool
    market: Optional[List[str]]
    market_info: Optional[Dict[str, Any]] = None
    next_event: Optional[Dict[str, Any]] = None
    last_scheduled_toggle: Optional[datetime] = None
    manual_override: bool

    class Config:
        json_schema_extra = {
            "example": {
                "scheduled": True,
                "market": ["NYSE"],
                "market_info": {"is_open": True, "next_close": "16:00"},
                "next_event": {"event": "close", "time": "16:00"},
                "last_scheduled_toggle": "2025-01-01T09:30:00",
                "manual_override": False
            }
        }


class StrategyScheduleUpdate(BaseModel):
    """Schema for updating strategy schedule"""
    market_schedule: Optional[List[str]] = Field(None, description="Market schedule: NYSE, LONDON, ASIA, 24/7, or None")

    @field_validator('market_schedule')
    def validate_market_schedule(cls, v):
        if v is not None:
            valid_markets = ['NYSE', 'LONDON', 'ASIA', '24/7']
            for market in v:
                if market not in valid_markets:
                    raise ValueError(f"Invalid market: {market}. Must be one of: {', '.join(valid_markets)}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "market_schedule": ["NYSE", "LONDON"]
            }
        }


class AccessibleStrategyResponse(BaseModel):
    """Schema for strategies accessible to the user for activation"""
    id: str = Field(..., description="Unique identifier: webhook_{id} or engine_{id}")
    type: Literal["webhook", "engine"] = Field(..., description="Strategy type")
    source_id: Union[str, int] = Field(..., description="Webhook token or engine strategy ID")
    name: str = Field(..., description="Strategy name")
    description: Optional[str] = Field(None, description="Strategy description")
    access_type: AccessType = Field(..., description="How user has access: owned, subscribed, or purchased")
    category: str = Field(..., description="Strategy category")
    is_premium: bool = Field(default=False, description="Whether this is a premium strategy")
    creator: Optional[str] = Field(None, description="Strategy creator username")

    # Activation capabilities
    supports_single: bool = Field(default=True, description="Supports single account activation")
    supports_multiple: bool = Field(default=True, description="Supports multiple account activation")
    requires_configuration: bool = Field(default=False, description="Requires additional configuration")

    # Additional metadata
    subscriber_count: Optional[int] = Field(None, description="Number of subscribers")
    rating: Optional[float] = Field(None, description="Average rating")
    is_active: bool = Field(default=True, description="Whether strategy is currently active")
    created_at: Optional[datetime] = Field(None, description="When strategy was created")

    model_config = ConfigDict(
        from_attributes=True,
        json_encoders={
            datetime: lambda v: v.isoformat() if v else None
        }
    )