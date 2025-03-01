import os
from app.routes import internal_router
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import httpx
import logging
from typing import List, Optional
import uvicorn
from app.models import Order, OrderCreate, OrderUpdate, OrderItem
from app.database import init_db, get_db, SessionLocal
from sqlalchemy.orm import Session
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Order Service API", version="0.1.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OPA endpoint
OPA_URL = os.getenv("OPA_URL", "http://opa.default.svc.cluster.local:8181/v1/data/orderservice/allow")
# Product service endpoint
PRODUCT_SERVICE_URL = os.getenv("PRODUCT_SERVICE_URL", "http://product-service.default.svc.cluster.local:8000")

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
    return {"status": "healthy", "service": "order-service"}

@app.get("/orders", response_model=List[Order])
async def get_orders(
    skip: int = 0, 
    limit: int = 100,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_orders as get_orders_route
    return get_orders_route(db, skip, limit)

@app.get("/orders/{order_id}", response_model=Order)
async def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_order as get_order_route
    return get_order_route(db, order_id)

@app.post("/orders", response_model=Order, status_code=201)
async def create_order(
    order: OrderCreate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    # Check and reserve product stock with the product service
    for item in order.items:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{PRODUCT_SERVICE_URL}/products/{item.product_id}/reserve",
                    params={"quantity": item.quantity}
                )
                if response.status_code != 200:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Failed to reserve product {item.product_id}: {response.text}"
                    )
        except httpx.RequestError as e:
            logger.error(f"Error connecting to product service: {e}")
            raise HTTPException(
                status_code=503,
                detail="Product service unavailable, cannot complete order"
            )
    
    from app.routes import create_order as create_order_route
    return create_order_route(db, order)

@app.put("/orders/{order_id}", response_model=Order)
async def update_order(
    order_id: int,
    order: OrderUpdate,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import update_order as update_order_route
    return update_order_route(db, order_id, order)

@app.delete("/orders/{order_id}", response_model=dict)
async def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import cancel_order as cancel_order_route
    return cancel_order_route(db, order_id)

@app.get("/orders/customer/{customer_id}", response_model=List[Order])
async def get_customer_orders(
    customer_id: str,
    db: Session = Depends(get_db),
    _: bool = Depends(check_policy)
):
    from app.routes import get_customer_orders as get_customer_orders_route
    return get_customer_orders_route(db, customer_id)

app.include_router(internal_router, prefix="/internal", tags=["internal"])

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)