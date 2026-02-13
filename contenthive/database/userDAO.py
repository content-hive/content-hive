
import sqlite3
from typing import Optional

from contenthive.database.database import get_db_connection
from contenthive.models.user import ProfileEntity, SessionEntity, UserEntity


class UserDAO:
    
    def __init__(self):
        self.conn = None

    def __enter__(self):
        self._get_connection()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        if self.conn is None:
            self.conn = get_db_connection()
            self.conn.row_factory = sqlite3.Row
        return self.conn

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            self.conn = None

    def user_exists(self, username: Optional[str] = None, email: Optional[str] = None) -> bool:
        """Check if a user exists by username or email"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            if username and email:
                cursor.execute(
                    "SELECT id FROM users WHERE username = ? OR email = ?",
                    (username, email),
                )
            elif username:
                cursor.execute(
                    "SELECT id FROM users WHERE username = ?",
                    (username,),
                )
            elif email:
                cursor.execute(
                    "SELECT id FROM users WHERE email = ?",
                    (email,),
                )
            else:
                return False

            return cursor.fetchone() is not None
        except sqlite3.Error:
            raise
    
    def create_user(
            self,
            username: str,
            password_hash: str,
            email: Optional[str] = None,
            is_admin: bool = False
        ) -> int:
        """Create a new user and return its ID"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (username, email, password_hash, status, is_admin)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, email, password_hash, 1, is_admin),
            )
            user_id = cursor.lastrowid if cursor.lastrowid else 0
            self._create_profile(user_id, commit=False)

            conn.commit()
            return user_id
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("Username or email already exists") from e
    
    def _create_profile(self, user_id: int, commit: bool = True):
        """Create a profile for a user"""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO profiles (user_id)
                VALUES (?)
                """,
                (user_id,),
            )
            if commit:
                conn.commit()
        except sqlite3.IntegrityError as e:
            if commit:
                conn.rollback()
            raise ValueError("Profile already exists for this user") from e
        
    def get_user_by_username(self, username: str) -> Optional[UserEntity]:
        """Retrieve a user by username"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,),
            )
            row = cursor.fetchone()
            if row:
                return UserEntity(
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    status=row["status"],
                    force_password_change=bool(row["force_password_change"]),
                    is_admin=bool(row["is_admin"]),
                    token_version=row["token_version"],
                    last_login_at=row["last_login_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return None
        except sqlite3.Error:
            raise ValueError("Database error occurred")

    def get_user_by_id(self, user_id: int) -> Optional[UserEntity]:
        """Retrieve a user by ID"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return UserEntity(
                    id=row["id"],
                    username=row["username"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    status=row["status"],
                    force_password_change=bool(row["force_password_change"]),
                    is_admin=bool(row["is_admin"]),
                    token_version=row["token_version"],
                    last_login_at=row["last_login_at"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return None
        except sqlite3.Error:
            raise ValueError("Database error occurred")
    
    def get_profile_by_user_id(self, user_id: int) -> Optional[ProfileEntity]:
        """Retrieve a user profile by user ID"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM profiles WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            if row:
                return ProfileEntity(
                    user_id=row["user_id"],
                    full_name=row["full_name"],
                    bio=row["bio"],
                    avatar_url=row["avatar_url"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            return None
        except sqlite3.Error:
            raise ValueError("Database error occurred")

    def update_user_password(self, user_id: int, new_password_hash: str, force_password_change: bool = True) -> bool:
        """Update the password hash for a user"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users
                SET password_hash = ?, force_password_change = ?, updated_at = CURRENT_TIMESTAMP, token_version = token_version + 1
                WHERE id = ?
                """,
                (new_password_hash, 0 if force_password_change else 1, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            conn.rollback()
            raise ValueError("Database error occurred")

    def update_last_login(self, user_id: int) -> bool:
        """Update the last login time for a user"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE users
                SET last_login_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (user_id,),
            )
            conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error:
            conn.rollback()
            raise ValueError("Database error occurred")


    def upsert_session(
            self,
            user_id: int,
            device_id: str,
            token_jti: str,
            expires_at: str,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
        ) -> int:
        """Create a new session and return its ID"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Check if session exists
            cursor.execute(
                """
                SELECT id FROM sessions WHERE user_id = ? AND device_id = ?
                """,
                (user_id, device_id),
            )

            existing_session = cursor.fetchone()

            if existing_session:
                # Update existing session
                cursor.execute(
                    """
                    UPDATE sessions
                    SET token_jti = ?, expires_at = ?, ip_address = ?, user_agent = ?, last_accessed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (token_jti, expires_at, ip_address, user_agent, existing_session["id"]),
                )
                session_id = existing_session["id"]
            else:
                # Create new session
                cursor.execute(
                    """
                    INSERT INTO sessions (user_id, device_id, token_jti, expires_at, ip_address, user_agent)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, device_id, token_jti, expires_at, ip_address, user_agent)
                )
                session_id = cursor.lastrowid if cursor.lastrowid else 0

            conn.commit()
            return session_id
        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError("Session with given device ID or token JTI already exists") from e
        except sqlite3.Error:
            conn.rollback()
            raise ValueError("Database error occurred")
        

    def get_session_by_jti(self, user_id: int, jti: str) -> Optional[SessionEntity]:
        """Retrieve a session by user ID and token JTI"""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM sessions WHERE user_id = ? AND token_jti = ?
                """,
                (user_id, jti),
            )
            row = cursor.fetchone()
            if row:
                return SessionEntity(
                    id=row["id"],
                    user_id=row["user_id"],
                    device_id=row["device_id"],
                    token_jti=row["token_jti"],
                    expires_at=row["expires_at"],
                    ip_address=row["ip_address"],
                    user_agent=row["user_agent"],
                    created_at=row["created_at"],
                    last_accessed_at=row["last_accessed_at"],
                )
            return None
        except sqlite3.Error:
            raise ValueError("Database error occurred")