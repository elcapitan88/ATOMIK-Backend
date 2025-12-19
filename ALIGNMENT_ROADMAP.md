# Trust Infrastructure Alignment Roadmap

This document tracks the implementation of Atomik's trust and verification system, enabling transparent, verifiable trading strategy performance on the marketplace.

---

## Phase 1: Trust Foundation (COMPLETED)

### Phase 1.1: Cryptographic Strategy Hashing
- [x] Add hash columns to `strategy_codes` table (`code_hash`, `config_hash`, `combined_hash`)
- [x] Add `locked_at` timestamp for immutability tracking
- [x] Add `parent_strategy_id` for version lineage
- [x] Create `StrategyHashService` for hash generation/verification
- [x] Create unique index on `combined_hash`

### Phase 1.2: User Mode Separation
- [x] Create `user_mode_enum` PostgreSQL enum
- [x] Add `user_mode` column to users table (subscriber/private_creator/public_creator)
- [x] Create permission decorators (`@require_creator_mode`, `@require_public_creator`)
- [x] Migrate existing users based on creator status

### Phase 1.3: Trade Version Tracking
- [x] Add `strategy_version_id` to trades table (links to StrategyCode)
- [x] Add `execution_environment` enum (live/paper/backtest)
- [x] Add `is_verified_live` flag for broker-verified trades
- [x] Add live performance columns to `strategy_codes` (`live_total_trades`, `live_winning_trades`, `live_total_pnl`, `live_win_rate`)
- [x] Update `TradeService.close_trade()` to aggregate performance on strategy
- [x] Create `/publish` endpoint that auto-locks on marketplace publish

### Phase 1.4: Public Verification API
- [x] Create `/api/v1/public/verify/{hash}` endpoint (no auth required)
- [x] Return strategy name, creator, locked date, performance metrics

---

## Phase 2: Frontend Trust Display (COMPLETED)

### Phase 2.1: Backend - Creator Aggregate Metrics
**Goal:** Calculate and expose creator-level performance across all their strategies

**Approach:** Option B - Calculate on-the-fly (simple first, cache later if needed)

**Endpoints to create/modify:**
- [x] `GET /api/v1/creators/{username}/performance` - Aggregate performance across all published strategies
- [x] Modify marketplace strategies response to include performance data
- [x] Modify creator profile response to include aggregate stats

**Data to expose (per strategy):**
```json
{
  "live_total_trades": 47,
  "live_winning_trades": 32,
  "live_total_pnl": 2340.50,
  "live_win_rate": 68.09,
  "combined_hash": "abc123...",
  "locked_at": "2025-12-17T15:42:00Z",
  "is_locked": true
}
```

**Data to expose (per creator - aggregate):**
```json
{
  "published_strategies_count": 3,
  "total_live_trades": 156,
  "total_live_pnl": 8420.75,
  "aggregate_win_rate": 71.2,
  "total_subscribers": 412
}
```

### Phase 2.2: Frontend - Enhanced Strategy Cards
**Goal:** Display trust indicators on strategy cards in marketplace and creator profile

**Changes to StrategyCard component:**
- [x] Add trade count display (e.g., "47 trades")
- [x] Add win rate display (e.g., "68% win")
- [x] Add verification hash badge (clickable, shows first 8 chars)
- [x] Add lock icon for published/immutable strategies
- [x] Show PnL indicator (optional, +/- color coded)

**Visual mockup:**
```
┌─────────────────────────────────┐
│  Strategy Name                  │
│  by @creator                    │
│                                 │
│  📈 47 trades • 68% win         │  ← Trust metrics
│  🔒 #abc123de                   │  ← Hash badge
│                                 │
│  ⭐ 4.5  •  128 subscribers     │
│  [Subscribe]                    │
└─────────────────────────────────┘
```

### Phase 2.3: Frontend - Strategy Detail Modal
**Goal:** Full verification and performance info when clicking a strategy card

**Modal content:**
- [x] Strategy name, creator, verified badge
- [x] Strategy-level performance metrics (trades, win rate, PnL, locked date)
- [x] Verification hash with copy/share buttons
- [x] Creator track record summary (aggregate across all strategies)
- [x] Link to full creator profile
- [x] Subscribe/Purchase CTA

