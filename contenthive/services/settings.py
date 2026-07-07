from pydantic import ValidationError

from contenthive.models.settings import UpdateAppSettingsRequest
from contenthive.settings.schema import AppSettings
from contenthive.settings.store import load_settings, save_settings


class SettingsValidationError(Exception):
    """Raised when application settings fail schema validation."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _format_validation_errors(error: ValidationError) -> list[str]:
    return [
        f"{'/'.join(str(part) for part in err['loc'])}: {err['msg']}" if err["loc"] else err["msg"]
        for err in error.errors()
    ]


def _merge_settings(current: AppSettings, body: UpdateAppSettingsRequest) -> AppSettings:
    data = current.model_dump()
    if body.plugins is not None:
        data["plugins"] = {**data["plugins"], **body.plugins.model_dump(exclude_none=True)}
    if body.auth is not None:
        data["auth"] = {**data["auth"], **body.auth.model_dump(exclude_none=True)}
    if body.download is not None:
        data["download"] = {**data["download"], **body.download.model_dump(exclude_none=True)}
    return AppSettings.model_validate(data)


class SettingsService:
    """Service layer for application settings."""

    def get_app_settings(self) -> AppSettings:
        """Return current application settings."""
        try:
            return load_settings()
        except ValidationError as e:
            raise SettingsValidationError(_format_validation_errors(e)) from e

    def update_app_settings(self, body: UpdateAppSettingsRequest) -> AppSettings:
        """Validate and persist application settings."""
        if body.plugins is None and body.auth is None and body.download is None:
            raise SettingsValidationError(["At least one settings section must be provided"])

        try:
            current = load_settings()
        except ValidationError as e:
            raise SettingsValidationError(_format_validation_errors(e)) from e

        try:
            updated = _merge_settings(current, body)
        except ValidationError as e:
            raise SettingsValidationError(_format_validation_errors(e)) from e

        save_settings(updated)
        return updated


settings_service = SettingsService()
