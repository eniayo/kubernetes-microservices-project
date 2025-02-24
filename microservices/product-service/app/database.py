import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import logging
from app.models import Base

logger = logging.getLogger(__name__)

# Get database connection details from environment variables
DB_HOST = os.getenv("DB_HOST", "yugabyte-service")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_USER = os.getenv("DB_USER", "yugabyte")
DB_PASSWORD = os.getenv("DB_PASSWORD", "yugabyte")
DB_NAME = os.getenv("DB_NAME", "productdb")

# Construct the database URL
SQLALCHEMY_DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create the SQLAlchemy engine
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,  # This helps with connection validation
    pool_size=5,         # Keep connection pool size limited for resource efficiency
    max_overflow=10,     # Allow up to 10 connections beyond pool_size
    pool_recycle=3600,   # Recycle connections after one hour
)

# Create a SessionLocal class
# Each instance of this class will be a database session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

async def init_db():
    """Initialize the database by creating all tables."""
    try:
        # Create all tables if they don't exist
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
        
        # Add some sample data if database is empty
        db = SessionLocal()
        from app.models import ProductModel
        
        if db.query(ProductModel).count() == 0:
            logger.info("Adding sample products to database")
            sample_products = [
                ProductModel(
                    name="Smartphone X",
                    description="Latest smartphone with advanced features",
                    price=999.99,
                    stock=50,
                    category="Electronics"
                ),
                ProductModel(
                    name="Laptop Pro",
                    description="High-performance laptop for professionals",
                    price=1499.99,
                    stock=30,
                    category="Electronics"
                ),
                ProductModel(
                    name="Wireless Headphones",
                    description="Noise-cancelling wireless headphones",
                    price=199.99,
                    stock=100,
                    category="Audio"
                ),
                ProductModel(
                    name="Smart Watch",
                    description="Fitness and health tracking smartwatch",
                    price=249.99,
                    stock=75,
                    category="Wearables"
                ),
                ProductModel(
                    name="Gaming Console",
                    description="Next-gen gaming console",
                    price=499.99,
                    stock=25,
                    category="Gaming"
                ),
            ]
            db.add_all(sample_products)
            db.commit()
            logger.info(f"Added {len(sample_products)} sample products")
        
        db.close()
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise

def get_db():
    """Dependency for getting the database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()