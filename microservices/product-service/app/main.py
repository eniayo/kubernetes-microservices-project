import os
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from typing import List, Optional
import uvicorn
from app.models import Product, ProductCreate, ProductUpdate
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

@app.get("/products", response_model=List[Product])
async def get_products(
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_products as get_products_route
    return get_products_route(db, skip, limit)

@app.get("/products/{product_id}", response_model=Product)
async def get_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_product as get_product_route
    return get_product_route(db, product_id)

@app.post("/products", response_model=Product, status_code=201)
async def create_product(
    product: ProductCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import create_product as create_product_route
    return create_product_route(db, product)

@app.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int,
    product: ProductUpdate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import update_product as update_product_route
    return update_product_route(db, product_id, product)

@app.delete("/products/{product_id}", response_model=dict)
async def delete_product(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import delete_product as delete_product_route
    return delete_product_route(db, product_id)

@app.get("/products/{product_id}/stock")
async def check_product_stock(
    product_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_product as get_product_route
    product = get_product_route(db, product_id)
    return {"product_id": product_id, "in_stock": product.stock > 0, "stock": product.stock}

@app.post("/products/{product_id}/reserve")
async def reserve_product(
    product_id: int,
    quantity: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import reserve_product as reserve_product_route
    return reserve_product_route(db, product_id, quantity)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)