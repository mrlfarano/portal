from flask import Blueprint, render_template, redirect, url_for, flash, current_app, request, session, jsonify
from flask_login import login_required, current_user
from app.main import bp
from app.models import Order, Customer, Message, Setting
from app import db
from datetime import datetime
import requests
from app.main.forms import APISettingsForm
from app.integrations.etsy import EtsyIntegration
import secrets
from urllib.parse import quote
from datetime import timedelta
import os
import json

def generate_code_verifier() -> str:
    """Generate a code verifier for PKCE"""
    import secrets
    import base64
    token = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(token).rstrip(b'=').decode('utf-8')

def generate_code_challenge(verifier: str) -> str:
    """Generate a code challenge for PKCE"""
    import hashlib
    import base64
    sha256 = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(sha256).rstrip(b'=').decode('utf-8')

@bp.route('/')
@bp.route('/index')
@login_required
def index():
    # Get latest orders from all platforms
    orders = Order.query.order_by(Order.order_date.desc()).limit(10).all()
    return render_template('main/index.html', orders=orders)

@bp.route('/orders')
@login_required
def orders():
    platform = request.args.get('platform', 'all')
    status = request.args.get('status', 'all')
    
    query = Order.query
    if platform != 'all':
        query = query.filter(Order.platform == platform)
    if status != 'all':
        query = query.filter(Order.status == status)
    
    orders = query.order_by(Order.order_date.desc()).all()
    return render_template('main/orders.html', 
                         orders=orders, 
                         current_platform=platform,
                         current_status=status)

@bp.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '')
    if search:
        customers = Customer.query.filter(
            (Customer.name.ilike(f'%{search}%')) |
            (Customer.email.ilike(f'%{search}%'))
        ).all()
    else:
        customers = Customer.query.order_by(Customer.created_at.desc()).all()
    return render_template('main/customers.html', customers=customers, search=search)

@bp.route('/customer/<int:id>')
@login_required
def customer(id):
    customer = Customer.query.get_or_404(id)
    orders = Order.query.filter_by(customer_id=id).order_by(Order.order_date.desc()).all()
    messages = Message.query.filter_by(customer_id=id).order_by(Message.sent_at.desc()).all()
    return render_template('main/customer_detail.html', 
                         customer=customer, 
                         orders=orders,
                         messages=messages)

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    form = APISettingsForm()
    
    if form.validate_on_submit():
        # Save Square settings
        if form.square_access_token.data:
            Setting.set_value('SQUARE_ACCESS_TOKEN', form.square_access_token.data, is_encrypted=True)
            flash('Settings updated successfully!', 'success')
        return redirect(url_for('main.settings'))

    # Pre-fill form with existing values
    square_access_token = Setting.get_value('SQUARE_ACCESS_TOKEN')
    if square_access_token:
        form.square_access_token.data = square_access_token

    # Get last sync times
    etsy_last_sync = Setting.get_value('ETSY_LAST_SYNC')
    square_last_sync = Setting.get_value('SQUARE_LAST_SYNC')
    
    # Check if connected to Etsy
    etsy_connected = Setting.get_value('ETSY_ACCESS_TOKEN') is not None

    return render_template('main/settings.html',
                         form=form,
                         etsy_connected=etsy_connected,
                         etsy_last_sync=etsy_last_sync,
                         square_last_sync=square_last_sync)

@bp.route('/sync/etsy')
@login_required
def sync_etsy():
    try:
        etsy = EtsyIntegration()
        new_orders, updated_orders = etsy.sync_orders()
        
        if new_orders or updated_orders:
            flash(f'Successfully synced Etsy orders. {new_orders} new, {updated_orders} updated.', 'success')
        else:
            flash('No new Etsy orders found.', 'info')
            
    except ValueError as e:
        current_app.logger.error(f"Configuration error in Etsy sync: {str(e)}")
        flash('Etsy API key not configured. Please check your settings.', 'error')
    except Exception as e:
        current_app.logger.error(f"Error syncing Etsy orders: {str(e)}", exc_info=True)
        flash('Error syncing Etsy orders. Check the logs for details.', 'error')
    
    return redirect(url_for('main.orders', platform='etsy'))