**Location:** Click any strategy card (marketplace or creator profile)

### Phase 2.4: Frontend - Creator Profile Enhancement
**Goal:** Display creator-level aggregate performance in profile header

**Changes to ProfileHeader component:**
- [x] Add "Creator Performance" section
- [x] Show aggregate stats: strategies published, total trades, overall win rate, total PnL
- [x] Make individual strategy cards show their own metrics

---

## Phase 3: Public Verification Page (FUTURE)

### Phase 3.1: `/verify/{hash}` Frontend Page
- [ ] Create standalone public page at `/verify/{hash}`
- [ ] No authentication required
- [ ] Shows: strategy name, creator, locked date, performance, hash verification status
- [ ] Link to marketplace/creator profile for more info
- [ ] Shareable on social media for credibility

---

## Phase 4: Creator Onboarding (FUTURE)

### Phase 4.1: Mode Upgrade Flow
- [ ] Create `/creator-onboarding` page
- [ ] Step 1: Accept creator terms
- [ ] Step 2: Verify identity (optional for public creators)
- [ ] Step 3: Complete profile
- [ ] Auto-upgrade user_mode on completion

---

## Technical Notes

### Database Schema Changes (Phase 1 - Completed)
```sql
-- strategy_codes additions
code_hash VARCHAR(64)
config_hash VARCHAR(64)
combined_hash VARCHAR(64) UNIQUE
locked_at TIMESTAMP
parent_strategy_id INT REFERENCES strategy_codes(id)
live_total_trades INT DEFAULT 0
live_winning_trades INT DEFAULT 0
live_total_pnl DECIMAL(12,2) DEFAULT 0
live_win_rate DECIMAL(5,2) DEFAULT 0
live_first_trade_at TIMESTAMP
live_last_trade_at TIMESTAMP

-- users additions
user_mode user_mode_enum DEFAULT 'subscriber'

-- trades additions
strategy_version_id INT REFERENCES strategy_codes(id)
execution_environment exec_env_enum DEFAULT 'live'
is_verified_live BOOLEAN DEFAULT false
```

### Key Files Modified (Phase 1)
- `alembic/versions/20251217_phase1_trust_foundation.py` - Migration
- `app/models/user.py` - UserMode enum, user_mode column
- `app/models/strategy_code.py` - Hash fields, performance tracking
- `app/models/trade.py` - Version linking, execution environment
- `app/services/strategy_hash_service.py` - Hash generation/verification
- `app/services/trade_service.py` - Performance aggregation on trade close
- `app/api/v1/endpoints/strategy_codes.py` - Lock, publish, version endpoints
- `app/api/v1/endpoints/public_verification.py` - Public hash lookup
- `app/core/permissions.py` - User mode decorators

### Key Files to Modify (Phase 2)
- `app/api/v1/endpoints/creator_profiles.py` - Add aggregate metrics
- `app/api/v1/endpoints/marketplace.py` - Include performance in response
- `frontend/src/components/features/marketplace/components/StrategyCard.js`
- `frontend/src/components/pages/CreatorProfile/components/ProfileHeader.js`
- `frontend/src/components/features/marketplace/components/StrategyDetailModal.js` (NEW)

---

## Commits Made

| Date | Commit | Description |
|------|--------|-------------|
| 2025-12-17 | `f779ead` | Phase 1.3: Auto-lock on marketplace publish + trade performance tracking |
| 2025-12-17 | `f4869f9` | Phase 1: Trust Foundation infrastructure |
| 2025-12-17 | `ab5f490` | Fix enum value mismatch for user_mode and execution_environment |
| 2025-12-18 | - | Phase 2.1: Backend creator aggregate metrics endpoints |
| 2025-12-18 | - | Phase 2.2: StrategyCard trust metrics display |
| 2025-12-18 | - | Phase 2.3: StrategyDetailModal component |
| 2025-12-18 | - | Phase 2.4: ProfileHeader verified performance section |
