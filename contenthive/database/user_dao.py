from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from contenthive.database.database import get_engine, get_session_local
from contenthive.database.orm_models import User, Profile, Session as SessionModel
from contenthive.models.user import ProfileEntity, SessionEntity, UserEntity


class UserDAO:
    
    def __init__(self):
        self.engine = get_engine()
        self.SessionLocal = get_session_local()
        self.session = None

    def __enter__(self):
        self.session = self.SessionLocal()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_session(self) -> Session:
        """Get database session"""
        if self.session is None:
            self.session = self.SessionLocal()
        return self.session

    def close(self):
        """Close database session"""
        if self.session:
            self.session.close()
            self.session = None

    def user_exists(self, username: Optional[str] = None, email: Optional[str] = None) -> bool:
        """Check if a user exists by username or email"""
        session = self._get_session()
        try:
            if username and email:
                stmt = select(User.id).where((User.username == username) | (User.email == email))
            elif username:
                stmt = select(User.id).where(User.username == username)
            elif email:
                stmt = select(User.id).where(User.email == email)
            else:
                return False

            result = session.execute(stmt).first()
            return result is not None
        except Exception:
            raise
    
    def create_user(
            self,
            username: str,
            password_hash: str,
            email: Optional[str] = None,
            is_admin: bool = False,
            created_by: int = 0
        ) -> int:
        """Create a new user and return its ID"""
        session = self._get_session()
        try:
            user = User(
                username=username,
                email=email,
                password_hash=password_hash,
                status=1,
                is_admin=is_admin,
                created_by=created_by
            )
            session.add(user)
            session.flush()  # Flush to get the user_id without committing
            user_id = user.id
            self._create_profile(user_id, commit=False)
            session.commit()
            return user_id
        except Exception as e:
            session.rollback()
            if "UNIQUE constraint failed" in str(e):
                raise ValueError("Username or email already exists") from e
            raise
    
    def _create_profile(self, user_id: int, commit: bool = True):
        """Create a profile for a user"""
        session = self._get_session()
        try:
            profile = Profile(user_id=user_id)
            session.add(profile)
            if commit:
                session.commit()
        except Exception as e:
            if commit:
                session.rollback()
            raise ValueError("Profile already exists for this user") from e
        
    def get_user_by_username(self, username: str) -> Optional[UserEntity]:
        """Retrieve a user by username"""
        session = self._get_session()
        try:
            stmt = select(User).where(User.username == username)
            user = session.execute(stmt).scalar_one_or_none()
            if user:
                return UserEntity(
                    id=user.id,
                    username=user.username,
                    email=user.email,
                    password_hash=user.password_hash,
                    status=user.status,
                    force_password_change=user.force_password_change,
                    is_admin=user.is_admin,
                    token_version=user.token_version,
                    last_login_at=user.last_login_at,
                    created_by=user.created_by,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
            return None
        except Exception:
            raise ValueError("Database error occurred")

    def get_user_by_id(self, user_id: int) -> Optional[UserEntity]:
        """Retrieve a user by ID"""
        session = self._get_session()
        try:
            user = session.get(User, user_id)
            if user:
                return UserEntity(
                    id=user.id,
                    username=user.username,
                    email=user.email,
                    password_hash=user.password_hash,
                    status=user.status,
                    force_password_change=user.force_password_change,
                    is_admin=user.is_admin,
                    token_version=user.token_version,
                    last_login_at=user.last_login_at,
                    created_by=user.created_by,
                    created_at=user.created_at,
                    updated_at=user.updated_at,
                )
            return None
        except Exception:
            raise ValueError("Database error occurred")
    
    def get_profile_by_user_id(self, user_id: int) -> Optional[ProfileEntity]:
        """Retrieve a user profile by user ID"""
        session = self._get_session()
        try:
            profile = session.get(Profile, user_id)
            if profile:
                return ProfileEntity(
                    user_id=profile.user_id,
                    full_name=profile.full_name,
                    bio=profile.bio,
                    avatar_url=profile.avatar_url,
                    created_at=profile.created_at,
                    updated_at=profile.updated_at,
                )
            return None
        except Exception:
            raise ValueError("Database error occurred")

    def update_user_password(self, user_id: int, new_password_hash: str, force_password_change: bool = True) -> bool:
        """Update the password hash for a user"""
        session = self._get_session()
        try:
            user = session.get(User, user_id)
            if user:
                user.password_hash = new_password_hash
                user.force_password_change = force_password_change
                user.token_version = user.token_version + 1
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")

    def update_last_login(self, user_id: int) -> bool:
        """Update the last login time for a user"""
        session = self._get_session()
        try:
            user = session.get(User, user_id)
            if user:
                from datetime import datetime, timezone
                user.last_login_at = datetime.now(timezone.utc)
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")


    def upsert_session(
            self,
            user_id: int,
            device_id: str,
            token_jti: str,
            expires_at: datetime,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
        ) -> int:
        """Create a new session and return its ID"""
        session = self._get_session()
        try:
            from datetime import datetime, timezone
            
            # Check if session exists
            stmt = select(SessionModel).where(
                (SessionModel.user_id == user_id) & (SessionModel.device_id == device_id)
            )
            existing_session = session.execute(stmt).scalar_one_or_none()

            if existing_session:
                # Update existing session and reset revoked flag
                existing_session.token_jti = token_jti
                existing_session.expires_at = expires_at
                existing_session.ip_address = ip_address
                existing_session.user_agent = user_agent
                existing_session.revoked = False
                existing_session.last_accessed_at = datetime.now(timezone.utc)
                session.commit()
                return existing_session.id
            else:
                # Create new session
                new_session = SessionModel(
                    user_id=user_id,
                    device_id=device_id,
                    token_jti=token_jti,
                    expires_at=expires_at,
                    ip_address=ip_address,
                    user_agent=user_agent
                )
                session.add(new_session)
                session.flush()
                session.commit()
                return new_session.id
        except Exception as e:
            session.rollback()
            if "UNIQUE constraint failed" in str(e):
                raise ValueError("Session with given device ID or token JTI already exists") from e
            raise ValueError("Database error occurred") from e
        

    def get_session_by_jti(self, user_id: int, jti: str) -> Optional[SessionEntity]:
        """Retrieve a session by user ID and token JTI"""
        session = self._get_session()
        try:
            stmt = select(SessionModel).where(
                (SessionModel.user_id == user_id) & (SessionModel.token_jti == jti)
            )
            sess = session.execute(stmt).scalar_one_or_none()
            if sess:
                return SessionEntity(
                    id=sess.id,
                    user_id=sess.user_id,
                    device_id=sess.device_id,
                    token_jti=sess.token_jti,
                    expires_at=sess.expires_at,
                    ip_address=sess.ip_address,
                    user_agent=sess.user_agent,
                    revoked=sess.revoked,
                    created_at=sess.created_at,
                    last_accessed_at=sess.last_accessed_at,
                )
            return None
        except Exception:
            raise ValueError("Database error occurred")
        
    def list_all_users(self) -> list[tuple[UserEntity, ProfileEntity]]:
        """List all users in the database"""
        session = self._get_session()
        try:
            stmt = select(User).outerjoin(Profile)
            users_orm = session.execute(stmt).scalars().all()
            users = []
            for user_orm in users_orm:
                user = UserEntity(
                    id=user_orm.id,
                    username=user_orm.username,
                    email=user_orm.email,
                    password_hash=user_orm.password_hash,
                    status=user_orm.status,
                    force_password_change=user_orm.force_password_change,
                    is_admin=user_orm.is_admin,
                    token_version=user_orm.token_version,
                    last_login_at=user_orm.last_login_at,
                    created_by=user_orm.created_by,
                    created_at=user_orm.created_at,
                    updated_at=user_orm.updated_at,
                )
                if user_orm.profile:
                    profile = ProfileEntity(
                        user_id=user_orm.profile.user_id,
                        full_name=user_orm.profile.full_name,
                        bio=user_orm.profile.bio,
                        avatar_url=user_orm.profile.avatar_url,
                        created_at=user_orm.profile.created_at,
                        updated_at=user_orm.profile.updated_at,
                    )
                else:
                    profile = ProfileEntity(user_id=user_orm.id)
                users.append((user, profile))
            return users
        except Exception:
            raise ValueError("Database error occurred")
        
    def update_user_status(self, user_id: int, status: int) -> bool:
        """Update the active status of a user"""
        session = self._get_session()
        try:
            user = session.get(User, user_id)
            if user:
                user.status = status
                user.token_version = user.token_version + 1
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")

    def cleanup_expired_sessions(self) -> int:
        """
        Delete all expired sessions from the database.
        Returns the number of sessions deleted.
        """
        session = self._get_session()
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            stmt = select(SessionModel).where(SessionModel.expires_at < now)
            expired_sessions = session.execute(stmt).scalars().all()
            count = len(expired_sessions)
            for sess in expired_sessions:
                session.delete(sess)
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")

    def revoke_session_by_jti(self, user_id: int, jti: str) -> bool:
        """
        Revoke a specific session by JTI.
        Returns True if the session was revoked, False if not found.
        """
        session = self._get_session()
        try:
            stmt = select(SessionModel).where(
                (SessionModel.user_id == user_id) & (SessionModel.token_jti == jti)
            )
            sess = session.execute(stmt).scalar_one_or_none()
            if sess:
                sess.revoked = True
                session.commit()
                return True
            return False
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")

    def revoke_all_user_sessions(self, user_id: int) -> int:
        """
        Revoke all sessions for a specific user.
        Returns the number of sessions revoked.
        """
        session = self._get_session()
        try:
            stmt = select(SessionModel).where(SessionModel.user_id == user_id)
            sessions = session.execute(stmt).scalars().all()
            for sess in sessions:
                sess.revoked = True
            session.commit()
            return len(sessions)
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")

    def delete_revoked_sessions(self) -> int:
        """
        Delete all revoked sessions from the database.
        Returns the number of sessions deleted.
        """
        session = self._get_session()
        try:
            stmt = select(SessionModel).where(SessionModel.revoked == True)
            revoked_sessions = session.execute(stmt).scalars().all()
            count = len(revoked_sessions)
            for sess in revoked_sessions:
                session.delete(sess)
            session.commit()
            return count
        except Exception:
            session.rollback()
            raise ValueError("Database error occurred")