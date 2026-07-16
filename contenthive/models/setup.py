"""
Models for first-time application setup.
"""

from pydantic import field_validator

from contenthive.core.secret import secret_manager
from contenthive.models.api import APIBaseModel


class SetupAdminRequest(APIBaseModel):
    """Request body for creating the first admin user during setup"""

    username: str
    password: str
    email: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """Validate password meets strength requirements"""
        if not secret_manager.password_strength(v):
            raise ValueError(
                "Password must be at least 8 characters long and contain "
                "at least one lowercase letter, one uppercase letter, "
                "one digit, and one special character (e.g. !@#$%^&*-_.)"
            )
        return v
