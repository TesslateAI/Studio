# Stripe/Payments Full Rebuild - UX Priority

## Executive Summary

**PRIORITY ORDER:**
1. **Part B: UX & Tier Restructuring** (DO FIRST) - Complete rebuild of billing system
2. **Part A: Security Fixes** (16 vulnerabilities) - Apply after UX is working

### Core Principle
**Consolidate ALL billing into `/settings/billing` only.** Remove billing from everywhere else (Library, standalone `/billing/*` routes).

### Theme Compliance (CRITICAL)
All components MUST use the existing theme system:
- CSS variables: `var(--primary)`, `var(--surface)`, `var(--text)`, etc.
- Use existing `SettingsSection`, `SettingsGroup`, `SettingsItem` components
- NO hardcoded colors (current billing uses `bg-gray-50` - must fix)
- Follow patterns in `app/src/components/settings/`

---

## Part B: New Tier Structure & UX Changes

### New Pricing Tiers
| Tier | Price | Projects | Monthly Credits | BYOK |
|------|-------|----------|-----------------|------|
| **Free** | $0 | 3 | 1000 credits ($10) | ❌ |
| **Basic** | $8/mo | 5 | 1000 credits ($10) | ❌ |
| **Pro** | $20/mo | 10 | 2500 credits ($25) | ✅ |
| **Ultra** | $100/mo | Unlimited | 12000 credits ($120) | ✅ |

### Credit System Changes
- **Display**: 1 credit = $0.01 (show "1847 credits" not "$18.47")
- **Bundled credits**: Reset monthly on billing date
- **Purchased credits**: Never expire
- **Marketplace**: Open to ALL tiers (just need credits)

### UX Changes Required
1. **Unified Billing Hub** at `/settings/billing` (consolidate ALL billing here)
2. **Remove billing from Library** tabs (no more `/library?tab=credits`)
3. **Remove standalone `/billing/*` routes** (BillingDashboard, UsageDashboard, etc.)
4. **Low balance warning** at 20% threshold
5. **Out of credits modal** with upgrade options
6. **BYOK restriction** to Pro+ tiers only
7. **Update credit display** to show credits not dollars (header display already exists)

### Theme System Compliance
All new components must use CSS variables from `app/src/theme/themePresets.ts`:

```css
/* Colors */
var(--primary), var(--primary-hover)    /* CTAs, active states */
var(--bg), var(--surface)               /* Backgrounds */
var(--text), var(--text-muted)          /* Typography */
var(--border)                           /* Subtle borders */
var(--status-success/warning/error)     /* Status indicators */

/* Common Patterns */
bg-[var(--surface)]                     /* Card backgrounds */
border border-white/10                  /* Subtle borders */
text-[var(--text)]                      /* Primary text */
text-[var(--text)]/50                   /* Muted text (50% opacity) */
hover:bg-white/[0.02]                   /* Hover states */
rounded-xl                              /* Card radius */
```

### Existing Components to Use
- `SettingsSection` - Page wrapper with max-width
- `SettingsGroup` - Grouped settings with header
- `SettingsItem` - Individual setting row

---

## Part A: Security Review Summary

The system handles:
- **Subscriptions** (Free/Basic/Pro/Ultra)
- **Credit purchases** ($5/500, $10/1000 packages)
- **Marketplace agent purchases** (one-time, monthly, API-based pricing)
- **Deploy slot purchases** ($10 each)
- **Creator payouts** via Stripe Connect (90/10 revenue split)
- **Usage-based billing** via LiteLLM token tracking

**Finding:** 16 vulnerabilities identified (4 critical, 6 high, 4 medium, 2 low). The system uses Stripe Checkout (redirect-based) which is architecturally sound for PCI compliance, but webhook handling and database transactions have significant race conditions and idempotency gaps.

---

## Architecture Overview

### Payment Flow
```
Frontend                    Backend                         Stripe
   │                           │                              │
   ├─→ billingApi.subscribe() ─┼─→ create_checkout_session ──→│
   │                           │←── session.url ──────────────┤
   │←── redirect to Stripe ────┤                              │
   │                           │                    [User pays]
   │                           │←── POST /webhooks/stripe ────┤
   │                           │    (signature verified)       │
   │                           │    update user tier/credits   │
   │←── redirect success.html ─┤                              │
```

### Revenue Models (Updated)
| Type | Price | Creator Share | Platform Share |
|------|-------|---------------|----------------|
| Free Tier | $0/month | N/A | N/A |
| Basic Tier | $8/month | N/A | 100% |
| Pro Tier | $20/month | N/A | 100% |
| Ultra Tier | $100/month | N/A | 100% |
| Credit Packages | $5/500, $10/1000 | N/A | 100% |
| Marketplace Agent (monthly) | Creator sets | 90% | 10% |
| Marketplace Agent (one-time) | Creator sets | 90% | 10% |
| Marketplace Agent (API) | Per-token | 90% | 10% |
| Deploy Slot | $10 | N/A | 100% |

### Key Files
| File | Lines | Purpose |
|------|-------|---------|
| [stripe_service.py](orchestrator/app/services/stripe_service.py) | 970 | Core payment logic, webhook handlers |
| [billing.py](orchestrator/app/routers/billing.py) | 703 | Billing API endpoints |
| [webhooks.py](orchestrator/app/routers/webhooks.py) | 53 | Webhook router |
| [marketplace.py](orchestrator/app/routers/marketplace.py) | 2417 | Marketplace purchases |
| [models.py](orchestrator/app/models.py) | - | CreditPurchase, MarketplaceTransaction, UsageLog |
| [models_auth.py](orchestrator/app/models_auth.py) | - | User.subscription_tier, credits_balance |
| [config.py](orchestrator/app/config.py) | - | Stripe keys, pricing config |