@bp.route('/sync/square', methods=['POST'])
@login_required
def sync_square():
    """Manually trigger Square order sync"""
    try:
        from app.integrations.square import SquareIntegration
        
        # Check if Square access token is configured
        if not current_app.config.get('SQUARE_ACCESS_TOKEN'):
            flash('Square access token is not configured.', 'error')
            return redirect(url_for('main.settings'))
        
        # Perform sync
        square_integration = SquareIntegration()
        new_orders, updated_orders = square_integration.sync_orders()
        
        # Provide feedback
        flash(f'Square sync successful. New orders: {new_orders}, Updated orders: {updated_orders}', 'success')
        
    except ValueError as ve:
        # Handle configuration or API errors
        flash(str(ve), 'error')
    except Exception as e:
        # Log unexpected errors
        current_app.logger.error(f'Error during Square sync: {str(e)}', exc_info=True)
        flash('An unexpected error occurred during Square sync.', 'error')
    
    return redirect(url_for('main.settings'))

@bp.route('/sync/square/catalog', methods=['POST'])
@login_required
def sync_square_catalog():
    """Manually trigger Square catalog sync"""
    try:
        from app.integrations.square import SquareIntegration
        
        # Check if Square access token is configured
        if not current_app.config.get('SQUARE_ACCESS_TOKEN'):
            flash('Square access token is not configured.', 'error')
            return redirect(url_for('main.settings'))
        
        # Perform sync
        square_integration = SquareIntegration()
        new_items, updated_items = square_integration.sync_catalog()
        
        # Provide feedback
        flash(f'Square catalog sync successful. New items: {new_items}, Updated items: {updated_items}', 'success')
        
    except ValueError as ve:
        flash(str(ve), 'error')
    except Exception as e:
        current_app.logger.error(f"Error during Square catalog sync: {str(e)}", exc_info=True)
        flash('An unexpected error occurred during Square catalog sync.', 'error')
    
    return redirect(url_for('main.settings'))

@bp.route('/orders/square/<order_id>/fulfillment', methods=['POST'])
@login_required
def update_square_fulfillment(order_id):
    """Update Square order fulfillment status"""
    try:
        from app.integrations.square import SquareIntegration
        
        status = request.form.get('status')
        if not status:
            flash('Fulfillment status is required.', 'error')
            return redirect(url_for('main.orders', platform='square'))
        
        # Get order to verify it exists
        order = Order.query.filter_by(platform='square', platform_order_id=order_id).first_or_404()
        
        # Update status in Square
        square_integration = SquareIntegration()
        if square_integration.update_fulfillment_status(order_id, status.upper()):
            # Update local status
            order.fulfillment_status = status.lower()
            db.session.commit()
            flash('Order fulfillment status updated successfully.', 'success')
        else:
            flash('Failed to update order fulfillment status in Square.', 'error')
            
    except Exception as e:
        current_app.logger.error(f'Error updating Square fulfillment status: {str(e)}', exc_info=True)
        flash('An unexpected error occurred while updating fulfillment status.', 'error')
    
    return redirect(url_for('main.orders', platform='square'))

@bp.route('/connect/etsy')
@login_required
def connect_etsy():
    """Start the Etsy OAuth flow"""
    # Check if Etsy API key is configured
    client_id = current_app.config.get('ETSY_API_KEY')
    if not client_id:
        flash('Etsy API key is not configured. Please set up your Etsy developer account.', 'error')
        return redirect(url_for('main.settings'))
    
    # Check if application is in development or production
    if current_app.config.get('FLASK_ENV') == 'development':
        flash('Note: Your Etsy application is pending approval. You may encounter authorization issues.', 'warning')
    
    redirect_uri = url_for('main.etsy_callback', _external=True)
    scopes = [
        'transactions.r',  # Read order transactions
        'listings.r',      # Read shop listings
        'shops.r',        # Read shop information
        'profile.r'       # Read user profile
    ]
    
    # Generate PKCE code verifier and challenge
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    
    # Store PKCE code verifier in session for later
    session['etsy_code_verifier'] = code_verifier
    
    # State parameter to prevent CSRF
    state = secrets.token_urlsafe(32)
    session['etsy_oauth_state'] = state
    
    # Construct the authorization URL
    auth_url = (
        'https://www.etsy.com/oauth/connect'
        f'?response_type=code'
        f'&client_id={client_id}'
        f'&redirect_uri={quote(redirect_uri)}'
        f'&scope={"%20".join(scopes)}'
        f'&state={state}'
        f'&code_challenge={code_challenge}'
        f'&code_challenge_method=S256'
    )
    
    return redirect(auth_url)

