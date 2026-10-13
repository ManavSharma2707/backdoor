import pytest

from app.core.config import ConfigError, Settings

STRONG = "x" * 48
PROD_DB = "postgresql+psycopg://u:p@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


def make(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "production",
        "database_url": PROD_DB,
        "jwt_secret": STRONG,
        "job_token": STRONG + "y",
        "cookie_secure": True,
        "cors_origins": "https://backroom.vercel.app",
    }
    return Settings(**{**base, **overrides}, _env_file=None)  # type: ignore[arg-type]


def test_local_defaults_are_usable() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.app_env == "local"
    assert settings.allow_registration is False
    assert settings.demo_login_enabled is False
    assert settings.allow_demo_reset is False
    assert settings.simulate_weekly is False
    assert settings.embed_dim == 768


def test_valid_production_settings_load() -> None:
    settings = make()
    assert settings.is_production
    assert settings.cors_origins == ["https://backroom.vercel.app"]


def test_cors_origins_parse_a_comma_list() -> None:
    settings = make(cors_origins="https://a.example.com/, http://localhost:5173 ,")
    assert settings.cors_origins == ["https://a.example.com", "http://localhost:5173"]


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET must be at least 32"),
        ({"jwt_secret": "replace-with-32-plus-random-bytes-base64"}, "JWT_SECRET is a placeholder"),
        ({"jwt_secret": "dev-only-" + "a" * 40}, "JWT_SECRET is a placeholder"),
        ({"job_token": "short"}, "JOB_TOKEN must be at least 32"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"cors_origins": ""}, "CORS_ORIGINS must list"),
        ({"cors_origins": "*"}, "wildcard"),
        (
            {"database_url": "postgresql+psycopg://backroom:backroom@localhost:5432/backroom"},
            "DATABASE_URL",
        ),
    ],
)
def test_production_refuses_unsafe_settings(override: dict[str, object], fragment: str) -> None:
    with pytest.raises(ConfigError, match=fragment):
        make(**override)


def test_default_dev_secret_is_rejected_in_production() -> None:
    with pytest.raises(ConfigError, match="placeholder"):
        Settings(
            app_env="production",
            database_url=PROD_DB,
            cookie_secure=True,
            cors_origins="https://x.example.com",
            _env_file=None,  # type: ignore[call-arg]
        )


def test_every_problem_is_reported_together() -> None:
    with pytest.raises(ConfigError) as caught:
        make(jwt_secret="short", cookie_secure=False)
    message = str(caught.value)
    assert "JWT_SECRET" in message
    assert "COOKIE_SECURE" in message


@pytest.mark.parametrize("env", ["local", "test"])
def test_local_and_test_environments_skip_the_strict_checks(env: str) -> None:
    settings = Settings(app_env=env, cookie_secure=False, _env_file=None)  # type: ignore[arg-type, call-arg]
    assert not settings.is_production
