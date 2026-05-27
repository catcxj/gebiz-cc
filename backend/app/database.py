from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401
    from sqlalchemy import inspect, text
    
    # 1. Create tables (new tables will be created automatically)
    Base.metadata.create_all(bind=engine)
    
    # 2. Schema migration: Add missing columns if database already exists
    with engine.connect() as conn:
        inspector = inspect(engine)
        
        # Check 'opportunities' table columns
        opp_columns = [col["name"] for col in inspector.get_columns("opportunities")]
        if "reference_no" not in opp_columns:
            conn.execute(text("ALTER TABLE opportunities ADD COLUMN reference_no VARCHAR(64)"))
            conn.commit()
            
        # Check 'notification_rules' table columns
        rule_columns = [col["name"] for col in inspector.get_columns("notification_rules")]
        if "agencies" not in rule_columns:
            conn.execute(text("ALTER TABLE notification_rules ADD COLUMN agencies JSON DEFAULT '[]'"))
            conn.commit()
        if "categories" not in rule_columns:
            conn.execute(text("ALTER TABLE notification_rules ADD COLUMN categories JSON DEFAULT '[]'"))
            conn.commit()