@bp.route('/connect/etsy/callback')
@login_required
def etsy_callback():
    """Handle the Etsy OAuth callback"""
    # Check for specific Etsy OAuth errors
    error = request.args.get('error')
    error_description = request.args.get('error_description', 'Unknown error')
    
    if error:
        if error == 'application_not_approved':
            flash(
                'Your Etsy application is not yet approved. '
                'Please complete the Etsy developer application process.', 
                'error'
            )
        elif error == 'invalid_scope':
            flash(
                'Invalid OAuth scopes. Please check your Etsy developer application settings.', 
                'error'
            )
        else:
            flash(f'Etsy authorization failed: {error_description}', 'error')
        
        return redirect(url_for('main.settings'))
    
    # Verify state to prevent CSRF
    state = request.args.get('state')
    if not state or state != session.get('etsy_oauth_state'):
        flash('Invalid OAuth state. Please try connecting again.', 'error')
        return redirect(url_for('main.settings'))
    
    # Get code verifier from session
    code_verifier = session.get('etsy_code_verifier')
    if not code_verifier:
        flash('Missing code verifier. Please try connecting again.', 'error')
        return redirect(url_for('main.settings'))
    
    # Exchange the code for an access token
    code = request.args.get('code')
    if not code:
        flash('No authorization code received. Please try connecting again.', 'error')
        return redirect(url_for('main.settings'))
    
    try:
        # Exchange the authorization code for access token
        client_id = current_app.config['ETSY_API_KEY']
        redirect_uri = url_for('main.etsy_callback', _external=True)
        
        response = requests.post(
            'https://api.etsy.com/v3/public/oauth/token',
            data={
                'grant_type': 'authorization_code',
                'client_id': client_id,
                'redirect_uri': redirect_uri,
                'code': code,
                'code_verifier': code_verifier
            }
        )
        
        if response.status_code != 200:
            # Log the full error response for debugging
            current_app.logger.error(f'Etsy token exchange failed: {response.text}')
            flash(
                'Failed to get access token. '
                'This may be due to an unapproved application or incorrect configuration.', 
                'error'
            )
            return redirect(url_for('main.settings'))
        
        token_data = response.json()
        
        # Store the tokens securely
        Setting.set_value('ETSY_ACCESS_TOKEN', token_data['access_token'], is_encrypted=True)
        Setting.set_value('ETSY_REFRESH_TOKEN', token_data['refresh_token'], is_encrypted=True)
        Setting.set_value('ETSY_TOKEN_EXPIRY', 
                         (datetime.utcnow() + timedelta(seconds=token_data['expires_in'])).isoformat())
        
        flash('Successfully connected to Etsy!', 'success')
        
    except Exception as e:
        current_app.logger.error(f'Error in Etsy OAuth callback: {str(e)}')
        flash(
            'An unexpected error occurred during Etsy authorization. '
            'Please check your application status in the Etsy Developer Portal.', 
            'error'
        )
    
    return redirect(url_for('main.settings'))

@bp.route('/logs/shipping')
@login_required
def get_shipping_logs():
    """Get the last 100 shipping-related log entries"""
    try:
        log_entries = []
        log_file = os.path.join('logs', 'beira.log')
        
        if os.path.exists(log_file):
            with open(log_file, 'r') as f:
                lines = f.readlines()
                # Get last 100 lines
                for line in lines[-100:]:
                    try:
                        # Try to parse as JSON first
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        # If not JSON, parse the standard log format
                        parts = line.split(' - ', 2)
                        if len(parts) >= 3:
                            timestamp = parts[0]
                            level = parts[1].strip()
                            message = parts[2].strip()
                            entry = {
                                'timestamp': timestamp,
                                'level': level,
                                'message': message
                            }
                        else:
                            continue
                    
                    # Only include shipping/tracking related logs
                    if any(keyword in entry.get('message', '').lower() 
                          for keyword in ['tracking', 'carrier', 'order']):
                        log_entries.append(entry)
        
        return jsonify(log_entries)
    except Exception as e:
        current_app.logger.error(f"Error fetching logs: {str(e)}")
        return jsonify({'error': 'Failed to fetch logs'}), 500
