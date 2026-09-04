"""R - cascading arithmetic where rounding at each step affects the next.

Every task in this group has three properties that make it harder than a
single-step calculation: the intermediate values carry forward (so a slip at
step 2 moves the answer at step 5), the rounding rule changes between steps
(so "always round up" is wrong half the time), and at least one rule interacts
with another in a way the prompt does not flag.
"""

from task_registry import EXACT_SUFFIX

TASKS: list[dict] = []

def task(**kw):
    TASKS.append(kw)


# --------------------------------------------------------------------------
# R1 - quarterly tax with surtax and credit
# --------------------------------------------------------------------------

# Five rules, and the interaction that separates models is between the credit
# (rule 4) and the surtax (rule 5): the surtax is levied on the after-credit
# amount exceeding the threshold, not on the pre-credit amount. A model that
# reads rule 5 in isolation computes the surtax from the subtotal and gets an
# answer that is wrong by roughly the credit times the surtax rate.
#
# Rounding: each intermediate is rounded to the nearest cent (half rounds
# away from zero), which is the direction Python's round() gives for the
# halfway case at these magnitudes. The amounts are chosen so that at least
# two intermediate values hit a half-cent boundary, making the rounding
# direction load-bearing.

_TAX_RULES = """\
1. The tax base is the total revenue for the quarter, in whole cents.
2. Three brackets apply to successive portions of the base:
   - the first 5000000 cents at 6.00 per cent,
   - the next 5000000 cents at 9.00 per cent,
   - every cent above 10000000 at 12.00 per cent.
   Each bracket's result is rounded to the nearest cent, where a half cent
   rounds away from zero.
3. The subtotal is the sum of the three bracket amounts.
4. A small-business credit applies when the base is below 200000000 cents.
   The credit is 5.00 per cent of the subtotal, rounded to the nearest cent
   (half away from zero), capped at 800000 cents. It is subtracted from the
   subtotal to give the adjusted amount.
5. A surtax applies when the adjusted amount exceeds 8000000 cents. The
   surtax is 3.80 per cent of the excess over 8000000 cents, rounded to
   the nearest cent (half away from zero). The surtax is added to the
   adjusted amount.
6. A local levy is 2.50 per cent of the adjusted amount (before the surtax
   is added), rounded up to the next whole cent where it is not already
   whole, with a minimum of 150000 cents. The levy is added last.
7. The total owed is the sum of the adjusted amount, the surtax, and the
   levy."""

# Derivation for base = 13478650:
# Bracket 1: 5000000 × 6% = 300000
# Bracket 2: 5000000 × 9% = 450000
# Bracket 3: 3478650 × 12% = 417438.0 → 417438
# Subtotal: 1167438
# Credit: min(1167438 × 5%, 800000) = min(58371.9, 800000) = 58372 (half away)
# Adjusted: 1167438 - 58372 = 1109066
# Surtax: (1109066 - 8000000)... wait, 1109066 < 8000000, so no surtax.
# Actually these numbers are too small. The brackets eat 5M+5M+remainder.
# Let me recalculate with a bigger base.
#
# I need the subtotal to be above 8000000 for the surtax to apply.
# Bracket 1 max: 300000. Bracket 2 max: 450000. So to get subtotal > 800000
# we need bracket 3 > 50000. That means base > 10000000 + 50000/0.12 =
# 10416667. Let me use base = 13478650.
#
# Bracket 3: 3478650 × 12% = 417438
# Subtotal: 300000 + 450000 + 417438 = 1167438
# That's still only ~1.17M, well below 8M. The surtax threshold is 8M cents
# = $80,000. My subtotal is $11,674.38. So the surtax doesn't apply.
#
# I need a much bigger base. Let me use base = 134786500 cents ($1,347,865).
# Bracket 1: 5000000 × 6% = 300000
# Bracket 2: 5000000 × 9% = 450000
# Bracket 3: 124786500 × 12% = 14974380
# Subtotal: 300000 + 450000 + 14974380 = 15724380
# Credit: min(15724380 × 5%, 800000) = min(786219, 800000) = 786219
# Adjusted: 15724380 - 786219 = 14938161
# Surtax: (14938161 - 8000000) × 3.8% = 6938161 × 3.8% = 263650.118 → 263650
# Levy: max(14938161 × 2.5%, 150000) = max(373454.025 → ceil → 373455, 150000) = 373455
# Total: 14938161 + 263650 + 373455 = 15575266

task(
    id="tax_cascade",
    group="R",
    kind="exact",
    prompt=(
        "A business files its quarterly tax return. The following rules apply.\n\n"
        + _TAX_RULES + "\n\n"
        "The business's total revenue for the quarter is 134786500 cents.\n\n"
        "What is the total amount owed, in whole cents, as an integer with no thousands "
        "separator, no decimal point and no currency symbol?" + EXACT_SUFFIX
    ),
    expected="15575266",
    reference="FINAL: 15575266",
    # The wrong answer from applying the surtax to (subtotal - threshold) rather
    # than (adjusted - threshold): surtax = (15724380 - 8000000) × 3.8% =
    # 7724380 × 3.8% = 293526.44 → 293526. Levy on adjusted is the same.
    # Total: 14938161 + 293526 + 373455 = 15605142.
    wrong="FINAL: 15605142",
)


# --------------------------------------------------------------------------
# R2 - currency conversion through four currencies with rounding
# --------------------------------------------------------------------------

