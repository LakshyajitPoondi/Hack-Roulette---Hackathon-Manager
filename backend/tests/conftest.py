import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-only-jwt-secret-with-more-than-32-characters"
os.environ["FRONTEND_ORIGIN"] = "http://127.0.0.1:5173"
os.environ["COOKIE_SECURE"] = "false"
os.environ["EMAIL_MODE"] = "development"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Role, User, Participant


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db):
    def create(role: Role, email: str):
        user = User(name=role.value, email=email, password_hash=hash_password("strong-test-password-123"), role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    return create


@pytest.fixture
def login(client):
    def sign_in(email: str):
        response = client.post("/api/auth/login", json={"email": email, "password": "strong-test-password-123"})
        assert response.status_code == 200
    return sign_in


@pytest.fixture
def fake_sheet(db):
    # Compatibility helper for older campaign tests; stores participants in Postgres's test equivalent.
    class People:
        @property
        def people(self):
            return list(db.query(Participant).all())

        @people.setter
        def people(self, values):
            db.add_all(values)
            db.commit()

        def make(self, id, name, email, college="Example College", eligible=True, disqualified=False):
            return Participant(id=id, name=name, email=email, college=college, team_name="Team Test")
    return People()
