from sqlalchemy.orm import Session
from fastapi import HTTPException
from typing import List, Optional
import logging
from app.models import ProductModel, ProductCreate, ProductUpdate

logger = logging.getLogger(__name__)

def get_products(db: Session, skip: int = 0, limit: int = 100):
    """Get all products with pagination"""
    return db.query(ProductModel).offset(skip).limit(limit).all()

def get_product(db: Session, product_id: int):
    """Get a specific product by ID"""
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")
    return product

def get_products_by_category(db: Session, category: str, skip: int = 0, limit: int = 100):
    """Get products filtered by category"""
    return db.query(ProductModel).filter(
        ProductModel.category == category
    ).offset(skip).limit(limit).all()

def create_product(db: Session, product: ProductCreate):
    """Create a new product"""
    db_product = ProductModel(
        name=product.name,
        description=product.description,
        price=product.price,
        stock=product.stock,
        category=product.category
    )
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    logger.info(f"Created new product: {db_product.name} (ID: {db_product.id})")
    return db_product

def update_product(db: Session, product_id: int, product_update: ProductUpdate):
    """Update an existing product"""
    db_product = get_product(db, product_id)
    
    
    update_data = product_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_product, key, value)
        
    db.commit()
    db.refresh(db_product)
    logger.info(f"Updated product: {db_product.name} (ID: {db_product.id})")
    return db_product

def delete_product(db: Session, product_id: int):
    """Delete a product"""
    db_product = get_product(db, product_id)
    db.delete(db_product)
    db.commit()
    logger.info(f"Deleted product ID: {product_id}")
    return {"success": True, "message": f"Product {product_id} deleted"}

def reserve_product(db: Session, product_id: int, quantity: int):
    """Reserve products by reducing stock"""
    product = get_product(db, product_id)
    
    if product.stock < quantity:
        raise HTTPException(
            status_code=400, 
            detail=f"Not enough stock available. Requested: {quantity}, Available: {product.stock}"
        )
    
    product.stock -= quantity
    db.commit()
    db.refresh(product)
    logger.info(f"Reserved {quantity} units of product ID: {product_id}")
    
    return {
        "success": True,
        "product_id": product_id,
        "reserved_quantity": quantity,
        "remaining_stock": product.stock
    }