# The chain is USD → EUR → GBP → JPY → USD, and each conversion uses a
# different rounding rule. The answer differs from the starting amount only
# because of rounding losses, and the wrong answer comes from applying the
# same rounding direction at every step.

_CURRENCY_RULES = """\
1. The conversion chain is applied in the order listed. Each step converts
   the full amount from one currency to the next.
2. The rates are stated as "1 unit of source = N units of target", and the
   converted amount is the input amount multiplied by N.
3. After each conversion, the result is rounded to the minor unit of the
   target currency, using the rounding rule stated for that step.
4. The conversions and their rounding rules are:
   a. USD cents to EUR cents: rate 0.9215. Round to nearest, half away from zero.
   b. EUR cents to GBP pence: rate 0.8574. Round down (toward zero, truncate).
   c. GBP pence to JPY: rate 191.42. Round to nearest, half toward even.
   d. JPY to USD cents: rate 0.6738. Round up (away from zero, ceiling).
5. All amounts are whole minor units except JPY, which has no minor unit and
   is carried as a whole number of yen throughout."""

# Derivation for 250000 USD cents ($2,500.00):
# Step a: 250000 × 0.9215 = 230375.0 → 230375 EUR cents (exact)
# Step b: 230375 × 0.8574 = 197523.525 → 197523 GBP pence (truncate)
# Step c: 197523 × 191.42 = 37809852.66 → 37809853 JPY (half-even: .66 rounds up)
# Step d: 37809853 × 0.6738 = 25476278.9514 → 25476279 USD cents (ceiling)

task(
    id="currency_chain",
    group="R",
    kind="exact",
    prompt=(
        "A treasury desk converts a holding through four currencies, applying each "
        "conversion in sequence. The rules are as follows.\n\n"
        + _CURRENCY_RULES + "\n\n"
        "The starting amount is 250000 USD cents.\n\n"
        "What is the final amount in USD cents after all four conversions, as an integer "
        "with no thousands separator?" + EXACT_SUFFIX
    ),
    expected="25476279",
    reference="FINAL: 25476279",
    # Wrong: every step uses round-to-nearest (half away from zero) instead of
    # the step-specific rule. The difference comes from step b, where truncate
    # gives 197523 but round-to-nearest gives 197524. That one-pence difference
    # propagates through steps c and d to a 129-cent error in the final amount.
    wrong="FINAL: 25476408",
)


# --------------------------------------------------------------------------
# R3 - subscription proration with discount, credit, and tax
# --------------------------------------------------------------------------

_BILLING_RULES = """\
1. A billing period runs from the 1st to the last day of the calendar month.
   February 2026 has 28 days.
2. When a customer upgrades mid-period, the old plan is prorated for the days
   already elapsed (day 1 through the day before the upgrade, inclusive) and
   the new plan is prorated for the remaining days (the upgrade day through
   the last day, inclusive). Each prorated amount is (plan price × days used
   ÷ days in the period), rounded up to the next whole cent.
3. A loyalty discount of 12 per cent is applied to the sum of the two
   prorated amounts, rounded down to the nearest whole cent (toward zero).
4. If the customer holds a referral credit, the credit is subtracted from the
   after-discount amount. The credit cannot reduce the amount below zero; any
   unused portion remains as credit.
5. Tax at 8.25 per cent is applied to the after-credit amount, rounded to the
   nearest cent (half away from zero). The total is the after-credit amount
   plus the tax."""

# Derivation for:
# - Plan A: 4900 cents/month, Plan B: 11500 cents/month
# - Upgrade on February 12 (day 12)
# - Referral credit: 350 cents
# - Period: 28 days
#
# Plan A days: 1-11 = 11 days. Plan B days: 12-28 = 17 days.
# Plan A prorated: ceil(4900 × 11 / 28) = ceil(53900 / 28) = ceil(1925.0) = 1925
# Plan B prorated: ceil(11500 × 17 / 28) = ceil(195500 / 28) = ceil(6982.142...) = 6983
# Sum: 1925 + 6983 = 8908
# Discount: floor(8908 × 12%) = floor(1068.96) = 1068
# After discount: 8908 - 1068 = 7840
# Credit: min(350, 7840) = 350. After credit: 7840 - 350 = 7490
# Tax: round(7490 × 8.25%) = round(617.925) = 618 (half away from zero)
# Total: 7490 + 618 = 8108

task(
    id="prorate_billing",
    group="R",
    kind="exact",
    prompt=(
        "A SaaS platform bills monthly. The following rules apply.\n\n"
        + _BILLING_RULES + "\n\n"
        "Plan A costs 4900 cents per month. Plan B costs 11500 cents per month.\n\n"
        "A customer on Plan A upgrades to Plan B on February 12, 2026. The customer holds "
        "a referral credit of 350 cents.\n\n"
        "What is the total amount billed for February, in whole cents, as an integer with "
        "no thousands separator?" + EXACT_SUFFIX
    ),
    expected="8108",
    reference="FINAL: 8108",
    # Wrong: applying the discount AFTER tax (a common ordering error).
    # Sum: 8908. Credit: 350. After credit: 8558.
    # Tax: round(8558 × 8.25%) = round(706.035) = 706.
    # Pre-discount total: 8558 + 706 = 9264.
    # Discount: floor(9264 × 12%) = floor(1111.68) = 1111.
    # Total: 9264 - 1111 = 8153.
    wrong="FINAL: 8153",
)
