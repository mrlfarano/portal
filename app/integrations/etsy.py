from flask import current_app, url_for
import requests
from app.models import Order, Customer, Setting
from app import db
from datetime import datetime, timedelta
import logging
import json
from typing import Tuple
import base64

logger = logging.getLogger(__name__)

class EtsyIntegration:
    def __init__(self):
        self.client_id = current_app.config.get('ETSY_API_KEY')
        self.client_secret = current_app.config.get('ETSY_SHARED_SECRET')
        if not self.client_id or not self.client_secret:
            raise ValueError("Etsy API credentials not configured")
        
        self.base_url = "https://api.etsy.com/v3"
        self.token_url = "https://api.etsy.com/v3/public/oauth/token"
        
        # Get stored access token
        self.access_token = Setting.get_value('ETSY_ACCESS_TOKEN')
        self.refresh_token = Setting.get_value('ETSY_REFRESH_TOKEN')
        self.token_expiry = Setting.get_value('ETSY_TOKEN_EXPIRY')
        
        if not self.access_token:
            raise ValueError("Not connected to Etsy. Please connect your Etsy account first.")
        
        # Check if token is expired and refresh if needed
        if self.token_expiry:
            expiry = datetime.fromisoformat(self.token_expiry)
            if datetime.utcnow() >= expiry:
                self._refresh_token()
        
        self.headers = {
            "Authorization": f"Bearer {self.access_token}",
            "x-api-key": self.client_id,
            "Accept": "application/json"
        }

    def _refresh_token(self):
        """Refresh the OAuth access token"""
        try:
            response = requests.post(
                self.token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.refresh_token,
                    "client_id": self.client_id
                },
                auth=(self.client_id, self.client_secret)
            )
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data['access_token']
            self.refresh_token = token_data['refresh_token']
            
            # Update stored tokens
            Setting.set_value('ETSY_ACCESS_TOKEN', self.access_token, is_encrypted=True)
            Setting.set_value('ETSY_REFRESH_TOKEN', self.refresh_token, is_encrypted=True)
            Setting.set_value('ETSY_TOKEN_EXPIRY', 
                            (datetime.utcnow() + timedelta(seconds=token_data['expires_in'])).isoformat())
            
            # Update headers with new token
            self.headers["Authorization"] = f"Bearer {self.access_token}"
            
        except Exception as e:
            logger.error(f"Failed to refresh Etsy token: {str(e)}")
            raise

    def _make_request(self, endpoint: str, method: str = "GET", params: dict = None) -> dict:
        """Make a request to the Etsy API"""
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                params=params
            )
            
            if response.status_code == 401 and self.refresh_token:
                # Token might be expired, try to refresh and retry
                self._refresh_token()
                response = requests.request(
                    method=method,
                    url=url,
                    headers=self.headers,
                    params=params
                )
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Etsy API request failed: {str(e)}")
            raise

    def get_shop_id(self) -> str:
        """Get the shop ID for the authenticated user"""
        try:
            response = self._make_request("application/shops")
            shops = response.get("results", [])
            if not shops:
                raise ValueError("No Etsy shops found")
            return shops[0]["shop_id"]
        except Exception as e:
            logger.error(f"Failed to get Etsy shop ID: {str(e)}")
            raise

    def sync_orders(self, days_back: int = 30) -> Tuple[int, int]:
        """
        Sync orders from Etsy for the last X days.
        
        Args:
            days_back (int): Number of days to look back for orders
        
        Returns:
            tuple: (new_orders, updated_orders) counts
        """
        try:
            logger.info(f"Starting Etsy order sync for last {days_back} days")
            
            # Get shop ID
            shop_id = self.get_shop_id()
            
            # Get orders
            response = self._make_request(
                f"application/shops/{shop_id}/receipts",
                params={
                    "limit": 100,  # Adjust based on your needs
                    "was_paid": True
                }
            )
            
            orders = response.get("results", [])
            new_orders = 0
            updated_orders = 0
            
            for etsy_order in orders:
                # Check if order already exists
                order = Order.query.filter_by(
                    platform='etsy',
                    platform_order_id=str(etsy_order['receipt_id'])
                ).first()
                
                # Get or create customer
                customer = Customer.query.filter_by(email=etsy_order['buyer_email']).first()
                if not customer:
                    customer = Customer(
                        email=etsy_order['buyer_email'],
                        name=f"{etsy_order['buyer_first_name']} {etsy_order['buyer_last_name']}",
                    )
                    db.session.add(customer)
                
                # Parse address
                shipping_address = {
                    'name': etsy_order['shipping_name'],
                    'address1': etsy_order['first_line'],
                    'address2': etsy_order.get('second_line', ''),
                    'city': etsy_order['city'],
                    'state': etsy_order['state'],
                    'zip': etsy_order['zip'],
                    'country': etsy_order['country_iso']
                }
                
                if order:
                    # Update existing order
                    order.status = 'shipped' if etsy_order['was_shipped'] else 'pending'
                    order.total_amount = float(etsy_order['total_price']['amount'] / etsy_order['total_price']['divisor'])
                    order.shipping_address = json.dumps(shipping_address)
                    
                    # Update tracking information
                    if etsy_order.get('was_shipped'):
                        shipping_carrier = etsy_order.get('shipping_carrier', '').upper()
                        tracking_number = etsy_order.get('tracking_code')
                        
                        logger.info(f"Found shipping info for Etsy order {etsy_order['receipt_id']}: "
                                  f"Carrier={shipping_carrier}, Tracking={tracking_number}")
                        
                        order.shipping_carrier = shipping_carrier
                        order.tracking_number = tracking_number
                        
                        if order.shipping_carrier and order.tracking_number:
                            logger.info(f"Updated tracking for order {order.id}: {order.shipping_carrier} - {order.tracking_number}")
                        else:
                            logger.warning(f"Missing carrier or tracking for shipped order {order.id}")
                    
                    updated_orders += 1
                else:
                    # Create new order
                    order = Order(
                        platform='etsy',
                        platform_order_id=str(etsy_order['receipt_id']),
                        customer=customer,
                        order_date=datetime.fromisoformat(etsy_order['created_timestamp']),
                        status='shipped' if etsy_order['was_shipped'] else 'pending',
                        total_amount=float(etsy_order['total_price']['amount'] / etsy_order['total_price']['divisor']),
                        shipping_address=json.dumps(shipping_address),
                        # Add tracking information
                        shipping_carrier=etsy_order.get('shipping_carrier', '').upper() if etsy_order.get('was_shipped') else None,
                        tracking_number=etsy_order.get('tracking_code') if etsy_order.get('was_shipped') else None
                    )
                    if order.shipping_carrier and order.tracking_number:
                        logger.info(f"Found tracking for new order: {order.shipping_carrier} - {order.tracking_number}")
                    
                    db.session.add(order)
                    new_orders += 1
            
            db.session.commit()
            
            # Update last sync time
            Setting.set_value('ETSY_LAST_SYNC', datetime.utcnow().isoformat())
            
            logger.info(f"Etsy sync complete. New orders: {new_orders}, Updated orders: {updated_orders}")
            return new_orders, updated_orders
            
        except Exception as e:
            logger.error(f"Error syncing Etsy orders: {str(e)}", exc_info=True)
            db.session.rollback()
            raise
