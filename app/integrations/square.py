from flask import current_app
from square.client import Client
from app.models import Order, Customer, Setting, Product, OrderLineItem
from app import db
from datetime import datetime, timedelta
import logging
import json
from typing import Tuple

logger = logging.getLogger(__name__)

class SquareIntegration:
    def __init__(self):
        self.access_token = current_app.config.get('SQUARE_ACCESS_TOKEN')
        if not self.access_token:
            raise ValueError("Square access token not configured")
        
        # Initialize Square client
        self.client = Client(
            access_token=self.access_token,
            environment='sandbox'  # Change to 'production' for live environment
        )

    def get_location_id(self) -> str:
        """Get the first location ID for the account"""
        try:
            result = self.client.locations.list_locations()
            if result.is_success():
                locations = result.body.get('locations', [])
                if not locations:
                    raise ValueError("No Square locations found")
                return locations[0]['id']
            elif result.is_error():
                logger.error(f"Failed to get Square locations: {result.errors}")
                raise ValueError(f"Square API error: {result.errors}")
        except Exception as e:
            logger.error(f"Failed to get Square location ID: {str(e)}")
            raise

    def sync_catalog(self) -> Tuple[int, int]:
        """
        Sync catalog items from Square.
        
        Returns:
            tuple: (new_items, updated_items) counts
        """
        try:
            logger.info("Starting Square catalog sync")
            
            result = self.client.catalog.list_catalog(
                types="ITEM"
            )
            
            if result.is_error():
                logger.error(f"Failed to get Square catalog: {result.errors}")
                raise ValueError(f"Square API error: {result.errors}")
            
            items = result.body.get('objects', [])
            new_items = 0
            updated_items = 0
            
            for item in items:
                item_data = item['item_data']
                # Get variations for pricing
                variations = item_data.get('variations', [])
                if not variations:
                    continue
                
                # Use the first variation's price as default
                variation = variations[0]
                price_money = variation.get('item_variation_data', {}).get('price_money', {})
                price = float(price_money.get('amount', 0)) / 100 if price_money else 0
                
                # Get or create product
                product = Product.query.filter_by(
                    platform='square',
                    platform_product_id=item['id']
                ).first()
                
                if product:
                    # Update existing product
                    product.name = item_data.get('name', '')
                    product.description = item_data.get('description', '')
                    product.price = price
                    product.sku = variation.get('item_variation_data', {}).get('sku', '')
                    updated_items += 1
                else:
                    # Create new product
                    product = Product(
                        platform='square',
                        platform_product_id=item['id'],
                        name=item_data.get('name', ''),
                        description=item_data.get('description', ''),
                        price=price,
                        sku=variation.get('item_variation_data', {}).get('sku', '')
                    )
                    db.session.add(product)
                    new_items += 1
            
            db.session.commit()
            logger.info(f"Square catalog sync complete. New items: {new_items}, Updated items: {updated_items}")
            return new_items, updated_items
            
        except Exception as e:
            logger.error(f"Error syncing Square catalog: {str(e)}", exc_info=True)
            db.session.rollback()
            raise

    def update_fulfillment_status(self, order_id: str, status: str) -> bool:
        """
        Update the fulfillment status of a Square order.
        
        Args:
            order_id (str): Square order ID
            status (str): New fulfillment status (PROPOSED, RESERVED, PREPARED, COMPLETED, CANCELED, FAILED)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get order to find fulfillment ID
            result = self.client.orders.retrieve_order(
                order_id=order_id
            )
            
            if result.is_error():
                logger.error(f"Failed to get Square order: {result.errors}")
                return False
            
            order = result.body.get('order')
            if not order:
                return False
            
            # Get the first shipment fulfillment
            fulfillment_id = None
            for fulfillment in order.get('fulfillments', []):
                if fulfillment.get('type') == 'SHIPMENT':
                    fulfillment_id = fulfillment.get('uid')
                    break
            
            if not fulfillment_id:
                logger.error(f"No shipment fulfillment found for order {order_id}")
                return False
            
            # Update fulfillment status
            result = self.client.orders.update_order(
                order_id=order_id,
                body={
                    "order": {
                        "fulfillments": [
                            {
                                "uid": fulfillment_id,
                                "state": status
                            }
                        ],
                        "version": order.get('version')
                    }
                }
            )
            
            if result.is_error():
                logger.error(f"Failed to update Square order fulfillment: {result.errors}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating Square fulfillment status: {str(e)}", exc_info=True)
            return False

    def sync_orders(self, days_back: int = 30) -> Tuple[int, int]:
        """
        Sync orders from Square for the last X days.
        
        Args:
            days_back (int): Number of days to look back for orders
        
        Returns:
            tuple: (new_orders, updated_orders) counts
        """
        try:
            logger.info(f"Starting Square order sync for last {days_back} days")
            
            # Get location ID
            location_id = self.get_location_id()
            
            # Calculate date range
            end_time = datetime.utcnow()
            start_time = end_time - timedelta(days=days_back)
            
            # Get orders
            result = self.client.orders.search_orders(
                body={
                    "location_ids": [location_id],
                    "query": {
                        "filter": {
                            "date_time_filter": {
                                "created_at": {
                                    "start_at": start_time.isoformat(),
                                    "end_at": end_time.isoformat()
                                }
                            },
                            "state_filter": {
                                "states": ["COMPLETED"]
                            }
                        }
                    }
                }
            )
            
            if result.is_error():
                logger.error(f"Failed to get Square orders: {result.errors}")
                raise ValueError(f"Square API error: {result.errors}")
            
            orders = result.body.get('orders', [])
            new_orders = 0
            updated_orders = 0
            
            for square_order in orders:
                # Check if order already exists
                order = Order.query.filter_by(
                    platform='square',
                    platform_order_id=square_order['id']
                ).first()
                
                # Get customer information
                customer_id = square_order.get('customer_id')
                customer_info = None
                if customer_id:
                    customer_result = self.client.customers.retrieve_customer(customer_id=customer_id)
                    if customer_result.is_success():
                        customer_info = customer_result.body.get('customer')
                
                # Get or create customer
                customer = None
                if customer_info and customer_info.get('email_address'):
                    customer = Customer.query.filter_by(email=customer_info['email_address']).first()
                    if not customer:
                        customer = Customer(
                            email=customer_info['email_address'],
                            name=f"{customer_info.get('given_name', '')} {customer_info.get('family_name', '')}".strip(),
                        )
                        db.session.add(customer)
                
                # Parse line items
                line_items = []
                for item in square_order.get('line_items', []):
                    catalog_item_id = item.get('catalog_object_id')
                    if catalog_item_id:
                        product = Product.query.filter_by(
                            platform='square',
                            platform_product_id=catalog_item_id
                        ).first()
                        
                        if product:
                            line_items.append({
                                'product_id': product.id,
                                'quantity': int(item.get('quantity', 1)),
                                'price': float(item.get('base_price_money', {}).get('amount', 0)) / 100
                            })
                
                # Parse fulfillments for shipping address and tracking
                shipping_address = {}
                fulfillment_status = None
                shipping_carrier = None
                tracking_number = None
                
                for fulfillment in square_order.get('fulfillments', []):
                    if fulfillment.get('type') == 'SHIPMENT':
                        # Get shipping address
                        address = fulfillment['shipment_details'].get('recipient', {}).get('address', {})
                        shipping_address = {
                            'name': f"{fulfillment['shipment_details']['recipient'].get('display_name', '')}",
                            'address1': address.get('address_line_1', ''),
                            'address2': address.get('address_line_2', ''),
                            'city': address.get('locality', ''),
                            'state': address.get('administrative_district_level_1', ''),
                            'zip': address.get('postal_code', ''),
                            'country': address.get('country', 'US')
                        }
                        fulfillment_status = fulfillment.get('state', 'PROPOSED').lower()
                        
                        # Get tracking information
                        shipment_details = fulfillment.get('shipment_details', {})
                        if shipment_details:
                            shipping_carrier = shipment_details.get('carrier')
                            tracking_number = shipment_details.get('tracking_number')
                            
                            logger.info(f"Found shipping info for Square order {square_order['id']}: "
                                      f"Carrier={shipping_carrier}, Tracking={tracking_number}")
                            
                            if shipping_carrier and tracking_number:
                                logger.info(f"Found valid tracking for order: {shipping_carrier} - {tracking_number}")
                            else:
                                logger.warning(f"Incomplete shipping info for order {square_order['id']}")
                        break
                
                # Calculate total amount
                total_money = square_order.get('total_money', {})
                total_amount = float(total_money.get('amount', 0)) / 100  # Convert from cents
                
                if order:
                    # Update existing order
                    order.status = square_order.get('state', 'UNKNOWN').lower()
                    order.fulfillment_status = fulfillment_status
                    order.total_amount = total_amount
                    if shipping_address:
                        order.shipping_address = json.dumps(shipping_address)
                    if customer:
                        order.customer = customer
                    
                    # Update tracking information
                    if shipping_carrier and tracking_number:
                        order.shipping_carrier = shipping_carrier.upper()
                        order.tracking_number = tracking_number
                    
                    # Update line items
                    order.line_items = []  # Clear existing items
                    for item_data in line_items:
                        line_item = OrderLineItem(
                            order=order,
                            product_id=item_data['product_id'],
                            quantity=item_data['quantity'],
                            price=item_data['price']
                        )
                        db.session.add(line_item)
                    
                    updated_orders += 1
                else:
                    # Create new order
                    order = Order(
                        platform='square',
                        platform_order_id=square_order['id'],
                        customer=customer,
                        order_date=datetime.fromisoformat(square_order['created_at']),
                        status=square_order.get('state', 'UNKNOWN').lower(),
                        fulfillment_status=fulfillment_status,
                        total_amount=total_amount,
                        shipping_address=json.dumps(shipping_address) if shipping_address else None,
                        # Add tracking information
                        shipping_carrier=shipping_carrier.upper() if shipping_carrier else None,
                        tracking_number=tracking_number
                    )
                    db.session.add(order)
                    
                    # Add line items
                    for item_data in line_items:
                        line_item = OrderLineItem(
                            order=order,
                            product_id=item_data['product_id'],
                            quantity=item_data['quantity'],
                            price=item_data['price']
                        )
                        db.session.add(line_item)
                    
                    new_orders += 1
            
            db.session.commit()
            
            # Update last sync time
            Setting.set_value('SQUARE_LAST_SYNC', datetime.utcnow().isoformat())
            
            logger.info(f"Square sync complete. New orders: {new_orders}, Updated orders: {updated_orders}")
            return new_orders, updated_orders
            
        except Exception as e:
            logger.error(f"Error syncing Square orders: {str(e)}", exc_info=True)
            db.session.rollback()
            raise
