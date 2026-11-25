import re
import secrets
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from pwdlib import PasswordHash

from contenthive.config import settings
from contenthive.settings.store import get_settings

_COMMON_PASSWORDS_PATH = Path(__file__).with_name("common_passwords.txt")
_CONSECUTIVE_CHARACTERS = re.compile(r"(.)\1{2}", re.DOTALL)


def _load_common_passwords() -> frozenset[str]:
    """Load the common-password list, ignoring blanks and source comments."""
    passwords: set[str] = set()
    for line in _COMMON_PASSWORDS_PATH.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        passwords.add(entry.casefold())
    return frozenset(passwords)


_COMMON_PASSWORDS = _load_common_passwords()


class SecretManager:
    def __init__(self):
        """Initialize the SecretManager with configuration from settings"""
        self.secret_key = self._get_or_create_secret_key()
        self.algorithm: str = "HS256"
        self.password_hash = PasswordHash.recommended()

    def _get_or_create_secret_key(self) -> str:
        """Get or create the application secret key."""
        secret_file = settings.data_dir / "secret.key"

        # Ensure the parent directory exists
        secret_file.parent.mkdir(parents=True, exist_ok=True)

        if secret_file.exists():
            return secret_file.read_text().strip()

        # Generate a new secret key
        new_secret = secrets.token_urlsafe(32)

        # Save the new secret key to the file
        secret_file.write_text(new_secret)
        secret_file.chmod(0o600)
        return new_secret

    # Punctuation included in generated passwords. Validation does not require it.
    _SPECIAL_CHARS = "!@#$%^&*-_."

    @staticmethod
    def password_strength(password: str) -> str | None:
        """Return a failure reason when the password misses a requirement.

        Requires at least 8 characters, one letter, and one digit. Rejects three
        or more identical characters in a row, and exact case-insensitive matches
        against the common-password list. Extra characters and punctuation are
        allowed.
        """
        if len(password) < 8:
            return "Password must be at least 8 characters long"
        if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            return "Password must include both letters and numbers"
        if _CONSECUTIVE_CHARACTERS.search(password):
            return "Password must not contain more than two identical characters in a row"
        if password.casefold() in _COMMON_PASSWORDS:
            return "Password is too common"
        return None

    @staticmethod
    def generate_random_password(length: int = 12) -> str:
        """Generate a cryptographically secure random password of given length"""
        if length < 8:
            length = 8

        special = SecretManager._SPECIAL_CHARS
        all_characters = string.ascii_letters + string.digits + special
        for _ in range(32):
            # Keep generated passwords stronger than the minimum: mixed case and punctuation.
            password_chars = [
                secrets.choice(string.ascii_lowercase),
                secrets.choice(string.ascii_uppercase),
                secrets.choice(string.digits),
                secrets.choice(special),
            ]
            password_chars += [secrets.choice(all_characters) for _ in range(length - 4)]
            secrets.SystemRandom().shuffle(password_chars)
            password = "".join(password_chars)
            if SecretManager.password_strength(password) is None:
                return password
        raise RuntimeError("Failed to generate a password that meets strength requirements")

    def hash_password(self, password: str) -> str:
        """Hash a password using the recommended password hashing algorithm (e.g., Argon2)"""
        return self.password_hash.hash(password)

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return self.password_hash.verify(password, hashed_password)

    def create_access_token(
        self,
        data: dict,
        expires_delta: timedelta | None = None,
        secret_key: str | None = None,
        algorithm: str | None = None,
    ) -> str:
        """Create a JWT access token for a user"""
        if expires_delta is None:
            expires_delta = timedelta(minutes=get_settings().auth.access_token_expire_minutes)

        if expires_delta.total_seconds() <= 0:
            raise ValueError("Expiration time must be in the future")

        if secret_key is None:
            secret_key = self.secret_key
        if algorithm is None:
            algorithm = self.algorithm

        to_encode = data.copy()
        expire = datetime.now(UTC) + expires_delta
        to_encode.update({"exp": expire, "type": "access"})

        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token

    def create_refresh_token(
        self,
        data: dict,
        expires_delta: timedelta | None = None,
        secret_key: str | None = None,
        algorithm: str | None = None,
    ) -> str:
        """Create a JWT refresh token for a user"""
        if expires_delta is None:
            expires_delta = timedelta(days=get_settings().auth.refresh_token_expire_days)

        if expires_delta.total_seconds() <= 0:
            raise ValueError("Expiration time must be in the future")

        if secret_key is None:
            secret_key = self.secret_key
        if algorithm is None:
            algorithm = self.algorithm

        to_encode = data.copy()
        expire = datetime.now(UTC) + expires_delta
        to_encode.update({"exp": expire, "type": "refresh"})

        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token

    def decode_token(
        self,
        token: str,
        secret_key: str | None = None,
        algorithms: list | None = None,
    ) -> dict:
        """Decode a JWT token and return its payload"""
        if secret_key is None:
            secret_key = self.secret_key
        if algorithms is None:
            algorithms = [self.algorithm]

        try:
            payload = jwt.decode(token, secret_key, algorithms=algorithms)
            return payload
        except jwt.PyJWTError as e:
            raise ValueError("Invalid token") from e


# Global singleton instance
secret_manager = SecretManager()
