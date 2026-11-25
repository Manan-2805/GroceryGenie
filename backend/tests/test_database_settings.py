from secrets import token_hex

from pydantic import SecretStr

from app.core.config import Settings


def test_compose_database_url_keeps_literal_password_out_of_display():
    credential = token_hex(16) + "@/:%"
    settings = Settings(
        _env_file=None,
        DATABASE_URL=None,
        DB_HOST="postgres",
        DB_USER="grocery",
        DB_NAME="grocery_db",
        POSTGRES_PASSWORD=SecretStr(credential),
    )

    assert settings.database_url.host == "postgres"
    assert settings.database_url.database == "grocery_db"
    assert settings.database_url.password == credential
    assert credential not in str(settings.database_url)
    assert credential not in repr(settings)


def test_database_url_override_takes_precedence():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql+asyncpg://tester@127.0.0.1:55432/isolated_test",
        DB_HOST="postgres",
    )
    assert settings.database_url.port == 55432
    assert settings.database_url.database == "isolated_test"
