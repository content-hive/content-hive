from fastapi import Request

from contenthive.core.secret import secret_manager
from contenthive.database.user_dao import UserDAO
from contenthive.models.system import SetupAdminRequest
from contenthive.models.user import LoginResponse, UserCreateResponse
from contenthive.services.token import token_service


class SetupService:
    """Service layer for first-time application setup."""

    def is_setup_complete(self) -> bool:
        """Return True when at least one admin user exists."""
        with UserDAO() as dao:
            return dao.has_admin_user()

    def setup_initial_admin(
        self,
        username: str,
        password: str,
        email: str | None = None,
    ) -> UserCreateResponse:
        """Create the first admin user during initial setup.

        Raises:
            ValueError: If setup is complete, password is weak, or username/email conflicts.
        """
        if not secret_manager.password_strength(password):
            raise ValueError("Password does not meet strength requirements")

        password_hash = secret_manager.hash_password(password)
        with UserDAO() as dao:
            user_id = dao.create_initial_admin_user(username, password_hash, email)
            user = dao.get_user_by_id(user_id)

        if not user:
            raise ValueError("Failed to create user")

        return UserCreateResponse.from_entity(user)

    async def complete_setup(self, body: SetupAdminRequest, request: Request) -> LoginResponse:
        """Create the first admin user and return login tokens.

        Raises:
            ValueError: If setup is complete or user creation fails validation.
        """
        if self.is_setup_complete():
            raise ValueError("Setup already complete")

        self.setup_initial_admin(
            username=body.username,
            password=body.password,
            email=body.email,
        )
        return token_service.authenticate_user(
            username=body.username,
            password=body.password,
            request=request,
        )


setup_service = SetupService()
