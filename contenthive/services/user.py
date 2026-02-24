
from typing import Optional
import os

from contenthive.database.user_dao import UserDAO
from contenthive.core.secret import secret_manager
from contenthive.models.user import UserCreateResponse, UserProfileResponse

class UserService:
    def __init__(self, ):
        pass

    def create_user(
            self,
            created_by: int,
            username: str,
            password: str,
            email: Optional[str] = None, 
            is_admin: bool = False
        ) -> UserCreateResponse:
        """Create a new user and return the user ID"""
        with UserDAO() as dao:
            if dao.user_exists(username=username, email=email):
                raise ValueError("User with given username or email already exists")

            password_hash = secret_manager.hash_password(password)
            user_id = dao.create_user(username, password_hash, email, is_admin, created_by)
            user = dao.get_user_by_id(user_id)
            
            if not user:
                raise ValueError("Failed to create user")
            
            return UserCreateResponse.from_entity(user)
        
    def create_admin_user(self) -> Optional[tuple[str, str]]:
        """
        Create initial admin user. Returns (username, password) only on creation,
        None if admin already exists or password was set via environment variable.
        
        Password can be set via ADMIN_PASSWORD environment variable for automated setups,
        otherwise a secure random password is generated.
        """
        with UserDAO() as dao:
            username = "admin"
            if dao.user_exists(username=username):
                raise ValueError("Admin user already exists")

            # Check if ADMIN_PASSWORD is set (for automated deployments)
            password = os.getenv("ADMIN_PASSWORD")
            if password:
                # Validate password strength if provided via env var
                if not secret_manager.password_strength(password):
                    raise ValueError(
                        "ADMIN_PASSWORD does not meet strength requirements. "
                        "Password must be at least 8 characters with uppercase, lowercase, "
                        "digit, and special character (!@#$%^&*)"
                    )
            else:
                # Generate secure random password
                password = secret_manager.generate_random_password()
            
            password_hash = secret_manager.hash_password(password)

            dao.create_user(
                username=username,
                password_hash=password_hash,
                is_admin=True,
                created_by=0
            )
            
            # Only return password if it was auto-generated
            # If set via env var, don't return it (assume deployer knows it)
            if os.getenv("ADMIN_PASSWORD"):
                return None
            
            return username, password
    
    def change_user_password(self, user_id: int, new_password: str) -> bool:
        """Change the password for a given user"""
        if not secret_manager.password_strength(new_password):
            raise ValueError("Password does not meet strength requirements")

        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            
            new_password_hash = secret_manager.hash_password(new_password)
            result = dao.update_user_password(user.id, new_password_hash, force_password_change=False)
            dao.revoke_all_user_sessions(user.id)
            return result
    
    def reset_user_password(self, user_id: int) -> str:
        """Reset the password for a given user and return the new password"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            
            new_password = secret_manager.generate_random_password()
            new_password_hash = secret_manager.hash_password(new_password)
            result = dao.update_user_password(user.id, new_password_hash, force_password_change=True)
            dao.revoke_all_user_sessions(user.id)
            if not result:
                raise ValueError("Failed to update user password")
            return new_password
    
    def get_user_profile(self, user_id: int) -> UserProfileResponse:
        """Retrieve user profile by user ID"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            profile = dao.get_profile_by_user_id(user_id)
            if not user or not profile:
                raise ValueError("User not found")
            
            return UserProfileResponse.from_entities(user, profile)

    def list_users(self) -> list[UserProfileResponse]:
        """List all users"""
        with UserDAO() as dao:
            users = dao.list_all_users()
            return [UserProfileResponse.from_entities(user, profile) for user, profile in users]

    def change_user_status(self, user_id: int, status: int) -> bool:
        """Change the active status of a user"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            
            result = dao.update_user_status(user.id, status)
            return result

user_service = UserService()