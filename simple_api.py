from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "product-service"}

@app.get("/products")
def get_products():
    return [
        {"id": 1, "name": "Test Product 1", "price": 19.99, "stock": 100},
        {"id": 2, "name": "Test Product 2", "price": 29.99, "stock": 50}
    ]
