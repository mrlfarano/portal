from app import db
from flask_login import UserMixin
from datetime import datetime
from app import login_manager
from typing import Any, Dict, List, Optional, Union
from sqlalchemy.orm import Mapped, mapped_column, relationship
from enum import Enum

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    __allow_unmapped__ = True
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    email: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    google_id: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(db.String(120))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

class Customer(db.Model):
    __tablename__ = 'customer'
    __allow_unmapped__ = True
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    email: Mapped[Optional[str]] = mapped_column(db.String(120), unique=True)
    name: Mapped[Optional[str]] = mapped_column(db.String(120))
    phone: Mapped[Optional[str]] = mapped_column(db.String(20))
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)
    orders: Mapped[List['Order']] = relationship('Order', back_populates='customer', lazy=True)
    messages: Mapped[List['Message']] = relationship('Message', back_populates='customer', lazy=True)

class Product(db.Model):
    """Model for products from various platforms"""
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(20), nullable=False)  # 'etsy', 'square'
    platform_product_id = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float)
    sku = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    line_items = db.relationship('OrderLineItem', back_populates='product')
    
    __table_args__ = (
        db.UniqueConstraint('platform', 'platform_product_id', name='uix_platform_product'),
    )

class OrderLineItem(db.Model):
    """Model for order line items"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False, default=1)
    price = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    order = db.relationship('Order', back_populates='line_items')
    product = db.relationship('Product', back_populates='line_items')

class Platform(str, Enum):
    ETSY = 'etsy'
    SQUARE = 'square'

class Order(db.Model):
    """Model for orders from various platforms"""
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.Enum(Platform), nullable=False)
    platform_order_id = db.Column(db.String(100), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'))
    order_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20))  # Platform-specific order status
    fulfillment_status = db.Column(db.String(20))  # Shipping/fulfillment status
    total_amount = db.Column(db.Float)
    shipping_address = db.Column(db.Text)  # JSON string of address details
    
    # Shipping and tracking fields
    shipping_carrier = db.Column(db.String(50))
    tracking_number = db.Column(db.String(100))
    tracking_status = db.Column(db.String(50))
    tracking_url = db.Column(db.String(500))
    tracking_updated_at = db.Column(db.DateTime)
    estimated_delivery_date = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = db.relationship('Customer', back_populates='orders')
    line_items = db.relationship('OrderLineItem', back_populates='order', cascade='all, delete-orphan')
    
    __table_args__ = (
        db.UniqueConstraint('platform', 'platform_order_id', name='uix_platform_order'),
    )

class Message(db.Model):
    __tablename__ = 'message'
    __allow_unmapped__ = True
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(db.Integer, db.ForeignKey('customer.id'))
    content: Mapped[str] = mapped_column(db.Text)
    platform: Mapped[str] = mapped_column(db.String(20))
    platform_message_id: Mapped[str] = mapped_column(db.String(120))
    sent_at: Mapped[datetime] = mapped_column(db.DateTime)
    created_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow)

    customer: Mapped['Customer'] = relationship('Customer', back_populates='messages')

class Setting(db.Model):
    __tablename__ = 'setting'
    __allow_unmapped__ = True
    id: Mapped[int] = mapped_column(db.Integer, primary_key=True)
    key: Mapped[str] = mapped_column(db.String(120), unique=True, nullable=False)
    value: Mapped[Optional[str]] = mapped_column(db.Text)
    is_encrypted: Mapped[bool] = mapped_column(db.Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def get_value(cls, key: str, default: Any = None) -> Any:
        setting = cls.query.filter_by(key=key).first()
        if setting is None:
            return default
        return setting.value

    @classmethod
    def set_value(cls, key: str, value: str, is_encrypted: bool = True) -> None:
        setting = cls.query.filter_by(key=key).first()
        if setting is None:
            setting = cls(key=key)
        setting.value = value
        setting.is_encrypted = is_encrypted
        db.session.add(setting)
        db.session.commit()
