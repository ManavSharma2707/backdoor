"""Every threshold the engine uses, in one place. `memory.md` lists the values actually in force.

Business settings (`business_settings`) override the ones marked "setting". The rest are fixed
by `engine-spec.md` and only change with a spec change.
"""

from typing import Final

MODEL_NAME: Final = "forecast-engine"
ENGINE_VERSION: Final = "1.0.0"

# Demand classification (engine-spec 4)
CLASS_WINDOW_DAYS: Final = 180
MIN_TRUSTED_DAYS: Final = 28
MIN_HISTORY_DAYS: Final = 7
ADI_CUTOFF: Final = 1.32
CV2_CUTOFF: Final = 0.49

# Forecast methods (engine-spec 5)
METHODS: Final = (
    "seasonal_naive",
    "moving_average",
    "weekday_profile",
    "ses_weekday",
    "croston_sba",
    "lightgbm_global",
    "category_prior",
)
BASELINE_METHODS: Final = ("seasonal_naive", "moving_average")
MA_WINDOW_SMOOTH: Final = 28
MA_WINDOW_INTERMITTENT: Final = 56
WEEKDAY_WEEKS: Final = 8
WEEKDAY_MIN_DAYS: Final = 42
WEEKDAY_SHRINK_K: Final = 4.0
SES_ALPHAS: Final = (0.05, 0.1, 0.2, 0.3, 0.5)
SES_WINDOW_DAYS: Final = 112
CROSTON_ALPHA: Final = 0.1
PRIOR_FACTOR: Final = 0.8
PRIOR_WINDOW_DAYS: Final = 56
TRAINING_DAYS: Final = 800

# Censoring (engine-spec 5.1)
CENSORED_SHARE_WARN: Final = 0.30
CENSORED_WINDOW_DAYS: Final = 56
CENSORED_SHARE_HIGH_CONFIDENCE: Final = 0.15

# LightGBM (engine-spec 5.3)
LGBM_ORIGIN_WEEKS: Final = 70
LGBM_MAX_ROWS: Final = 450_000
LGBM_TIME_CAP_SECONDS: Final = 300
LGBM_BACKTEST_ORIGINS: Final = 4
LGBM_SEED: Final = 42

# Backtest and selection (engine-spec 6)
BACKTEST_ORIGINS: Final = 12
BACKTEST_HORIZON: Final = 7
PARSIMONY: Final = 0.03
MIN_SEGMENT_PRODUCTS: Final = 3
MIN_SEGMENT_POINTS: Final = 200
SELECTION_MAX_AGE_DAYS: Final = 35
INTERVAL_LOWER_Q: Final = 0.10
INTERVAL_UPPER_Q: Final = 0.90

# Confidence (engine-spec 6.4)
HIGH_COVERAGE: Final = 0.80
HIGH_WAPE: Final = 0.35
MEDIUM_COVERAGE: Final = 0.60
MEDIUM_WAPE: Final = 0.60
INTERMITTENT_MAE_RATIO: Final = 1.0
COVERAGE_WINDOW_DAYS: Final = 90

# Event effects (engine-spec 7)
EFFECT_BASELINE_WEEKS: Final = 8
EFFECT_MIN_BASELINE_DAYS: Final = 28
EFFECT_MIN_TRUSTED_SHARE: Final = 0.70
EFFECT_MIN_PRODUCTS: Final = 3
EFFECT_MIN_SHIFT: Final = 0.15
EFFECT_MIN_CONSISTENCY: Final = 0.60
EFFECT_FDR: Final = 0.10
EFFECT_DEVIATION: Final = 0.05
EFFECT_SHRINK_K: Final = 0.5
EFFECT_CLIP_LOW: Final = 0.5
EFFECT_CLIP_HIGH: Final = 3.0
EFFECT_MIN_DURING_DAYS: Final = 3
MEDICAL_MIN_OCCURRENCES: Final = 2
MEDICAL_MIN_CONSISTENCY: Final = 0.75
HIGH_EFFECT_CONSISTENCY: Final = 0.75
EFFECT_REFRESH_DAYS: Final = 7
PROMO_MIN_OCCURRENCES: Final = 2
PROMOTION_KEY: Final = "promotion"

# Inventory, expiry and replenishment (engine-spec 8 to 10)
EXTENSION_DAYS: Final = 14
EXPIRY_EXTRAPOLATION_CAP_DAYS: Final = 365
EXPIRY_CAP_DAYS_MAX: Final = 120
SIGMA_FLOOR_RATIO: Final = 0.5
FORECAST_HORIZON_DAYS: Final = 28

# Risk (engine-spec 11)
RISK_CRITICAL: Final = 0.60
RISK_HIGH: Final = 0.30
RISK_MEDIUM: Final = 0.10
DAYS_OF_COVER_WINDOW: Final = 14

# Budget (engine-spec 12)
CONFIDENCE_SCORE: Final = {"high": 1.0, "medium": 0.7, "low": 0.4}
DEFAULT_WEIGHTS: Final = {"risk": 0.45, "value": 0.30, "confidence": 0.15, "excess": 0.10}

# Stock status (engine-spec 13)
AVAILABLE_SHARE_MIN: Final = 0.70
ABC_A_SHARE: Final = 0.70
ABC_B_SHARE: Final = 0.90
ABC_WINDOW_DAYS: Final = 90

# Data quality (engine-spec 14)
PRICE_ANOMALY_RATIO: Final = 0.30
CALENDAR_LOOKAHEAD_DAYS: Final = 60
UNRECORDED_STOCKOUT_DAYS: Final = 2
EXCEPTION_RECEIPT_DAYS: Final = 30
DUPLICATE_WINDOW_SECONDS: Final = 120

# Festival and report (report-spec 1)
FESTIVAL_NOTE_DAYS: Final = 21
FESTIVAL_SECTION_DAYS: Final = 35
RETAINED_FORECAST_RUNS: Final = 8
