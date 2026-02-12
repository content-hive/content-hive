
from typing import Optional

from contenthive.database.userDAO import UserDAO
from contenthive.utils.user import UserUtils
from contenthive.models.user import UserCreateModel, UserModel, UserProfileModel

class UserService:
    def __init__(self, ):
        pass

    def _create_user(
            self,
            username: str,
            password: str,
            email: Optional[str] = None, 
            is_admin: bool = False
        ) -> int:
        """Create a new user and return the user ID"""
        with UserDAO() as dao:
            if dao.user_exists(username=username, email=email):
                raise ValueError("User with given username or email already exists")

            user_id = dao.create_user(username, password, email, is_admin)
            return user_id
        
    def create_admin_user(self) -> tuple[str, str]:
        """Public method to create a new user"""
        with UserDAO() as dao:
            username = "admin"
            if dao.user_exists(username=username):
                raise ValueError("Admin user already exists")

            password = UserUtils.generate_random_password()
            password_hash = UserUtils.hash_password(password)

            dao.create_user(
                username=username,
                password_hash=password_hash,
                is_admin=True
            )
            
            return username, password
    
    def change_user_password(self, user_id: int, new_password: str) -> bool:
        """Change the password for a given user"""
        if not UserUtils.password_strength(new_password):
            raise ValueError("Password does not meet strength requirements")

        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            
            new_password_hash = UserUtils.hash_password(new_password)
            result = dao.update_user_password(user.id, new_password_hash, force_password_change=False)
            return result
    
    def reset_user_password(self, user_id: int) -> str:
        """Reset the password for a given user and return the new password"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")
            
            new_password = UserUtils.generate_random_password()
            new_password_hash = UserUtils.hash_password(new_password)
            result = dao.update_user_password(user.id, new_password_hash, force_password_change=True)
            if not result:
                raise ValueError("Failed to update user password")
            return new_password
    
    def get_user_profile(self, user_id: int) -> UserProfileModel:
        """Retrieve user profile by user ID"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            profile = dao.get_profile_by_user_id(user_id)
            if not user or not profile:
                raise ValueError("User not found")
            
            return UserProfileModel.from_entities(user, profile)

user_service = UserService()