import random
import string
from pwdlib import PasswordHash
from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from contenthive.config import settings

password_hash = PasswordHash.recommended()

class UserUtils:
    
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
        """Generate a random password of given length"""
        if length < 8:
            length = 8
        
        # Ensure password contains at least one of each required character type
        password_chars = [
            random.choice(string.ascii_lowercase),  # At least one lowercase
            random.choice(string.ascii_uppercase),  # At least one uppercase
            random.choice(string.digits),           # At least one digit
            random.choice("!@#$%^&*")              # At least one special char
        ]
        
        # Fill the rest with random characters
        all_characters = string.ascii_letters + string.digits + "!@#$%^&*"
        password_chars += [random.choice(all_characters) for _ in range(length - 4)]
        
        # Shuffle to avoid predictable pattern
        random.shuffle(password_chars)
        
        return ''.join(password_chars)
    
    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt"""
        return password_hash.hash(password)

    @staticmethod
    def verify_password(password: str, hashed_password: str) -> bool:
        """Verify a password against its hash"""
        return password_hash.verify(password, hashed_password)
    
    @staticmethod
    def create_access_token(data: dict, expires_delta: timedelta, secret_key: str, algorithm: str) -> str:
        """Create a JWT access token for a user"""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire, "type": "access"})
        
        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token
    
    @staticmethod
    def create_refresh_token(data: dict, expires_delta: timedelta, secret_key: str, algorithm: str) -> str:
        """Create a JWT refresh token for a user"""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + expires_delta
        to_encode.update({"exp": expire, "type": "refresh"})
        
        token = jwt.encode(to_encode, secret_key, algorithm=algorithm)
        return token
    
    @staticmethod
    def decode_token(token: str, secret_key: str, algorithms: list) -> dict:
        """Decode a JWT token and return its payload"""
        try:
            payload = jwt.decode(token, secret_key, algorithms=algorithms)
            return payload
        except JWTError:
            raise ValueError("Invalid token")