from contenthive.core.secret import secret_manager
from contenthive.database.user_dao import UserDAO
from contenthive.models.enumerates import UserStatus
from contenthive.models.user import UserCreateResponse, UserProfileResponse


class UserService:
    def __init__(
        self,
    ):
        pass

    def create_user(
        self,
        created_by: int,
        username: str,
        password: str,
        email: str | None = None,
        is_admin: bool = False,
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

    def change_user_status(self, user_id: int, status: UserStatus) -> bool:
        """Change the active status of a user"""
        with UserDAO() as dao:
            user = dao.get_user_by_id(user_id)
            if not user:
                raise ValueError("User not found")

            result = dao.update_user_status(user.id, status)
            return result


user_service = UserService()
