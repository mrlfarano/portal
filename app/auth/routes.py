from flask import current_app, redirect, url_for, flash, session, request, render_template
from flask_login import login_user, logout_user, login_required, current_user
from app.auth import bp
from app.models import User
from app import db
from oauthlib.oauth2 import WebApplicationClient
import requests
import json
import os

# Initialize OAuth client only if not in development
if os.getenv('FLASK_ENV') != 'development':
    client = WebApplicationClient(os.getenv('GOOGLE_CLIENT_ID'))
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

    def get_google_provider_cfg():
        return requests.get(GOOGLE_DISCOVERY_URL).json()

@bp.route('/')
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if os.getenv('FLASK_ENV') != 'development':
            current_app.logger.warning('Attempted to use development login in production')
            flash('Development login is not available in production.', 'error')
            return redirect(url_for('main.index'))
        
        email = request.form.get('email')
        if not email:
            current_app.logger.warning('Login attempt with no email provided')
            flash('Email is required', 'error')
            return redirect(url_for('auth.login'))

        # Create or get development user
        user = User.query.filter_by(email=email).first()
        if not user:
            current_app.logger.info(f'Creating new development user: {email}')
            user = User(
                email=email,
                name=email.split('@')[0],
                google_id='dev-' + email  # Prefix with 'dev-' to distinguish from real Google IDs
            )
            db.session.add(user)
            db.session.commit()
        else:
            current_app.logger.info(f'Existing user logged in: {email}')

        login_user(user)
        flash('Logged in successfully.', 'success')
        return redirect(url_for('main.index'))
    else:
        if os.getenv('FLASK_ENV') == 'development':
            current_app.logger.info('Serving development login page')
            return render_template('auth/dev_login.html')
        
        current_app.logger.info('Initiating Google OAuth flow')
        # Get Google's OAuth2 provider configuration
        google_provider_cfg = get_google_provider_cfg()
        authorization_endpoint = google_provider_cfg["authorization_endpoint"]

        # Construct the request for Google login
        request_uri = client.prepare_request_uri(
            authorization_endpoint,
            redirect_uri=request.base_url + "/callback",
            scope=["openid", "email", "profile"],
        )
        return redirect(request_uri)

@bp.route("/login/callback")
def callback():
    if os.getenv('FLASK_ENV') == 'development':
        current_app.logger.warning('OAuth callback accessed in development mode')
        return redirect(url_for('auth.login'))

    # Get authorization code Google sent back
    code = request.args.get("code")
    if not code:
        current_app.logger.error('No authorization code received from Google')
        flash('Authentication failed.', 'error')
        return redirect(url_for('auth.login'))

    current_app.logger.info('Processing Google OAuth callback')
    # Find out what URL to hit to get tokens
    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    # Get tokens
    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=request.base_url,
        code=code
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(os.getenv('GOOGLE_CLIENT_ID'), os.getenv('GOOGLE_CLIENT_SECRET')),
    )

    # Parse the tokens
    client.parse_request_body_response(json.dumps(token_response.json()))

    # Get user info from Google
    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    if userinfo_response.json().get("email_verified"):
        unique_id = userinfo_response.json()["sub"]
        users_email = userinfo_response.json()["email"]
        users_name = userinfo_response.json().get("given_name", users_email.split('@')[0])

        # Check if user's email is in the allowed list
        allowed_emails = current_app.config.get('ALLOWED_EMAILS', [])
        if allowed_emails and users_email not in allowed_emails:
            current_app.logger.warning(f'Unauthorized access attempt from: {users_email}')
            flash('You are not authorized to access this application.', 'error')
            return redirect(url_for('auth.login'))

        # Create or get user
        user = User.query.filter_by(google_id=unique_id).first()
        if not user:
            current_app.logger.info(f'Creating new user from Google OAuth: {users_email}')
            user = User(
                google_id=unique_id,
                name=users_name,
                email=users_email
            )
            db.session.add(user)
            db.session.commit()
        else:
            current_app.logger.info(f'Existing Google user logged in: {users_email}')

        # Begin user session
        login_user(user)
        flash('Logged in successfully.', 'success')
        return redirect(url_for('main.index'))
    else:
        current_app.logger.error('User email not verified by Google')
        flash('Google authentication failed.', 'error')
        return redirect(url_for('auth.login'))

@bp.route("/logout")
@login_required
def logout():
    current_app.logger.info(f'User logged out: {current_user.email}')
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('auth.login'))
