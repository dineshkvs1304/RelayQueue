import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from relayqueue.api.dependencies import get_db
from relayqueue.core.config import get_settings
from relayqueue.database.base import Base
from relayqueue.main import app


@pytest.fixture(scope="session")
def test_engine():
    """Create an isolated engine for the test database."""
    settings = get_settings()

    test_database_url = settings.database_url.set(database="relayqueue_test")

    engine = create_engine(
        test_database_url,
        pool_pre_ping=True,
        echo=False,
    )

    # Create tables only in the dedicated test database.
    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine):
    """Provide a database session isolated by an outer transaction."""
    connection = test_engine.connect()
    transaction = connection.begin()

    session = Session(
        bind=connection,
        autoflush=False,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )

    try:
        yield session
    finally:
        session.close()

        if transaction.is_active:
            transaction.rollback()

        connection.close()


@pytest.fixture
def client(db_session):
    """Provide a FastAPI client using the test database session."""

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
