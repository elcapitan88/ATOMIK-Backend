# Stripe Webhook Improvements - Implementation Guide

## Summary

This document outlines the improvements made to handle Stripe webhook failures and prevent issues like User 188's missing purchase record.

## Problem Identified

User 188 had an active Stripe subscription (`sub_1SF1pyD3oMVy2RzcxMz5WaBQ`) but couldn't access the Break and Enter strategy because:
- The Stripe webhook failed to create a `strategy_purchases` record
- Without this record, the system didn't know the user had paid
- The user couldn't see or activate the strategy

## Solutions Implemented

### 1. Immediate Fix (Completed ✅)

Created purchase record for User 188:
```sql
INSERT INTO strategy_purchases (
    user_id, webhook_id, pricing_id, amount_paid, status,
    stripe_payment_intent_id, stripe_subscription_id,
    purchase_type, platform_fee, creator_payout
) VALUES (
    188, 117, 'b3293832-7f49-4307-a4e0-60a63b784bdc', 29.99, 'active',
    'manual_fix_sub_1SF1pyD3oMVy2RzcxMz5WaBQ',
    'sub_1SF1pyD3oMVy2RzcxMz5WaBQ',
    'subscription', 4.50, 25.49
);
```

User 188 can now see and activate Break and Enter strategy.

### 2. Webhook Retry Logic

**File:** `app/services/stripe_webhook_service.py`

Features:
- Logs all webhook events to `stripe_webhook_logs` table
- Automatically retries failed webhooks (up to 3 times)
- Exponential backoff (5 min, 10 min, 15 min)
- Prevents duplicate processing

### 3. Reconciliation Service

**File:** `app/services/stripe_reconciliation_service.py`

Features:
- Compares Stripe subscriptions with database records
- Automatically creates missing purchase records
- Sends alerts for issues that can't be auto-fixed
- Can check specific users

### 4. Background Tasks

**File:** `app/tasks/stripe_tasks.py`
**Scheduler:** `app/core/scheduler.py`

Schedule:
- Retry failed webhooks: Every 15 minutes
- Reconcile subscriptions: Every 6 hours
- Health checks: Every hour

### 5. Admin Endpoints

**File:** `app/api/v1/endpoints/admin/stripe_admin.py`

Endpoints:
- `GET /admin/stripe/webhook-logs` - View webhook processing history
- `POST /admin/stripe/retry-webhooks` - Manually trigger webhook retry
- `POST /admin/stripe/reconcile` - Manually trigger reconciliation
- `GET /admin/stripe/check-user/{user_id}` - Check specific user
- `POST /admin/stripe/fix-user/{user_id}` - Fix specific user
- `GET /admin/stripe/subscription-health` - Overall health metrics

### 6. Database Changes

**Migration:** `alembic/versions/add_stripe_webhook_logs.py`

New table: `stripe_webhook_logs`
- Tracks all webhook events
- Stores errors and retry information
- Enables monitoring and debugging

## Integration Steps

### 1. Run Database Migration
```bash
cd fastapi_backend
alembic upgrade head
```

### 2. Update Main Application

In `main.py`, add:
```python
from app.core.scheduler import setup_scheduler, shutdown_scheduler
from app.api.v1.endpoints.admin import stripe_admin

# In startup
@app.on_event("startup")
async def startup():
    setup_scheduler()

# In shutdown
@app.on_event("shutdown")
async def shutdown():
    shutdown_scheduler()

# Add admin routes
app.include_router(stripe_admin.router, prefix="/api/v1")
```

### 3. Update Webhook Handler

Replace existing webhook handler with:
```python
from app.services.stripe_webhook_service import StripeWebhookService

@router.post("/stripe-webhook")
async def handle_webhook(
    request: Request,
    db: Session = Depends(get_db)
):
    payload = await request.body()
    signature = request.headers.get('stripe-signature')

    service = StripeWebhookService(db)
    result = await service.process_webhook(payload, signature)

    return result
```

### 4. Install Required Packages
```bash
pip install apscheduler
```

## Monitoring

### Health Check Dashboard

Access `/admin/stripe/subscription-health` to see:
- Health score (0-100)
- Failed webhooks count
- Missing purchase records
- Orphaned purchases

### Alert Conditions

System will alert when:
- Health score < 80
- Failed webhooks > 5
- Missing purchase records found during reconciliation

## Testing

### Test Webhook Retry
```python
# Simulate webhook failure
curl -X POST /admin/stripe/retry-webhooks
```

### Test User Check
```python
# Check specific user
curl /admin/stripe/check-user/188
```

### Test Reconciliation
```python
# Run full reconciliation
curl -X POST /admin/stripe/reconcile
```

## Prevention Measures

1. **Idempotency:** Webhooks can be safely retried without duplicates
2. **Logging:** All events logged for debugging
3. **Monitoring:** Regular health checks catch issues early
4. **Auto-healing:** Reconciliation fixes most issues automatically
5. **Manual tools:** Admin endpoints for edge cases

## Future Improvements

1. Add Slack/Discord notifications for critical issues
2. Create dashboard UI for webhook monitoring
3. Add metrics to track webhook success rate
4. Implement webhook replay from Stripe API
5. Add automated tests for webhook scenarios

## Support

If a user reports access issues:

1. Check their subscription:
   ```
   GET /admin/stripe/check-user/{user_id}
   ```

2. If missing purchase record, fix it:
   ```
   POST /admin/stripe/fix-user/{user_id}
   {
     "stripe_subscription_id": "sub_xxx",
     "webhook_id": 117
   }
   ```

3. Run reconciliation to catch other issues:
   ```
   POST /admin/stripe/reconcile
   ```

## Conclusion

These improvements ensure:
- User 188 and similar cases are automatically detected and fixed
- Webhook failures don't block user access
- Administrators have visibility and control
- System self-heals from most issues

The system is now resilient to Stripe webhook failures and can recover automatically.