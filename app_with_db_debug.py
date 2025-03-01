from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, Float, MetaData, Table
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database connection
DB_HOST = os.getenv("DB_HOST", "yugabytedb.default.svc.cluster.local")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_USER = os.getenv("DB_USER", "yugabyte")
DB_PASSWORD = os.getenv("DB_PASSWORD", "yugabyte")
DB_NAME = os.getenv("DB_NAME", "productdb")

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

logger.info(f"Connecting to database: {DATABASE_URL}")

try:
    # SQLAlchemy setup
    engine = create_engine(DATABASE_URL)
    logger.info("Engine created")
    
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    # Product model
    class Product(Base):
        __tablename__ = "products"
        
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, index=True)
        description = Column(String, nullable=True)
        price = Column(Float)
        stock = Column(Integer)

    # Create tables
    logger.info("Creating tables")
    Base.metadata.create_all(bind=engine)
    logger.info("Tables created successfully")
except Exception as e:
    logger.error(f"Error setting up database: {e}")

# FastAPI app
app = FastAPI()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Endpoints
@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "product-service"}

@app.get("/products")
def get_products(db: Session = Depends(get_db)):
    try:
        products = db.query(Product).all()
        if not products:
            # Add some sample products if the table is empty
            sample_products = [
                Product(name="Test Product 1", description="A test product", price=19.99, stock=100),
                Product(name="Test Product 2", description="Another test product", price=29.99, stock=50)
            ]
            db.add_all(sample_products)
            db.commit()
            products = sample_products
        
        return products
    except Exception as e:
        logger.error(f"Error accessing products: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    try:
        product = db.query(Product).filter(Product.id == product_id).first()
        if product is None:
            raise HTTPException(status_code=404, detail="Product not found")
        return product
    except Exception as e:
        logger.error(f"Error accessing product {product_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
