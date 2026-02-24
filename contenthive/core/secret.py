import secrets
import string
from typing import Optional
from pwdlib import PasswordHash
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone

from contenthive.config import settings


class SecretManager:
    
    def __init__(self):
        """Initialize the SecretManager with configuration from settings"""
        self.secret_key = self._get_or_create_secret_key()
        self.algorithm: str = "HS256"
        self.access_token_expire_minutes: int = settings.access_token_expire_minutes
        self.refresh_token_expire_days: int = settings.refresh_token_expire_days
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
    
    @staticmethod
    def password_strength(password: str) -> bool:
        """Check if the password meets strength requirements"""
        if (len(password) < 8 or
            not any(c.islower() for c in password) or
            not any(c.isupper() for c in password) or
            not any(c.isdigit() for c in password) or
            not any(c in "!@#$%^&*" for c in password)):
            return False
        return True

    @staticmethod
    def generate_random_password(length: int = 12) -> str:
        """Generate a cryptographically secure random password of given length"""
        if length < 8:
            length = 8
        
        # Ensure password contains at least one of each required character type
        password_chars = [
            secrets.choice(string.ascii_lowercase),  # At least one lowercase
            secrets.choice(string.ascii_uppercase),  # At least one uppercase
            secrets.choice(string.digits),           # At least one digit
            secrets.choice("!@#$%^&*")              # At least one special char
        ]
        
        # Fill the rest with random characters
        all_characters = string.ascii_letters + string.digits + "!@#$%^&*"
        password_chars += [secrets.choice(all_characters) for _ in range(length - 4)]
        
        # Shuffle to avoid predictable pattern using secrets
        secrets.SystemRandom().shuffle(password_chars)
        
        return ''.join(password_chars)
    
    def hash_password(self, password: str) -> str:
        """Hash a password using the recommended password hashing algorithm (e.g., Argon2)"""
        return self.password_hash.hash(password)

    def verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return self.password_hash.verify(password, hashed_password)
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None, secret_key: Optional[str] = None, algorithm: Optional[str] = None) -> str:
        """Create a JWT access token for a user"""
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.access_token_expire_minutes)
    
        if expires_delta.total_seconds() <= 0:
            raise ValueError("Expiration time must be in the future")
        
        if secret_key is None:
            secret_key = self.secret_key
        if algorithm is None:
            algorithm = self.algorithm

        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire, "type": "access"})
        
        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token
    
    def create_refresh_token(self, data: dict, expires_delta: Optional[timedelta] = None, secret_key: Optional[str] = None, algorithm: Optional[str] = None) -> str:
        """Create a JWT refresh token for a user"""
        if expires_delta is None:
            expires_delta = timedelta(days=self.refresh_token_expire_days)
        
        if expires_delta.total_seconds() <= 0:
            raise ValueError("Expiration time must be in the future")
        
        if secret_key is None:
            secret_key = self.secret_key
        if algorithm is None:
            algorithm = self.algorithm
        
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire, "type": "refresh"})
        
        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token
    
    def decode_token(self, token: str, secret_key: Optional[str] = None, algorithms: Optional[list] = None) -> dict:
        """Decode a JWT token and return its payload"""
        if secret_key is None:
            secret_key = self.secret_key
        if algorithms is None:
            algorithms = [self.algorithm]

        try:
            payload = jwt.decode(token, secret_key, algorithms=algorithms)
            return payload
        except JWTError:
            raise ValueError("Invalid token")


# Global singleton instance
secret_manager = SecretManager()