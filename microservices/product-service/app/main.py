import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from typing import List, Optional
import uvicorn
from app.models import Product, ProductCreate, ProductUpdate, ProductModel
from app.database import init_db, get_db, SessionLocal
from sqlalchemy.orm import Session
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Product Service API", version="0.1.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OPA endpoint
OPA_URL = os.getenv("OPA_URL", "http://opa.default.svc.cluster.local:8181/v1/data/productservice/allow")
# Order service endpoint
ORDER_SERVICE_URL = os.getenv("ORDER_SERVICE_URL", "http://order-service.default.svc.cluster.local:8000")

# Middleware for request timing (useful for monitoring)
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response

# Dependency to check OPA policies
async def check_policy(request: Request):
    # Skip OPA check during healthcheck
    if request.url.path == "/health":
        return True
        
    # Prepare input for OPA
    headers = dict(request.headers)
    method = request.method
    path = request.url.path
    
    input_data = {
        "input": {
            "method": method,
            "path": path,
            "headers": headers,
        }
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(OPA_URL, json=input_data)
            if response.status_code != 200:
                logger.error(f"OPA service error: {response.text}")
                raise HTTPException(status_code=403, detail="Policy check failed")
            
            result = response.json()
            if not result.get("result", False):
                raise HTTPException(status_code=403, detail="Request denied by policy")
                
    except httpx.RequestError as e:
        logger.error(f"Error connecting to OPA: {e}")
        # In case OPA is unreachable, we could define a fallback policy
        # For now, we'll allow the request to proceed to avoid blocking legitimate traffic
        logger.warning("OPA unreachable, applying fallback policy (allow request)")
        return True
        
    return True

# Database initialization
@app.on_event("startup")
async def startup_event():
    await init_db()
    logger.info("Database initialized")

# Routes
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "product-service"}

# Implement route functions directly instead of importing

@app.get("/products", response_model=List[Product])
async def get_products(
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    """Get all products with pagination"""
    return db.query(ProductModel).offset(skip).limit(limit).all()

@app.get("/products/{product_id}", response_model=Product)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    """Get a specific product by ID"""
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")
    return product

@app.post("/products", response_model=Product, status_code=201)
async def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
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

@app.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int,
    product_update: ProductUpdate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    """Update an existing product"""
    db_product = get_product(db, product_id)
    
    # Update only provided fields
    update_data = product_update.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_product, key, value)
        
    db.commit()
    db.refresh(db_product)
    logger.info(f"Updated product: {db_product.name} (ID: {db_product.id})")
    return db_product

@app.delete("/products/{product_id}", response_model=dict)
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    """Delete a product"""
    db_product = get_product(db, product_id)
    db.delete(db_product)
    db.commit()
    logger.info(f"Deleted product ID: {product_id}")
    return {"success": True, "message": f"Product {product_id} deleted"}

@app.get("/products/{product_id}/stock")
async def check_product_stock(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")
    return {"product_id": product_id, "in_stock": product.stock > 0, "stock": product.stock}

@app.post("/products/{product_id}/reserve")
async def reserve_product(
    product_id: int,
    quantity: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    """Reserve products by reducing stock"""
    product = db.query(ProductModel).filter(ProductModel.id == product_id).first()
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product with ID {product_id} not found")
    
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

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)