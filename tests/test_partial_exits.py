"""
Integration tests for partial exit functionality.
Tests the complete flow from webhook reception to order execution with exit types.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.orm import Session

from app.services.exit_calculator import ExitCalculator
from app.services.position_service import PositionService
from app.services.webhook_service import WebhookProcessor
from app.models.strategy import ActivatedStrategy
from app.models.broker import BrokerAccount
from app.schemas.webhook import ExitType


class TestExitCalculator:
    """Test the exit quantity calculation logic."""
    
    def setup_method(self):
        """Set up test data for each test."""
        self.strategy = MagicMock()
        self.strategy.id = 1
        self.strategy.quantity = 10
        self.strategy.max_position_size = None
        self.strategy.partial_exits_count = 0
    
    @pytest.mark.asyncio
    async def test_entry_calculation(self):
        """Test entry (BUY) signals use configured quantity."""
        quantity, reason = await ExitCalculator.calculate_exit_quantity(
            self.strategy,
            "ENTRY",
            current_position=0,
            configured_quantity=10,
            action="BUY"
        )
        
        assert quantity == 10
        assert "configured quantity" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_50_percent_exit(self):
        """Test 50% partial exit calculation."""
        quantity, reason = await ExitCalculator.calculate_exit_quantity(
            self.strategy,
            "EXIT_50",
            current_position=10,
            configured_quantity=10,
            action="SELL"
        )
        
        assert quantity == 5  # 50% of 10
        assert "50%" in reason
    
    @pytest.mark.asyncio
    async def test_final_exit(self):
        """Test final exit closes entire position."""
        quantity, reason = await ExitCalculator.calculate_exit_quantity(
            self.strategy,
            "EXIT_FINAL",
            current_position=5,
            configured_quantity=10,
            action="SELL"
        )
        
        assert quantity == 5  # All remaining
        assert "final" in reason.lower()
    
    @pytest.mark.asyncio
    async def test_custom_percentage_exit(self):
        """Test custom percentage exits (e.g., EXIT_33)."""
        quantity, reason = await ExitCalculator.calculate_exit_quantity(
            self.strategy,
            "EXIT_33",
            current_position=9,
            configured_quantity=10,
            action="SELL"
        )
        
        # 33% of 9 = 2.97, rounded up = 3
        assert quantity == 3
        assert "33%" in reason
    
    @pytest.mark.asyncio
    async def test_no_position_to_exit(self):
        """Test selling with no position returns 0 quantity."""
        quantity, reason = await ExitCalculator.calculate_exit_quantity(
            self.strategy,
            "EXIT_50",
            current_position=0,
            configured_quantity=10,
            action="SELL"
        )
        
        assert quantity == 0
        assert "no position" in reason.lower()
    
    def test_quantity_validation_oversell(self):
        """Test validation prevents overselling."""
        adjusted_qty, is_valid, message = ExitCalculator.validate_exit_quantity(
            action="SELL",
            calculated_quantity=10,
            current_position=5,
            max_position_size=None
        )
        
        assert adjusted_qty == 5  # Reduced to match position
        assert is_valid == True
        assert "adjusted" in message.lower()
    
    def test_quantity_validation_max_position(self):
        """Test validation respects max position size."""
        adjusted_qty, is_valid, message = ExitCalculator.validate_exit_quantity(
            action="BUY",
            calculated_quantity=10,
            current_position=5,
            max_position_size=10
        )
        
        assert adjusted_qty == 5  # Can only buy 5 more to reach max of 10
        assert is_valid == True
        assert "adjusted" in message.lower()


class TestPositionService:
    """Test position tracking and caching."""
    
    def setup_method(self):
        """Set up mock objects."""
        self.db = MagicMock()
        self.position_service = PositionService(self.db)
    
    @pytest.mark.asyncio
    @patch('app.services.position_service.get_redis_connection')
    async def test_position_caching(self, mock_redis):
        """Test position caching functionality."""
        # Mock Redis
        mock_redis_client = MagicMock()
        mock_redis.return_value.__enter__.return_value = mock_redis_client
        mock_redis_client.get.return_value = "10"  # Cached position
        
        # Test cache hit
        position = await self.position_service._get_cached_position("account123", "ES")
        
        assert position == 10
        mock_redis_client.get.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_position_update_cache(self):
        """Test position cache updates."""
        with patch.object(self.position_service, '_cache_position') as mock_cache:
            with patch.object(self.position_service, 'get_current_position', return_value=10):
                await self.position_service.update_position_cache(
                    "account123",
                    "ES",
                    quantity_change=-5,
                    is_absolute=False
                )
                
                # Should cache new position of 5 (10 - 5)
                mock_cache.assert_called_once_with("account123", "ES", 5)


class TestWebhookIntegration:
    """Test full webhook processing with partial exits."""
    
    def setup_method(self):
        """Set up test environment."""
        self.db = MagicMock()
        self.webhook_processor = WebhookProcessor(self.db)
        
        # Mock webhook
        self.webhook = MagicMock()
        self.webhook.id = 1
        self.webhook.token = "test_token"
        self.webhook.source_type = "tradingview"
        
        # Mock strategy
        self.strategy = MagicMock()
        self.strategy.id = 1
        self.strategy.user_id = 1
        self.strategy.ticker = "ES"
        self.strategy.quantity = 10
        self.strategy.is_active = True
        self.strategy.account_id = "account123"
        self.strategy.strategy_type = "single"
    
    def test_payload_normalization_with_comment(self):
        """Test webhook payload normalization includes comment field."""
        payload = {
            "action": "sell",
            "comment": "exit_50"
        }
        
        normalized = self.webhook_processor.normalize_payload("tradingview", payload)
        
        assert normalized["action"] == "SELL"
        assert normalized["comment"] == "EXIT_50"  # Should be uppercase
        assert "timestamp" in normalized
        assert "source" in normalized
    
    @pytest.mark.asyncio
    @patch('app.services.webhook_service.ActivatedStrategy')
    async def test_webhook_finds_strategies(self, mock_strategy_query):
        """Test webhook processing finds associated strategies."""
        # Mock database query
        mock_strategy_query.query.return_value.filter.return_value.all.return_value = [self.strategy]
        self.db.query.return_value = mock_strategy_query.query.return_value
        
        # Mock strategy processor
        with patch.object(self.webhook_processor, 'strategy_processor') as mock_processor:
            mock_processor.execute_strategy = AsyncMock(return_value={"status": "success"})
            
            payload = {"action": "BUY", "comment": "ENTRY"}
            
            result = await self.webhook_processor._process_webhook_internal(
                self.webhook,
                payload,
                "127.0.0.1",
                datetime.utcnow()
            )
            
            assert result["status"] == "success"
            mock_processor.execute_strategy.assert_called_once()


class TestPartialExitScenarios:
    """Test realistic partial exit scenarios."""
    
    @pytest.mark.asyncio
    async def test_complete_exit_cycle(self):
        """Test a complete cycle: Entry -> 50% Exit -> Final Exit."""
        
        # Scenario: User has 10 contracts configured
        strategy_quantity = 10
        
        # Step 1: Entry (BUY)
        entry_qty, _ = await ExitCalculator.calculate_exit_quantity(
            MagicMock(quantity=strategy_quantity),
            "ENTRY",
            current_position=0,
            configured_quantity=strategy_quantity,
            action="BUY"
        )
        assert entry_qty == 10  # Buy full configured amount
        
        # Step 2: First exit - 50%
        first_exit_qty, _ = await ExitCalculator.calculate_exit_quantity(
            MagicMock(quantity=strategy_quantity),
            "EXIT_50",
            current_position=10,  # Position after entry
            configured_quantity=strategy_quantity,
            action="SELL"
        )
        assert first_exit_qty == 5  # Sell 50%
        
        # Step 3: Final exit
        final_exit_qty, _ = await ExitCalculator.calculate_exit_quantity(
            MagicMock(quantity=strategy_quantity),
            "EXIT_FINAL",
            current_position=5,  # Position after first exit
            configured_quantity=strategy_quantity,
            action="SELL"
        )
        assert final_exit_qty == 5  # Sell remaining
    
    @pytest.mark.asyncio
    async def test_multiple_user_scenarios(self):
        """Test different users with different quantities."""
        
        test_cases = [
            {"user": "A", "config_qty": 2, "expected_50_exit": 1},
            {"user": "B", "config_qty": 10, "expected_50_exit": 5}, 
            {"user": "C", "config_qty": 100, "expected_50_exit": 50},
            {"user": "D", "config_qty": 3, "expected_50_exit": 2},  # 1.5 rounded up
        ]
        
        for case in test_cases:
            # Entry
            entry_qty, _ = await ExitCalculator.calculate_exit_quantity(
                MagicMock(quantity=case["config_qty"]),
                "ENTRY",
                current_position=0,
                configured_quantity=case["config_qty"],
                action="BUY"
            )
            assert entry_qty == case["config_qty"]
            
            # 50% Exit
            exit_qty, _ = await ExitCalculator.calculate_exit_quantity(
                MagicMock(quantity=case["config_qty"]),
                "EXIT_50",
                current_position=case["config_qty"],
                configured_quantity=case["config_qty"],
                action="SELL"
            )
            assert exit_qty == case["expected_50_exit"], f"User {case['user']} failed"


@pytest.fixture
def mock_database():
    """Provide a mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture
def mock_broker():
    """Provide a mock broker instance."""
    broker = MagicMock()
    broker.get_positions = AsyncMock(return_value=[
        {"symbol": "ES", "quantity": 10}
    ])
    broker.place_order = AsyncMock(return_value={
        "order_id": "test_order_123",
        "status": "filled"
    })
    return broker


if __name__ == "__main__":
    # Run specific test
    pytest.main([__file__ + "::TestExitCalculator::test_50_percent_exit", "-v"])