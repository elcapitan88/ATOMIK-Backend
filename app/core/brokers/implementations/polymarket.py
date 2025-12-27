"""Polymarket broker implementation for prediction market trading.

This broker integrates with Polymarket's CLOB (Central Limit Order Book) API
for executing trades on prediction markets. Requires a Polygon wallet for
signing transactions and USDC for settlement.
"""

import logging
import aiohttp
from typing import Dict, List, Optional, Any
from datetime import datetime

from sqlalchemy.orm import Session

from ..base import BaseBroker, BrokerException, AuthenticationError, ConnectionError, OrderError
from ..config import BrokerEnvironment

logger = logging.getLogger(__name__)


class PolymarketBroker(BaseBroker):
    """
    Polymarket CLOB broker for prediction market trading.
    
    Authentication:
    - API Key + API Secret (from Polymarket dashboard)
    - Polygon wallet private key (for signing transactions)
    
    Note: Polymarket is not available to US persons.
    """
    
    CLOB_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self, broker_id: str, db: Session):
        super().__init__(broker_id, db)
        self.session: Optional[aiohttp.ClientSession] = None
        self._api_key: Optional[str] = None
        self._api_secret: Optional[str] = None
        self._wallet_address: Optional[str] = None
        
    async def _ensure_session(self) -> aiohttp.ClientSession:
        """Ensure HTTP session exists."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self.session
    
    async def authenticate(self, credentials: Dict[str, Any]) -> Any:
        """
        Authenticate with Polymarket.
        
        Required credentials:
        - api_key: Polymarket API key
        - api_secret: Polymarket API secret
        - wallet_address: Polygon wallet address (optional, for signing)
        """
        try:
            api_key = credentials.get("api_key")
            api_secret = credentials.get("api_secret")
            
            if not api_key or not api_secret:
                raise AuthenticationError("API key and secret are required")
            
            # Test credentials by fetching API key info
            session = await self._ensure_session()
            headers = self._build_headers(api_key, api_secret)
            
            async with session.get(f"{self.CLOB_URL}/auth/api-key", headers=headers) as response:
                if response.status == 200:
                    self._api_key = api_key
                    self._api_secret = api_secret
                    self._wallet_address = credentials.get("wallet_address")
                    
                    data = await response.json()
                    logger.info(f"Polymarket authentication successful for wallet: {data.get('funderAddress', 'unknown')}")
                    
                    # Return credentials object for storage
                    from ....models.broker import BrokerCredentials
                    return BrokerCredentials(
                        broker_id=self.broker_id,
                        access_token=api_key,
                        refresh_token=api_secret,
                        token_expiry=None,  # API keys don't expire
                        additional_data={
                            "wallet_address": self._wallet_address or data.get("funderAddress")
                        }
                    )
                else:
                    error = await response.text()
                    raise AuthenticationError(f"Authentication failed: {error}")
                    
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error(f"Polymarket authentication error: {e}")
            raise AuthenticationError(f"Authentication failed: {str(e)}")
    
    async def validate_credentials(self, credentials: Any) -> bool:
        """Validate stored credentials."""
        try:
            if not credentials or not credentials.access_token:
                return False
            
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            async with session.get(f"{self.CLOB_URL}/auth/api-key", headers=headers) as response:
                return response.status == 200
                
        except Exception as e:
            logger.error(f"Credential validation error: {e}")
            return False
    
    async def refresh_credentials(self, credentials: Any) -> Any:
        """Refresh credentials - API keys don't expire so just return existing."""
        return credentials
    
    async def connect_account(
        self,
        user: Any,
        account_id: str,
        environment: BrokerEnvironment,
        credentials: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Connect Polymarket account."""
        try:
            if not credentials:
                raise ConnectionError("Credentials required for Polymarket")
            
            # Authenticate
            broker_creds = await self.authenticate(credentials)
            
            # Create account record
            from ....models.broker import BrokerAccount
            
            account = BrokerAccount(
                user_id=user.id,
                broker_id=self.broker_id,
                account_id=account_id or broker_creds.additional_data.get("wallet_address", "polymarket"),
                environment=environment.value,
                display_name=credentials.get("display_name", "Polymarket"),
                is_active=True,
                is_primary=True,
                metadata={
                    "wallet_address": broker_creds.additional_data.get("wallet_address")
                }
            )
            
            self.db.add(account)
            self.db.commit()
            self.db.refresh(account)
            
            # Store credentials
            broker_creds.account_id = account.id
            self.db.add(broker_creds)
            self.db.commit()
            
            logger.info(f"Connected Polymarket account for user {user.id}")
            return account
            
        except Exception as e:
            logger.error(f"Account connection error: {e}")
            self.db.rollback()
            raise ConnectionError(f"Failed to connect account: {str(e)}")
    
    async def disconnect_account(self, account: Any) -> bool:
        """Disconnect Polymarket account."""
        try:
            account.is_active = False
            self.db.commit()
            logger.info(f"Disconnected Polymarket account {account.id}")
            return True
        except Exception as e:
            logger.error(f"Disconnect error: {e}")
            self.db.rollback()
            return False
    
    async def fetch_accounts(self, user: Any) -> List[Dict[str, Any]]:
        """Fetch user's Polymarket accounts."""
        from ....models.broker import BrokerAccount
        
        accounts = self.db.query(BrokerAccount).filter(
            BrokerAccount.user_id == user.id,
            BrokerAccount.broker_id == self.broker_id,
            BrokerAccount.is_active == True
        ).all()
        
        return [
            {
                "id": acc.id,
                "account_id": acc.account_id,
                "display_name": acc.display_name,
                "environment": acc.environment,
                "wallet_address": acc.metadata.get("wallet_address") if acc.metadata else None
            }
            for acc in accounts
        ]
    
    async def get_account_status(self, account: Any) -> Dict[str, Any]:
        """Get account status and balances."""
        try:
            credentials = await self._get_account_credentials(account)
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            async with session.get(f"{self.CLOB_URL}/auth/api-key", headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "connected": True,
                        "wallet_address": data.get("funderAddress"),
                        "api_key_valid": True,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                return {"connected": False, "api_key_valid": False}
                
        except Exception as e:
            logger.error(f"Account status error: {e}")
            return {"connected": False, "error": str(e)}
    
    async def get_positions(self, account: Any) -> List[Dict[str, Any]]:
        """Get current positions."""
        try:
            credentials = await self._get_account_credentials(account)
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            async with session.get(f"{self.CLOB_URL}/positions", headers=headers) as response:
                if response.status == 200:
                    positions = await response.json()
                    return [
                        self.normalize_position_response(pos)
                        for pos in positions
                    ]
                return []
                
        except Exception as e:
            logger.error(f"Get positions error: {e}")
            return []
    
    async def get_orders(self, account: Any) -> List[Dict[str, Any]]:
        """Get open orders."""
        try:
            credentials = await self._get_account_credentials(account)
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            async with session.get(f"{self.CLOB_URL}/orders", headers=headers) as response:
                if response.status == 200:
                    orders = await response.json()
                    return [
                        self.normalize_order_response(order)
                        for order in orders
                    ]
                return []
                
        except Exception as e:
            logger.error(f"Get orders error: {e}")
            return []
    
    async def place_order(
        self,
        account: Any,
        order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Place a limit order on Polymarket.
        
        order_data:
        - token_id: The outcome token ID
        - side: "BUY" or "SELL"
        - price: Price between 0 and 1
        - size: Amount in USDC
        """
        try:
            credentials = await self._get_account_credentials(account)
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            # Build order payload
            order_payload = {
                "tokenID": order_data.get("token_id"),
                "side": order_data.get("side", "BUY").upper(),
                "price": str(order_data.get("price")),
                "size": str(order_data.get("size")),
                "orderType": "GTC",  # Good Till Cancelled
            }
            
            async with session.post(
                f"{self.CLOB_URL}/order",
                headers=headers,
                json=order_payload
            ) as response:
                if response.status in (200, 201):
                    result = await response.json()
                    logger.info(f"Order placed: {result.get('orderID')}")
                    return self.normalize_order_response(result)
                else:
                    error = await response.text()
                    raise OrderError(f"Order failed: {error}")
                    
        except OrderError:
            raise
        except Exception as e:
            logger.error(f"Place order error: {e}")
            raise OrderError(f"Failed to place order: {str(e)}")
    
    async def cancel_order(self, account: Any, order_id: str) -> bool:
        """Cancel an open order."""
        try:
            credentials = await self._get_account_credentials(account)
            session = await self._ensure_session()
            headers = self._build_headers(credentials.access_token, credentials.refresh_token)
            
            async with session.delete(
                f"{self.CLOB_URL}/order/{order_id}",
                headers=headers
            ) as response:
                if response.status == 200:
                    logger.info(f"Order cancelled: {order_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
            return False
    
    async def initialize_oauth(self, user: Any, environment: str) -> Dict[str, Any]:
        """OAuth not supported - use API key."""
        raise NotImplementedError("Polymarket uses API key authentication, not OAuth")
    
    async def initialize_api_key(
        self,
        user: Any,
        environment: str,
        credentials: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Initialize API key connection."""
        try:
            account = await self.connect_account(
                user=user,
                account_id=credentials.get("wallet_address", "polymarket"),
                environment=BrokerEnvironment(environment),
                credentials=credentials
            )
            
            return {
                "success": True,
                "account_id": account.id,
                "message": "Polymarket account connected successfully"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    # Helper methods
    def _build_headers(self, api_key: str, api_secret: str) -> Dict[str, str]:
        """Build authorization headers for Polymarket API."""
        return {
            "Authorization": f"Bearer {api_key}",
            "POLY_API_KEY": api_key,
            "POLY_API_SECRET": api_secret,
            "Content-Type": "application/json"
        }
    
    async def _get_account_credentials(self, account: Any) -> Any:
        """Get credentials for an account."""
        from ....models.broker import BrokerCredentials
        
        credentials = self.db.query(BrokerCredentials).filter(
            BrokerCredentials.account_id == account.id
        ).first()
        
        if not credentials:
            raise AuthenticationError("No credentials found for account")
        
        return credentials
    
    def normalize_position_response(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Polymarket position to standard format."""
        return {
            "symbol": raw.get("assetId", raw.get("tokenId", "")),
            "side": raw.get("side", "BUY"),
            "quantity": float(raw.get("size", 0)),
            "entry_price": float(raw.get("avgPrice", 0)),
            "current_price": float(raw.get("curPrice", raw.get("avgPrice", 0))),
            "unrealized_pnl": float(raw.get("pnl", 0)),
            "realized_pnl": 0.0,
            "market_id": raw.get("conditionId"),
            "updated_at": datetime.utcnow().isoformat()
        }
    
    def normalize_order_response(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Polymarket order to standard format."""
        return {
            "order_id": raw.get("orderID", raw.get("id", "")),
            "status": raw.get("status", "OPEN"),
            "symbol": raw.get("assetId", raw.get("tokenID", "")),
            "side": raw.get("side", ""),
            "quantity": float(raw.get("size", raw.get("originalSize", 0))),
            "filled_quantity": float(raw.get("sizeFilled", 0)),
            "price": float(raw.get("price", 0)),
            "created_at": raw.get("timestamp", datetime.utcnow().isoformat())
        }
    
    # Market data methods (for convenience)
    async def get_markets(self, search: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get available markets."""
        try:
            session = await self._ensure_session()
            params = {"active": "true"}
            if search:
                params["search"] = search
            
            async with session.get(f"{self.GAMMA_URL}/markets", params=params) as response:
                if response.status == 200:
                    return await response.json()
                return []
                
        except Exception as e:
            logger.error(f"Get markets error: {e}")
            return []
    
    async def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """Get order book for a token."""
        try:
            session = await self._ensure_session()
            
            async with session.get(
                f"{self.CLOB_URL}/book",
                params={"token_id": token_id}
            ) as response:
                if response.status == 200:
                    return await response.json()
                return {"bids": [], "asks": []}
                
        except Exception as e:
            logger.error(f"Get orderbook error: {e}")
            return {"bids": [], "asks": []}
