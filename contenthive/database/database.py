import sqlite3
from contenthive.config import settings

def get_db_connection():
    conn = sqlite3.connect(settings.database_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def initialize_db():
    conn = get_db_connection()
    
    # User table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            status INTEGER DEFAULT 0,
            force_password_change BOOLEAN DEFAULT 1,
            is_admin BOOLEAN DEFAULT 0,
            token_version INTEGER DEFAULT 0,
            last_login_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Profile table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT,
            bio TEXT,
            avatar_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # Session table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            device_id TEXT UNIQUE NOT NULL,
            revoked BOOLEAN DEFAULT 0,
            token_jti TEXT UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # Platform table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS platforms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            icon_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Author table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS authors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL,
            uid TEXT NOT NULL,
            name TEXT,
            username TEXT NOT NULL,
            avatar TEXT,
            url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(platform_id, uid),
            FOREIGN KEY (platform_id) REFERENCES platforms(id)
        )
    """)
    
    # Media table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            type TEXT NOT NULL,
            title TEXT,
            duration INTEGER,
            width TEXT,
            height TEXT,
            cover TEXT,
            media_path TEXT,
            cover_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Parse Results table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parse_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pid TEXT NOT NULL,
            url TEXT NOT NULL,
            content TEXT NOT NULL,
            author_id INTEGER,
            platform_id INTEGER NOT NULL,
            user_id INTEGER,
            created_time INTEGER,
            parser TEXT NOT NULL,
            state TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (author_id) REFERENCES authors(id),
            FOREIGN KEY (platform_id) REFERENCES platforms(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # Parse Results and Media Association table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS parse_result_media (
            parse_result_id INTEGER NOT NULL,
            media_id INTEGER NOT NULL,
            PRIMARY KEY (parse_result_id, media_id),
            FOREIGN KEY (parse_result_id) REFERENCES parse_results(id) ON DELETE CASCADE,
            FOREIGN KEY (media_id) REFERENCES media(id) ON DELETE CASCADE
        )
    """)
    
    conn.commit()
    conn.close()

    # Create admin user if not exists
    from contenthive.services.user import user_service
    try:
        username, password = user_service.create_admin_user()
        print(f"Admin user created. Username: {username}, Password: {password}, please change it after first login.")
    except ValueError:
        pass  # Admin user already exists
