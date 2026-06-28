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
        tables = inspector.get_table_names()
        if "notification_rules" in tables:
            rule_columns = [col["name"] for col in inspector.get_columns("notification_rules")]
            if "agencies" not in rule_columns:
                conn.execute(text("ALTER TABLE notification_rules ADD COLUMN agencies JSON DEFAULT '[]'"))
                conn.commit()
            if "categories" not in rule_columns:
                conn.execute(text("ALTER TABLE notification_rules ADD COLUMN categories JSON DEFAULT '[]'"))
                conn.commit()
            if "webhook_keyword" not in rule_columns:
                conn.execute(text("ALTER TABLE notification_rules ADD COLUMN webhook_keyword VARCHAR(128)"))
                conn.commit()

            # Re-fetch columns to check for 'name' column migration
            rule_columns = [col["name"] for col in inspector.get_columns("notification_rules")]
            if "name" not in rule_columns:
                # Drop the index on the old table first so SQLite doesn't complain about global index name conflict
                try:
                    conn.execute(text("DROP INDEX IF EXISTS ix_notification_rules_user_id"))
                    conn.commit()
                except Exception:
                    pass

                # We migrate the table to support multiple sets of rules
                conn.execute(text("ALTER TABLE notification_rules RENAME TO notification_rules_old"))
                conn.commit()
                
                # Recreate tables with the new schema
                Base.metadata.create_all(bind=engine)
                
                # Copy the data
                conn.execute(text("""
                    INSERT INTO notification_rules (
                        user_id, name, is_active, keywords, agencies, categories, 
                        countdown_days, channel_in_app, channel_email, email_to, 
                        channel_webhook, webhook_url, updated_at
                    )
                    SELECT 
                        user_id, '默认规则' as name, 1 as is_active, keywords, agencies, categories, 
                        countdown_days, channel_in_app, channel_email, email_to, 
                        channel_webhook, webhook_url, updated_at
                    FROM notification_rules_old
                """))
                conn.commit()
                
                conn.execute(text("DROP TABLE notification_rules_old"))
                conn.commit()
        elif "notification_rules_old" in tables:
            # Recovery path: table was renamed but recreation failed
            try:
                conn.execute(text("DROP INDEX IF EXISTS ix_notification_rules_user_id"))
                conn.commit()
            except Exception:
                pass

            Base.metadata.create_all(bind=engine)

            conn.execute(text("""
                INSERT INTO notification_rules (
                    user_id, name, is_active, keywords, agencies, categories, 
                    countdown_days, channel_in_app, channel_email, email_to, 
                    channel_webhook, webhook_url, updated_at
                )
                SELECT 
                    user_id, '默认规则' as name, 1 as is_active, keywords, agencies, categories, 
                    countdown_days, channel_in_app, channel_email, email_to, 
                    channel_webhook, webhook_url, updated_at
                FROM notification_rules_old
            """))
            conn.commit()
            
            conn.execute(text("DROP TABLE notification_rules_old"))
            conn.commit()