### Database Models (Payment-Related)
- **User**: `stripe_customer_id`, `stripe_subscription_id`, `subscription_tier`, `credits_balance`, `total_spend`, `creator_stripe_account_id`
- **CreditPurchase**: `user_id`, `amount_cents`, `stripe_payment_intent` (unique), `status`
- **MarketplaceTransaction**: `user_id`, `agent_id`, `creator_id`, `amount_total`, `amount_creator`, `amount_platform`, `payout_status`
- **UserPurchasedAgent**: `user_id`, `agent_id`, `purchase_type`, `stripe_subscription_id`, `is_active`
- **UsageLog**: `user_id`, `agent_id`, `cost_total`, `creator_revenue`, `platform_revenue`, `billed_status`

---

## All Vulnerabilities (Complete List)

### CRITICAL SEVERITY

#### 1. Premium Subscription - NO Idempotency Check
**Location:** [stripe_service.py:758-772](orchestrator/app/services/stripe_service.py#L758-L772)

```python
# CURRENT (VULNERABLE):
async def _handle_premium_subscription_checkout(self, session, db):
    user_id = UUID(session["metadata"]["user_id"])
    subscription_id = session.get("subscription")
    user = user_result.scalar_one()
    user.subscription_tier = "pro"  # No check if already "pro"!
    user.stripe_subscription_id = subscription_id  # Overwrites existing!
    await db.commit()
```

**Attack:** Webhook replay → overwrites subscription_id → user has multiple subscriptions, only one tracked.

**Fix Required:**
```python
# Check if already processed
if user.subscription_tier == "pro" and user.stripe_subscription_id == subscription_id:
    logger.info(f"Premium subscription already processed for user {user_id}")
    return
# Also check if subscription_id already exists (different user attack)
existing = await db.execute(
    select(User).where(User.stripe_subscription_id == subscription_id)
)
if existing.scalar_one_or_none():
    logger.warning(f"Subscription {subscription_id} already assigned to another user")
    return
```

---

#### 2. Deploy Slot Purchase - NO Idempotency
**Location:** [stripe_service.py:880-896](orchestrator/app/services/stripe_service.py#L880-L896)

```python
# CURRENT (VULNERABLE):
async def _handle_deploy_purchase_checkout(self, session, db):
    user.total_spend += session["amount_total"]  # No duplicate check!
    await db.commit()
```

**Attack:** Replay webhook → user gets unlimited deploy slots for price of one.

**Fix Required:** Create `DeploySlotPurchase` model and add idempotency:
```python
# New model needed in models.py:
class DeploySlotPurchase(Base):
    __tablename__ = "deploy_slot_purchases"
    id = Column(UUID, primary_key=True, default=uuid4)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    stripe_payment_intent = Column(String, unique=True, nullable=False, index=True)
    stripe_checkout_session = Column(String)
    status = Column(String, default="completed")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Then in handler:
existing = await db.execute(
    select(DeploySlotPurchase).where(
        DeploySlotPurchase.stripe_checkout_session == session["id"]
    )
)
if existing.scalar_one_or_none():
    logger.info(f"Deploy slot purchase already processed: {session['id']}")
    return
```

---

#### 3. Credit Purchase - Race Condition
**Location:** [stripe_service.py:780-808](orchestrator/app/services/stripe_service.py#L780-L808)

```python
# CURRENT (VULNERABLE - race between check and insert):
existing = await db.execute(select(CreditPurchase).where(...))
if existing.scalar_one_or_none():
    return  # Idempotency check
# GAP: Between check and insert, duplicate webhook can slip through
db.add(purchase)
user.credits_balance += amount_cents
await db.commit()
```

**Fix Required:** Use `SELECT ... FOR UPDATE` or handle unique constraint violation:
```python
from sqlalchemy.exc import IntegrityError

try:
    # Lock user row for update
    user_result = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_result.scalar_one()

    purchase = CreditPurchase(...)
    db.add(purchase)
    user.credits_balance += amount_cents
    user.total_spend += amount_cents
    await db.commit()
except IntegrityError:
    await db.rollback()
    logger.info(f"Credit purchase already processed (constraint): {payment_intent}")
    return
```

---

#### 4. Agent Purchase - Incomplete Idempotency
**Location:** [stripe_service.py:819-828](orchestrator/app/services/stripe_service.py#L819-L828)

```python
# CURRENT (VULNERABLE):
existing = await db.execute(
    select(UserPurchasedAgent).where(
        UserPurchasedAgent.user_id == user_id,
        UserPurchasedAgent.agent_id == agent_id
    )
)
if existing.scalar_one_or_none():
    return  # Blocks re-purchase but loses new subscription_id
```

**Problem:** If user re-subscribes to same agent (e.g., after cancellation), the new subscription_id is lost.

**Fix Required:** Check by payment_intent or session_id instead:
```python
existing = await db.execute(
    select(UserPurchasedAgent).where(
        UserPurchasedAgent.stripe_payment_intent == payment_intent
    )
)
if existing.scalar_one_or_none():
    logger.info(f"Agent purchase already processed: {payment_intent}")
    return

# For re-subscription, update existing record:
existing_purchase = await db.execute(
    select(UserPurchasedAgent).where(
        UserPurchasedAgent.user_id == user_id,
        UserPurchasedAgent.agent_id == agent_id
    )
)
if existing_record := existing_purchase.scalar_one_or_none():
    existing_record.stripe_subscription_id = subscription_id
    existing_record.is_active = True
    existing_record.purchase_date = datetime.now(timezone.utc)
else:
    # Create new purchase record
    ...
```

---

### HIGH SEVERITY

#### 5. Webhook Returns 400 on Failure
**Location:** [webhooks.py:45-50](orchestrator/app/routers/webhooks.py#L45-L50)

```python
# CURRENT (PROBLEMATIC):
if not result.get("success"):
    raise HTTPException(status_code=400, ...)  # Stripe retries forever!
```

**Fix Required:** Always return 200, log errors internally:
```python
@router.post("/stripe")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not sig_header:
        logger.error("Missing Stripe signature header")
        return {"received": True, "error": "Missing signature"}  # Still 200!

    result = await stripe_service.handle_webhook(payload, sig_header, db)

    if not result.get("success"):
        logger.error(f"Webhook processing failed: {result.get('message')}")
        # Still return 200 - Stripe best practice

    return {"received": True}
```

---

#### 6. No Rate Limiting on Purchase Endpoints
**Location:** [billing.py](orchestrator/app/routers/billing.py) - multiple endpoints

**Fix Required:** Add rate limiting dependency:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/subscribe")
@limiter.limit("5/minute")
async def create_subscription_checkout(...):
    ...

@router.post("/credits/purchase")
@limiter.limit("10/minute")
async def create_credit_purchase_checkout(...):
    ...
```

---

#### 7. Origin Header Not Validated
**Location:** [billing.py:178, 302, 368](orchestrator/app/routers/billing.py#L178)

```python
# CURRENT (VULNERABLE):
origin = request.headers.get("origin", settings.frontend_url)
success_url = f"{origin}/billing/success"  # Open redirect!
```

**Fix Required:**
```python
ALLOWED_ORIGINS = {settings.frontend_url, "http://localhost:5173", "http://localhost:3000"}

def get_safe_origin(request: Request) -> str:
    origin = request.headers.get("origin")
    if origin and origin in ALLOWED_ORIGINS:
        return origin
    return settings.frontend_url

# Usage:
origin = get_safe_origin(request)
success_url = f"{origin}/billing/success"
```

---

#### 8. No Stripe Transfer Idempotency Key
**Location:** [stripe_service.py:660-680](orchestrator/app/services/stripe_service.py#L660-L680)

```python
# CURRENT (VULNERABLE):
transfer = self.stripe.Transfer.create(
    amount=transaction.amount_creator,
    currency="usd",
    destination=creator.creator_stripe_account_id,
    # No idempotency_key!
)
```

**Fix Required:**
```python
transfer = self.stripe.Transfer.create(
    amount=transaction.amount_creator,
    currency="usd",
    destination=creator.creator_stripe_account_id,
    idempotency_key=f"transfer_{transaction.id}",  # Use transaction ID
    metadata={
        "transaction_id": str(transaction.id),
        "agent_id": str(transaction.agent_id),
    }
)
```

---

#### 9. Non-Atomic Credit Purchase (Multiple Commits)
**Location:** [stripe_service.py:789-808](orchestrator/app/services/stripe_service.py#L789-L808)

The current code does multiple database operations but they should be atomic.

**Fix Required:** Ensure single transaction:
```python
async def _handle_credit_purchase_checkout(self, session, db):
    # All operations in same transaction block
    user_id = UUID(session["metadata"]["user_id"])
    amount_cents = int(session["metadata"]["amount_cents"])
    payment_intent = session.get("payment_intent")

    # Lock user row
    user_result = await db.execute(
        select(User).where(User.id == user_id).with_for_update()
    )
    user = user_result.scalar_one()

    purchase = CreditPurchase(
        user_id=user_id,
        amount_cents=amount_cents,
        credits_amount=amount_cents,
        stripe_payment_intent=payment_intent,
        stripe_checkout_session=session["id"],
        status="completed",
        completed_at=datetime.now(timezone.utc)
    )
    db.add(purchase)

    user.credits_balance += amount_cents
    user.total_spend += amount_cents

    await db.commit()  # Single commit for all changes
```

---

#### 10. Agent Purchase/Payout Not Atomic
**Location:** [stripe_service.py:830-878](orchestrator/app/services/stripe_service.py#L830-L878)

Current flow: insert purchase → insert transaction → commit → update user → commit → create payout

**Fix Required:** Single transaction with deferred payout:
```python
async def _handle_agent_purchase_checkout(self, session, db):
    # All DB operations atomic
    async with db.begin_nested():  # Savepoint
        purchase = UserPurchasedAgent(...)
        db.add(purchase)

        transaction = MarketplaceTransaction(...)
        db.add(transaction)

        user.total_spend += amount_total
        agent.downloads += 1

    await db.commit()  # Single commit

    # Payout is separate (external API call)
    # If payout fails, transaction record exists for retry
    if agent.created_by_user_id:
        try:
            await self.create_payout(transaction, db)
        except Exception as e:
            logger.error(f"Payout failed for transaction {transaction.id}: {e}")
            transaction.payout_status = "failed"
            await db.commit()
```

---

### MEDIUM SEVERITY

#### 11. Debug Print Statements in Production
**Location:** [billing.py:119-145](orchestrator/app/routers/billing.py#L119-L145)

```python
# CURRENT (LEAKS PII):
print(f"Stripe subscription: {stripe_sub}")
traceback.print_exc()
```

**Fix Required:** Replace with proper logging:
```python
logger.debug(f"Subscription status for user {current_user.id}")
logger.exception("Error fetching subscription")  # Logs traceback properly
```

---

#### 12. No Webhook Event Audit Table
**Problem:** No audit trail for webhook events - can't debug or replay.

**Fix Required:** Add WebhookEvent model:
```python
class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(UUID, primary_key=True, default=uuid4)
    stripe_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    payload = Column(JSON)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())
    status = Column(String, default="processed")  # processed, failed, skipped
    error_message = Column(String, nullable=True)
```

Then in webhook handler:
```python
# Check if already processed
existing = await db.execute(
    select(WebhookEvent).where(WebhookEvent.stripe_event_id == event["id"])
)
if existing.scalar_one_or_none():
    logger.info(f"Webhook event already processed: {event['id']}")
    return {"success": True, "message": "Already processed"}

# Record event
webhook_record = WebhookEvent(
    stripe_event_id=event["id"],
    event_type=event["type"],
    payload=event,
)
db.add(webhook_record)
```

---

#### 13. Credits Balance Can Go Negative
**Location:** Various places where credits are deducted

**Fix Required:** Add check before deduction:
```python
async def deduct_credits(user: User, amount: int, db: AsyncSession) -> bool:
    if user.credits_balance < amount:
        return False
    user.credits_balance -= amount
    await db.commit()
    return True
```

---

#### 14. Invoice Creation Missing Idempotency
**Location:** [stripe_service.py:543](orchestrator/app/services/stripe_service.py#L543)

**Fix Required:**
```python
invoice = self.stripe.Invoice.create(
    customer=user.stripe_customer_id,
    collection_method="send_invoice",
    days_until_due=7,
    idempotency_key=f"invoice_{user.id}_{billing_period}",
)
```

---

### LOW SEVERITY

#### 15. Redundant UNIQUE + INDEX
**Location:** [models.py:898](orchestrator/app/models.py#L898)

```python
stripe_payment_intent = Column(String, nullable=False, unique=True, index=True)
#                                                       ^^^^^^       ^^^^^
# unique=True already creates an index
```

**Fix:** Remove redundant `index=True`.

---

#### 16. Magic String Values Throughout
**Problem:** Status values like "free", "pro", "pending", "completed" hardcoded everywhere.

**Fix Required:** Use Enums:
```python
from enum import Enum

class SubscriptionTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"

class PaymentStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"
```

---

## Security Strengths (What's Good)

1. **Stripe webhook signature verification** - Properly implemented with `construct_event()`
2. **Redirect-based checkout** - No card data touches your servers (PCI compliant)
3. **Amounts in cents** - Avoids floating-point precision issues
4. **CSRF protection** - Properly configured with webhook exemption
5. **All endpoints authenticated** - `current_active_user` dependency on all billing routes
6. **Revenue split calculation** - Correct 90/10 math with integer arithmetic
7. **Customer isolation** - Each user has separate Stripe customer
8. **Stripe Connect for payouts** - Proper Express account flow

---

## Part B: UX Implementation Details

### B1. Database Schema Changes

**User model additions** (`models_auth.py`):
```python
# New tier values
subscription_tier: Mapped[str] = mapped_column(String, default="free")  # free, basic, pro, ultra

# Credit tracking (separate bundled vs purchased)
bundled_credits: Mapped[int] = mapped_column(Integer, default=1000)  # Monthly allowance
purchased_credits: Mapped[int] = mapped_column(Integer, default=0)   # Never expire
credits_reset_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

**Note**: Keep existing `credits_balance` as computed property: `bundled_credits + purchased_credits`

### B2. Config Changes

**New tier configuration** (`config.py`):
```python
# Tier pricing (cents)
tier_prices: dict = {
    "free": 0,
    "basic": 800,   # $8
    "pro": 2000,    # $20
    "ultra": 10000  # $100
}

# Monthly bundled credits per tier
tier_bundled_credits: dict = {
    "free": 1000,    # $10 worth
    "basic": 1000,   # $10 worth
    "pro": 2500,     # $25 worth
    "ultra": 12000   # $120 worth
}

# Project limits per tier
tier_max_projects: dict = {
    "free": 3,
    "basic": 5,
    "pro": 10,
    "ultra": 999  # Unlimited
}

# BYOK enabled tiers
byok_enabled_tiers: list = ["pro", "ultra"]

# Credit packages (credits, not cents)
credit_packages: dict = {
    "small": {"credits": 500, "price_cents": 500},   # $5 for 500 credits
    "medium": {"credits": 1000, "price_cents": 1000} # $10 for 1000 credits
}
```

### B3. Credit Display Logic

**Backend API changes** (`billing.py`):
```python
@router.get("/credits")
async def get_credits(current_user: User = Depends(current_active_user)):
    return {
        "bundled_credits": current_user.bundled_credits,
        "purchased_credits": current_user.purchased_credits,
        "total_credits": current_user.bundled_credits + current_user.purchased_credits,
        "credits_reset_date": current_user.credits_reset_date,
        "tier": current_user.subscription_tier,
        "monthly_allowance": settings.tier_bundled_credits[current_user.subscription_tier]
    }
```

**Frontend display** (show credits, not dollars):
```typescript
// Header component
<span>🎫 {credits.total_credits} credits</span>

// Settings billing page
<div>
  <h3>{credits.total_credits} credits remaining</h3>
  <p>(Resets to {credits.monthly_allowance} on {formatDate(credits.credits_reset_date)})</p>
</div>
```

### B4. Monthly Credit Reset Logic

**Scheduled task** (runs daily):
```python
async def reset_monthly_credits():
    """Reset bundled credits for users whose billing date has passed."""
    today = datetime.now(timezone.utc)

    # Find users with past reset dates
    users = await db.execute(
        select(User).where(
            User.credits_reset_date <= today,
            User.subscription_tier != "free"  # Free users reset immediately on signup
        )
    )

    for user in users.scalars():
        tier_credits = settings.tier_bundled_credits[user.subscription_tier]
        user.bundled_credits = tier_credits
        user.credits_reset_date = today + timedelta(days=30)  # Next month

    await db.commit()
```

### B5. BYOK Restriction (Pro+ Only)

**API key creation** (`routers/api_keys.py`):
```python
@router.post("/api-keys")
async def create_api_key(
    request: CreateAPIKeyRequest,
    current_user: User = Depends(current_active_user),
    db: AsyncSession = Depends(get_db)
):
    # Check tier
    if current_user.subscription_tier not in settings.byok_enabled_tiers:
        raise HTTPException(
            status_code=403,
            detail="BYOK (Bring Your Own Key) is only available for Pro and Ultra tiers"
        )
    # ... rest of creation logic
```

**Frontend**: Show upgrade prompt for Free/Basic users trying to access API Keys settings.

### B6. Low Balance Warning (20% threshold)

**Backend endpoint**:
```python
@router.get("/credits/status")
async def get_credit_status(current_user: User = Depends(current_active_user)):
    total = current_user.bundled_credits + current_user.purchased_credits
    monthly = settings.tier_bundled_credits[current_user.subscription_tier]
    threshold = int(monthly * 0.2)  # 20%

    return {
        "total_credits": total,
        "is_low": total <= threshold and total > 0,
        "is_empty": total <= 0,
        "threshold": threshold
    }
```

**Frontend component** (`LowBalanceWarning.tsx`):
```tsx
const LowBalanceWarning = () => {
  const { data: status } = useQuery(['creditStatus'], billingApi.getCreditStatus);

  if (!status?.is_low) return null;

  return (
    <Alert variant="warning">
      <AlertTitle>⚠️ Low Credits</AlertTitle>
      <p>You have {status.total_credits} credits remaining.</p>
      <div className="flex gap-2">
        <Button onClick={() => navigate('/settings/billing')}>Add Credits</Button>
        <Button variant="outline" onClick={() => navigate('/settings/billing')}>Upgrade Plan</Button>
      </div>
    </Alert>
  );
};
```

### B7. Out of Credits Modal

**Frontend component** (`OutOfCreditsModal.tsx`):
```tsx
const OutOfCreditsModal = ({ open, onClose }) => {
  const { data: subscription } = useQuery(['subscription'], billingApi.getSubscription);
  const daysUntilReset = calculateDaysUntil(subscription?.credits_reset_date);

  return (
    <Modal open={open} onClose={onClose}>
      <h2>🎫 Out of Credits</h2>
      <p>You've used all your credits.</p>

      <div className="options">
        <Button onClick={() => purchaseCredits('small')}>
          Add 500 credits ($5)
        </Button>
        <Button onClick={() => purchaseCredits('medium')}>
          Add 1000 credits ($10)
        </Button>
        <Button onClick={() => navigate('/settings/billing')}>
          Upgrade Plan
        </Button>
        {subscription?.tier !== 'free' && (
          <p className="text-muted">
            Or wait {daysUntilReset} days until credits reset
          </p>
        )}
      </div>
    </Modal>
  );
};
```

### B8. Unified Billing Hub (`/settings/billing`)

**Structure** (using existing Settings components):
```
/settings/billing (BillingSettings.tsx)
├── SettingsSection
│   ├── SettingsGroup title="Plan & Credits"
│   │   ├── Plan card with tier badge + [Change Plan]
│   │   ├── Credits display: "1847 credits remaining"
│   │   ├── Reset info: "(Resets to 2500 on Feb 15)"
│   │   └── [Add Credits] button
│   │
│   ├── SettingsGroup title="API Keys" (Pro+ badge or upgrade prompt)
│   │   ├── IF Pro/Ultra: Show API key management
│   │   └── IF Free/Basic: Show upgrade prompt
│   │
│   ├── SettingsGroup title="Usage History"
│   │   ├── Inline usage table (not separate page)
│   │   ├── Date range filter
│   │   └── Export button
│   │
│   └── SettingsGroup title="Transaction History"
│       ├── Inline transaction table
│       ├── Pagination
│       └── Export button
```

**Theme-Compliant Implementation**:
```tsx
// BillingSettings.tsx
import { SettingsSection, SettingsGroup, SettingsItem } from '@/components/settings';

export default function BillingSettings() {
  return (
    <SettingsSection>
      {/* Plan & Credits */}
      <SettingsGroup
        title="Plan & Credits"
        description="Manage your subscription and credits"
      >
        {/* Plan Card - uses theme colors */}
        <div className="bg-[var(--surface)] border border-white/10 rounded-xl p-6">
          <div className="flex justify-between items-center">
            <div>
              <span className="text-[var(--text)]/50 text-sm">Current Plan</span>
              <h3 className="text-2xl font-bold text-[var(--text)]">Pro</h3>
            </div>
            <Button variant="secondary">Change Plan</Button>
          </div>

          {/* Credits Display */}
          <div className="mt-6 pt-6 border-t border-white/10">
            <div className="flex items-center gap-2">
              <span className="text-3xl font-bold text-[var(--text)]">1847</span>
              <span className="text-[var(--text)]/50">credits remaining</span>
            </div>
            <p className="text-sm text-[var(--text)]/40 mt-1">
              Resets to 2,500 on Feb 15
            </p>
            <Button className="mt-4" variant="primary">Add Credits</Button>
          </div>
        </div>
      </SettingsGroup>

      {/* API Keys - Conditional on tier */}
      <SettingsGroup
        title="API Keys"
        badge={tier === 'pro' || tier === 'ultra' ? null : 'Pro+'}
      >
        {(tier === 'pro' || tier === 'ultra') ? (
          <ApiKeysList />
        ) : (
          <UpgradePrompt feature="BYOK" requiredTier="Pro" />
        )}
      </SettingsGroup>

      {/* Usage History - Inline */}
      <SettingsGroup title="Usage History">
        <UsageTable />
      </SettingsGroup>

      {/* Transaction History - Inline */}
      <SettingsGroup title="Transaction History">
        <TransactionTable />
      </SettingsGroup>
    </SettingsSection>
  );
}
```

**Button Styling (theme-compliant)**:
```tsx
// Primary button
<button className="bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white px-4 py-2 rounded-lg transition-colors min-h-[44px]">
  Add Credits
</button>

// Secondary button
<button className="bg-white/5 border border-white/10 hover:bg-white/10 text-[var(--text)] px-4 py-2 rounded-lg transition-colors min-h-[44px]">
  Change Plan
</button>
```

### B9. Remove Billing from Library

**Files to modify**:
- `app/src/pages/Library.tsx` - Remove credits tab
- `app/src/components/navigation/` - Update nav links
- `app/src/App.tsx` - Remove `/library?tab=credits` handling

### B10. Stripe Product Setup

**Create new Stripe Products/Prices**:
1. Basic Plan: $8/month recurring
2. Pro Plan: $20/month recurring
3. Ultra Plan: $100/month recurring
4. Credit Pack (500): $5 one-time
5. Credit Pack (1000): $10 one-time

**Update config**:
```python
stripe_basic_price_id: str = "price_basic_xxx"
stripe_pro_price_id: str = "price_pro_xxx"
stripe_ultra_price_id: str = "price_ultra_xxx"
```

---

## Complete Implementation Checklist

### Part A: Security Fixes (16 items)

#### New Models to Create
- [ ] `DeploySlotPurchase` model in `models.py`
- [ ] `WebhookEvent` model in `models.py`

#### [stripe_service.py](orchestrator/app/services/stripe_service.py) Security Fixes
- [ ] 1. Add idempotency check to `_handle_premium_subscription_checkout` (line 758-772)
- [ ] 2. Add `DeploySlotPurchase` record and idempotency check (line 880-896)
- [ ] 3. Fix race condition with `FOR UPDATE` in `_handle_credit_purchase_checkout` (line 780-808)
- [ ] 4. Fix agent purchase idempotency to use payment_intent (line 819-828)
- [ ] 8. Add idempotency_key to Transfer.create() (line 660-680)
- [ ] 9. Make credit purchase transaction atomic (line 789-808)
- [ ] 10. Make agent purchase/payout atomic (line 830-878)
- [ ] 14. Add idempotency_key to Invoice.create() (line 543)
- [ ] Add WebhookEvent logging for audit trail (line 688-740)

#### [webhooks.py](orchestrator/app/routers/webhooks.py) Security Fixes
- [ ] 5. Always return 200, log errors internally (line 45-50)

#### [billing.py](orchestrator/app/routers/billing.py) Security Fixes
- [ ] 6. Add rate limiting to purchase endpoints
- [ ] 7. Validate origin header against allowlist (line 178, 302, 368)
- [ ] 11. Replace print/traceback with proper logging (line 119-145)
- [ ] 13. Add credit balance floor check

#### [models.py](orchestrator/app/models.py) Security Fixes
- [ ] 12. Add WebhookEvent model for audit trail
- [ ] 15. Remove redundant index=True on unique columns
- [ ] 16. Add Enum classes for status values (SubscriptionTier, PaymentStatus)

#### [config.py](orchestrator/app/config.py) Security Fixes
- [ ] Add `allowed_origins: List[str]` setting

---

### Part B: UX & Tier Restructuring (12 items)

#### Database Changes
- [ ] B1. Add to User model: `bundled_credits`, `purchased_credits`, `credits_reset_date`
- [ ] B1. Update `subscription_tier` to support: free, basic, pro, ultra
- [ ] B1. Create migration for new fields

#### Backend Changes
- [ ] B2. Update `config.py` with new tier pricing, limits, and credit amounts
- [ ] B3. Update `/billing/credits` endpoint to return bundled vs purchased
- [ ] B4. Add monthly credit reset scheduled task
- [ ] B5. Add BYOK tier restriction (Pro+ only) in API keys router
- [ ] B6. Add `/billing/credits/status` endpoint for low balance check
- [ ] B10. Create Stripe products for Basic/Pro/Ultra tiers
- [ ] Update subscription handlers for new tiers

#### Frontend Changes (Theme-Compliant)
- [ ] B7. **Rebuild** `/settings/billing` as unified billing hub (using SettingsSection/SettingsGroup/SettingsItem)
- [ ] B8. Update `SubscriptionStatus` to show credits (not dollars) - header display already exists
- [ ] B9. Remove credits tab from `Library.tsx`
- [ ] B9. Remove standalone `/billing/*` routes from `App.tsx`
- [ ] B9. Delete or repurpose old billing pages (BillingDashboard, UsageDashboard, TransactionHistory)
- [ ] B6. Add `LowBalanceWarning` component (theme-compliant)
- [ ] B7. Add `OutOfCreditsModal` component (theme-compliant)
- [ ] Update `SubscriptionPlans` for 4-tier selection (Free/Basic/Pro/Ultra)
- [ ] Add BYOK upgrade prompt for Free/Basic users in API Keys settings
- [ ] Update `SettingsSidebar` to only show billing entry (remove redundant links)

---

### Files Summary

#### Backend Files to Modify
| File | Security Fixes | UX Changes |
|------|----------------|------------|
| `models_auth.py` | - | Add bundled_credits, purchased_credits, credits_reset_date |
| `models.py` | DeploySlotPurchase, WebhookEvent, Enums | - |
| `config.py` | allowed_origins | Tier config (free/basic/pro/ultra), credit amounts |
| `stripe_service.py` | 8 fixes (idempotency, atomic) | Handle new tiers, bundled credits |
| `billing.py` | 4 fixes (logging, rate limit) | New endpoints: /credits (bundled vs purchased), /credits/status |
| `webhooks.py` | Return 200 always | - |
| `routers/api_keys.py` | - | BYOK tier restriction (Pro+ only) |

#### Frontend Files to CREATE (Theme-Compliant)
| File | Purpose |
|------|---------|
| `pages/settings/BillingSettings.tsx` | **REBUILD** - Unified billing hub with all sections |
| `components/billing/LowBalanceWarning.tsx` | Warning banner at 20% threshold |
| `components/billing/OutOfCreditsModal.tsx` | Modal when credits = 0 |
| `components/billing/PlanSelector.tsx` | 4-tier plan cards |
| `components/billing/CreditDisplay.tsx` | Credits remaining + reset date |
| `components/billing/UsageSection.tsx` | Usage history (inline, not separate page) |
| `components/billing/TransactionSection.tsx` | Transaction history (inline) |

#### Frontend Files to MODIFY
| File | Changes |
|------|---------|
| `App.tsx` | Remove `/billing/*` routes |
| `Library.tsx` | Remove credits tab |
| `SubscriptionStatus.tsx` | Update to show credits not dollars |
| `SubscriptionPlans.tsx` | Update for 4 tiers |
| `SettingsSidebar.tsx` | Simplify billing section |
| `ApiKeysSettings.tsx` | Add BYOK tier restriction + upgrade prompt |

#### Frontend Files to DELETE/DEPRECATE
| File | Reason |
|------|--------|
| `pages/BillingDashboard.tsx` | Consolidated into Settings |
| `pages/UsageDashboard.tsx` | Consolidated into Settings |
| `pages/TransactionHistory.tsx` | Consolidated into Settings |
| `pages/SubscriptionPlans.tsx` (standalone) | Move to Settings modal |

---

## Verification Plan

### Part A: Security Testing

#### Unit Tests
```bash
# Test duplicate webhook handling
pytest tests/test_stripe_idempotency.py -v

# Test race condition prevention
pytest tests/test_concurrent_purchases.py -v

# Test origin validation
pytest tests/test_billing_security.py -v
```

#### Integration Tests
```bash
# Start Stripe CLI webhook forwarding
stripe listen --forward-to http://localhost:8000/api/webhooks/stripe

# Trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.created
stripe trigger invoice.payment_succeeded
```

#### Security Manual Testing
- [ ] Complete subscription checkout flow
- [ ] Replay webhook event (verify idempotency)
- [ ] Attempt webhook replay attack
- [ ] Test concurrent purchase requests
- [ ] Verify rate limiting blocks rapid requests
- [ ] Test with invalid origin header (should use default)
- [ ] Check for negative credit balance
- [ ] Verify payout idempotency
- [ ] Verify no sensitive data in logs
- [ ] Check audit logs for webhook events

---

### Part B: UX Testing

#### Tier & Credit Tests
- [ ] Free user gets 1000 bundled credits on signup
- [ ] Upgrading to Basic sets bundled_credits to 1000
- [ ] Upgrading to Pro sets bundled_credits to 2500
- [ ] Upgrading to Ultra sets bundled_credits to 12000
- [ ] Credit reset date is set to billing date + 30 days
- [ ] Purchased credits do NOT reset (persist across months)
- [ ] Bundled credits reset to tier allowance on reset date

#### Credit Display Tests
- [ ] Header shows "🎫 X credits" (not dollars)
- [ ] Settings billing shows total credits
- [ ] Settings billing shows reset date
- [ ] Low balance warning shows at 20% threshold
- [ ] Out of credits modal appears when credits = 0

#### BYOK Restriction Tests
- [ ] Free user cannot add API keys (403 error)
- [ ] Basic user cannot add API keys (403 error)
- [ ] Pro user CAN add API keys
- [ ] Ultra user CAN add API keys
- [ ] Free/Basic users see upgrade prompt in API Keys settings

#### Unified Billing Hub Tests
- [ ] /settings/billing shows all billing info
- [ ] Plan & Credits section works
- [ ] API Keys section shows (Pro+) or upgrade prompt
- [ ] Usage History section works
- [ ] Transaction History section works
- [ ] Library no longer has billing/credits tab

#### Stripe Product Tests
- [ ] Basic ($8/mo) checkout works
- [ ] Pro ($20/mo) checkout works
- [ ] Ultra ($100/mo) checkout works
- [ ] Credit pack 500 ($5) checkout works
- [ ] Credit pack 1000 ($10) checkout works
- [ ] Webhook updates bundled_credits correctly for each tier

---

## Database Migration

```python
# orchestrator/alembic/versions/xxxx_stripe_security_and_ux_overhaul.py
"""
Stripe security fixes and UX overhaul:
- Add DeploySlotPurchase and WebhookEvent models (security)
- Add bundled/purchased credits and reset date to User (UX)
"""

def upgrade():
    # ===== SECURITY: DeploySlotPurchase table =====
    op.create_table(
        'deploy_slot_purchases',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('amount_cents', sa.Integer(), nullable=False),
        sa.Column('stripe_payment_intent', sa.String(), nullable=False),
        sa.Column('stripe_checkout_session', sa.String()),
        sa.Column('status', sa.String(), default='completed'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('stripe_payment_intent')
    )
    op.create_index('ix_deploy_slot_purchases_user_id', 'deploy_slot_purchases', ['user_id'])

    # ===== SECURITY: WebhookEvent table =====
    op.create_table(
        'webhook_events',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('stripe_event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('payload', sa.JSON()),
        sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('status', sa.String(), default='processed'),
        sa.Column('error_message', sa.String()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_event_id')
    )
    op.create_index('ix_webhook_events_stripe_event_id', 'webhook_events', ['stripe_event_id'])
    op.create_index('ix_webhook_events_event_type', 'webhook_events', ['event_type'])

    # ===== UX: User table - credit tracking fields =====
    # Add bundled_credits (monthly allowance, resets)
    op.add_column('users', sa.Column('bundled_credits', sa.Integer(), nullable=False, server_default='1000'))

    # Add purchased_credits (never expire)
    op.add_column('users', sa.Column('purchased_credits', sa.Integer(), nullable=False, server_default='0'))

    # Add credits_reset_date (when bundled credits reset)
    op.add_column('users', sa.Column('credits_reset_date', sa.DateTime(timezone=True), nullable=True))

    # ===== DATA MIGRATION: Move existing credits_balance to purchased_credits =====
    # Existing credits were all purchased (no bundled system before)
    op.execute("""
        UPDATE users
        SET purchased_credits = credits_balance,
            bundled_credits = CASE
                WHEN subscription_tier = 'pro' THEN 2500
                ELSE 1000
            END,
            credits_reset_date = CURRENT_TIMESTAMP + INTERVAL '30 days'
        WHERE credits_balance > 0 OR subscription_tier != 'free'
    """)

    # ===== UX: Set initial bundled credits for free users =====
    op.execute("""
        UPDATE users
        SET bundled_credits = 1000
        WHERE subscription_tier = 'free' AND bundled_credits = 0
    """)

def downgrade():
    # Remove UX columns
    op.drop_column('users', 'credits_reset_date')
    op.drop_column('users', 'purchased_credits')
    op.drop_column('users', 'bundled_credits')

    # Remove security tables
    op.drop_table('webhook_events')
    op.drop_table('deploy_slot_purchases')
```

---

## Summary

### PRIORITY: Part B - UX & Tier Restructuring (DO FIRST)

**Goal: Consolidate ALL billing into `/settings/billing`, remove from everywhere else.**

**Backend Changes:**
1. Database: Add bundled_credits, purchased_credits, credits_reset_date to User
2. Database: Update subscription_tier to support free/basic/pro/ultra
3. Config: New tier pricing ($0/$8/$20/$100) and credit amounts (1000/1000/2500/12000)
4. Backend: Monthly credit reset scheduled task
5. Backend: BYOK restriction to Pro+ tiers
6. Backend: Low balance status endpoint (/billing/credits/status)
7. Backend: Update /billing/credits endpoint (bundled vs purchased)

**Frontend Changes (Theme-Compliant):**
1. REBUILD `/settings/billing` as unified billing hub
2. Remove credits tab from Library
3. Remove standalone `/billing/*` routes
4. Delete old billing pages (BillingDashboard, UsageDashboard, TransactionHistory)
5. Add LowBalanceWarning component
6. Add OutOfCreditsModal component
7. Update SubscriptionStatus to show credits not dollars (header already exists)
8. Update SubscriptionPlans for 4 tiers
9. Add BYOK upgrade prompt for Free/Basic in API Keys settings

### THEN: Part A - Security Fixes (16 items)
1. Premium subscription idempotency check
2. Deploy slot purchase model + idempotency
3. Credit purchase race condition fix (FOR UPDATE)
4. Agent purchase idempotency by payment_intent
5. Webhook always returns 200
6. Rate limiting on purchase endpoints
7. Origin header validation
8. Transfer idempotency key
9. Atomic credit purchase transaction
10. Atomic agent purchase/payout transaction
11. Remove debug print statements
12. WebhookEvent audit table
13. Credit balance floor check
14. Invoice idempotency key
15. Remove redundant index
16. Status Enums

### Stripe Products to Create
- Basic: $8/month → `price_basic_xxx`
- Pro: $20/month → `price_pro_xxx`
- Ultra: $100/month → `price_ultra_xxx`
- Credit Pack 500: $5 → one-time
- Credit Pack 1000: $10 → one-time
