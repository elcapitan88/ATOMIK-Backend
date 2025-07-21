# Endpoint Rollout Plan

## Strategy: Incremental Deployment

We'll add endpoints one by one to identify which one causes failures.

## Current Status: ✅ WORKING
- auth ✅
- broker ✅  
- subscription ✅
- webhooks ✅
- strategy ✅
- tradovate ✅
- binance ✅
- futures_contracts ✅
- admin ✅
- creators ✅

## Endpoints to Add (Priority Order):

### 1. chat endpoint (HIGH PRIORITY)
- **Why first**: Chat is a core user feature
- **Dependencies**: chat.py, chat_role_service.py, chat models/schemas
- **Risk**: LOW - well established functionality

### 2. feature_flags endpoint (MEDIUM PRIORITY)  
- **Why**: Controls feature rollouts
- **Dependencies**: feature_flag_service.py
- **Risk**: LOW - simple service

### 3. marketplace endpoint (HIGH PRIORITY)
- **Why**: Core monetization feature
- **Dependencies**: marketplace_service.py, stripe_connect_service.py
- **Risk**: MEDIUM - complex Stripe integration

### 4. interactivebrokers endpoint (MEDIUM PRIORITY)
- **Why**: Important broker integration
- **Dependencies**: digital_ocean_server_manager.py, permissions.py
- **Risk**: HIGH - most complex, just fixed merge conflicts

## Rollout Process:

1. Add ONE endpoint to imports
2. Deploy and test login
3. If successful, move to next
4. If failed, investigate that specific endpoint's dependencies
5. Document the issue and fix before proceeding

## Testing Commands:
```bash
# Test basic API health
curl -s https://api.atomiktrading.io/health

# Test auth endpoint specifically  
curl -s https://api.atomiktrading.io/api/v1/auth/me

# Test new endpoint after adding
curl -s https://api.atomiktrading.io/api/v1/[ENDPOINT]/[PATH]
```

## Dependencies We Know Work:
- ✅ stripe (in requirements.txt)
- ✅ database models and schemas exist
- ✅ services exist

## Dependencies That May Cause Issues:
- ❓ digital_ocean_server_manager (complex external service)
- ❓ Complex service interdependencies
- ❓ Missing environment variables in production