from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
import logging
import httpx
import os
from app.models import OrderModel, OrderItemModel, OrderCreate, OrderUpdate, OrderStatus

logger = logging.getLogger(__name__)

# Product service URL for verifying products
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service.default.svc.cluster.local:8000")

# Create a router for internal endpoints
internal_router = APIRouter()

# List of trusted services that can access internal endpoints
TRUSTED_SERVICES = ["product-service", "inventory-service"]

# Dependency to check service identity
async def verify_service_identity(x_service_id: str = Header(None)):
    if not x_service_id or x_service_id not in TRUSTED_SERVICES:
        logger.warning(f"Unauthorized access attempt with service ID: {x_service_id}")
        raise HTTPException(
            status_code=403, 
            detail="Access forbidden: Service identity verification failed"
        )
    logger.info(f"Authorized access from service: {x_service_id}")
    return x_service_id

# Internal endpoint that only trusted services can access
@internal_router.get("/", dependencies=[Depends(verify_service_identity)])
async def internal_endpoint():
    """Internal endpoint that returns sensitive information only for other services."""
    return {
        "message": "This is internal service data",
        "data": {
            "service_health": "optimal",
            "db_connection_pool": 12,
            "current_processing_capacity": "85%"
        }
    }

def get_orders(db: Session, skip: int = 0, limit: int = 100):
    """Get all orders with pagination"""
    return db.query(OrderModel).offset(skip).limit(limit).all()

def get_order(db: Session, order_id: int):
    """Get a specific order by ID"""
    order = db.query(OrderModel).filter(OrderModel.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order with ID {order_id} not found")
    return order

def get_customer_orders(db: Session, customer_id: str, skip: int = 0, limit: int = 100):
    """Get all orders for a specific customer"""
    return db.query(OrderModel).filter(
        OrderModel.customer_id == customer_id
    ).offset(skip).limit(limit).all()

def create_order(db: Session, order: OrderCreate):
    """Create a new order"""
    # Calculate total amount
    total_amount = 0
    order_items = []
    
    for item in order.items:
        order_item = OrderItemModel(
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.unit_price or 0  # If unit_price not provided, we'll update it below
        )
        order_items.append(order_item)
        total_amount += item.quantity * (item.unit_price or 0)
    
    # Create the order record
    db_order = OrderModel(
        customer_id=order.customer_id,
        shipping_address=order.shipping_address,
        status=OrderStatus.PENDING.value,
        total_amount=total_amount,
        items=order_items
    )
    
    db.add(db_order)
    db.commit()
    db.refresh(db_order)
    logger.info(f"Created new order ID: {db_order.id} for customer: {db_order.customer_id}")
    return db_order

def update_order(db: Session, order_id: int, order_update: OrderUpdate):
    """Update an existing order"""
    db_order = get_order(db, order_id)
    
    # Can only update certain fields if order is not delivered or cancelled
    if db_order.status in [OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value]:
        if order_update.status and order_update.status != db_order.status:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot update order in {db_order.status} status"
            )
    
    # Update only provided fields
    update_data = order_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        # Convert enum to string value if it's an enum
        if isinstance(value, OrderStatus):
            value = value.value
        setattr(db_order, key, value)
        
    db.commit()
    db.refresh(db_order)
    logger.info(f"Updated order ID: {db_order.id}, new status: {db_order.status}")
    return db_order

def cancel_order(db: Session, order_id: int):
    """Cancel an order"""
    db_order = get_order(db, order_id)
    
    # Can only cancel if not already delivered or cancelled
    if db_order.status in [OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel order in {db_order.status} status"
        )
    
    # Update status to cancelled
    db_order.status = OrderStatus.CANCELLED.value
    db.commit()
    logger.info(f"Cancelled order ID: {order_id}")
    
    return {"success": True, "message": f"Order {order_id} cancelled"}

# Export the internal_router so it can be imported in main.py
__all__ = [
    "get_orders", 
    "get_order", 
    "create_order", 
    "update_order", 
    "cancel_order", 
    "get_customer_orders",
    "internal_router"
]