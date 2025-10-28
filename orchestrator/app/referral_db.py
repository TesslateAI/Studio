"""
Referral tracking database - separate SQLite database for tracking referrals.
"""
import sqlite3
from datetime import datetime
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Database file location
DB_PATH = Path("/app/referrals.db")

def init_db():
    """Initialize the referral tracking database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Table for tracking when someone lands on the site via referral
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referral_landings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referred_by TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            landing_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Table for tracking when someone actually signs up via referral
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referral_conversions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referred_by TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            conversion_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info(f"Referral database initialized at {DB_PATH}")

def save_landing(referred_by: str, ip_address: str = None, user_agent: str = None):
    """Save a landing (someone visited the site via referral link)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO referral_landings (referred_by, ip_address, user_agent) VALUES (?, ?, ?)",
            (referred_by, ip_address, user_agent)
        )
        conn.commit()
        conn.close()
        logger.info(f"Saved referral landing for: {referred_by}")
    except Exception as e:
        logger.error(f"Failed to save referral landing: {e}")

def save_conversion(referred_by: str, user_id: str, username: str, email: str, name: str):
    """Save a conversion (someone who came via referral actually signed up)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO referral_conversions (referred_by, user_id, username, email, name) VALUES (?, ?, ?, ?, ?)",
            (referred_by, user_id, username, email, name)
        )
        conn.commit()
        conn.close()
        logger.info(f"Saved referral conversion for: {referred_by} -> {username}")
    except Exception as e:
        logger.error(f"Failed to save referral conversion: {e}")

def get_all_referral_stats():
    """Get statistics for all referrers."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Get all unique referrers from both tables
        cursor.execute("""
            SELECT DISTINCT referred_by FROM (
                SELECT referred_by FROM referral_landings
                UNION
                SELECT referred_by FROM referral_conversions
            )
        """)
        
        referrers = [row[0] for row in cursor.fetchall()]
        
        stats = []
        for referrer in referrers:
            # Count landings
            cursor.execute(
                "SELECT COUNT(*) FROM referral_landings WHERE referred_by = ?",
                (referrer,)
            )
            landings = cursor.fetchone()[0]
            
            # Count conversions
            cursor.execute(
                "SELECT COUNT(*) FROM referral_conversions WHERE referred_by = ?",
                (referrer,)
            )
            conversions = cursor.fetchone()[0]
            
            # Get latest conversion details if any
            cursor.execute(
                "SELECT username, email, conversion_time FROM referral_conversions WHERE referred_by = ? ORDER BY conversion_time DESC LIMIT 1",
                (referrer,)
            )
            latest = cursor.fetchone()
            
            stats.append({
                "referrer": referrer,
                "landings": landings,
                "conversions": conversions,
                "conversion_rate": round((conversions / landings * 100) if landings > 0 else 0, 1),
                "latest_conversion": {
                    "username": latest[0] if latest else None,
                    "email": latest[1] if latest else None,
                    "time": latest[2] if latest else None
                } if latest else None
            })
        
        conn.close()
        return stats
    except Exception as e:
        logger.error(f"Failed to get referral stats: {e}")
        return []

# Initialize database on import
init_db()
