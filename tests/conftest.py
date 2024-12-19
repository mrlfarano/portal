import pytest
from app import create_app, db
from app.models import User, Setting
import os

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    # Create a temporary database file
    db_fd, db_path = tempfile.mkstemp()
    
    app = create_app()
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{db_path}',
        'WTF_CSRF_ENABLED': False,
        'SERVER_NAME': 'localhost:5000',  # Required for url_for() to work in tests
        'ETSY_API_KEY': 'test_api_key',
        'ETSY_SHARED_SECRET': 'test_shared_secret'
    })

    # Create the database and the database tables
    with app.app_context():
        db.create_all()
        # Create a test user
        user = User(email='test@example.com')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()

    yield app

    # Close and remove the temporary database
    os.close(db_fd)
    os.unlink(db_path)

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's Click commands."""
    return app.test_cli_runner()

@pytest.fixture
def auth_client(client):
    """A test client with an authenticated user."""
    client.post('/auth/login', data={
        'email': 'test@example.com',
        'password': 'password'
    }, follow_redirects=True)
    return client
