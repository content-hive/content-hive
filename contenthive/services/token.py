from datetime import datetime, timedelta, timezone
import hashlib
from typing import Optional
import uuid

from fastapi import Request
from contenthive.config import settings
from contenthive.models.user import DeviceInfoModel, LoginResponse, RefreshTokenResponse, UserModel, AuthTokenModel
from contenthive.database.userDAO import UserDAO
from contenthive.utils.user import UserUtils

class TokenService:
    
    def __init__(self):
        self.secret_key = settings.secret_key
        self.algorithm = settings.algorithm
        self.access_token_expire_minutes = settings.access_token_expire_minutes
        self.refresh_token_expire_days = settings.refresh_token_expire_days

    def authenticate_user(self, username: str, password: str, request: Request) -> LoginResponse:
        """Authenticate user and return token data"""
        with UserDAO() as dao:
            user = dao.get_user_by_username(username)
            if not user or not UserUtils.verify_password(password, user.password_hash):
                raise ValueError("Invalid username or password")
            
            if user.status == 2:  # disabled
                raise ValueError("User account is disabled")
            
            # Update last login time
            dao.update_last_login(user.id)
            
            user_response = UserModel.from_entity(user)
            
            access_token = UserUtils.create_access_token(
                data={"sub": user.username, "user_id": user.id, "token_version": user.token_version},
                expires_delta=timedelta(minutes=self.access_token_expire_minutes),
                secret_key=self.secret_key,
                algorithm=self.algorithm
            )

            # Generate unique JTI
            token_jti = str(uuid.uuid4())
            refresh_token = UserUtils.create_refresh_token(
                data={"sub": user.username, "user_id": user.id, "jti": token_jti, "token_version": user.token_version},
                expires_delta=timedelta(days=self.refresh_token_expire_days),
                secret_key=self.secret_key,
                algorithm=self.algorithm
            )
            refresh_token_expires_at = (datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)).isoformat()

            device_info = self._extract_device_info(request)

            # Store session in database
            dao.upsert_session(
                user_id=user.id,
                device_id=device_info.device_id or "",
                token_jti=token_jti,
                expires_at=refresh_token_expires_at,
                ip_address=device_info.ip_address or "",
                user_agent=device_info.user_agent or ""
            )

            return LoginResponse(
                user=user_response,
                tokens=AuthTokenModel(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_type="bearer",
                    expires_in=self.access_token_expire_minutes * 60
                )
            )
    

    def refresh_access_token(self, refresh_token: str, request: Request) -> RefreshTokenResponse:
        """Refresh access token using a valid refresh token"""
        try:
            payload = UserUtils.decode_token(
                token=refresh_token,
                secret_key=self.secret_key,
                algorithms=[self.algorithm]
            )
            
            # Validate token type
            token_type: Optional[str] = payload.get("type")
            if token_type != "refresh":
                raise ValueError("Invalid token type - expected refresh token")
            
            username: Optional[str] = payload.get("sub")
            user_id: Optional[int] = payload.get("user_id")
            jti: Optional[str] = payload.get("jti")
            token_version: Optional[int] = payload.get("token_version")

            if username is None or user_id is None or jti is None or token_version is None:
                raise ValueError("Invalid token payload")

            with UserDAO() as dao:
                user = dao.get_user_by_id(user_id)
                if not user or user.username != username:
                    raise ValueError("User not found")
                
                # Validate token_version to ensure token hasn't been invalidated
                if user.token_version != token_version:
                    raise ValueError("Token has been invalidated due to account changes")
                
                # Check if user account is disabled
                if user.status == 2:
                    raise ValueError("User account is disabled")

                session = dao.get_session_by_jti(user_id=user.id, jti=jti)
                if not session:
                    raise ValueError("Session not found or invalidated")
                
                # Check if session is revoked
                if session.revoked:
                    raise ValueError("Session has been revoked")

                # Generate new access token
                access_token = UserUtils.create_access_token(
                    data={"sub": user.username, "user_id": user.id, "token_version": user.token_version},
                    expires_delta=timedelta(minutes=self.access_token_expire_minutes),
                    secret_key=self.secret_key,
                    algorithm=self.algorithm
                )

                # Generate new refresh token with new JTI
                new_jti = str(uuid.uuid4())
                refresh_token = UserUtils.create_refresh_token(
                    data={"sub": user.username, "user_id": user.id, "jti": new_jti, "token_version": user.token_version},
                    expires_delta=timedelta(days=self.refresh_token_expire_days),
                    secret_key=self.secret_key,
                    algorithm=self.algorithm
                )
                refresh_token_expires_at = (datetime.now(timezone.utc) + timedelta(days=self.refresh_token_expire_days)).isoformat()

                device_info = self._extract_device_info(request)

                # Update session in database
                dao.upsert_session(
                    user_id=user.id,
                    device_id=device_info.device_id or "",
                    token_jti=new_jti,
                    expires_at=refresh_token_expires_at,
                    ip_address=device_info.ip_address or "",
                    user_agent=device_info.user_agent or ""
                )

                return RefreshTokenResponse(
                    tokens=AuthTokenModel(
                        access_token=access_token,
                        refresh_token=refresh_token,
                        token_type="bearer",
                        expires_in=self.access_token_expire_minutes * 60
                    )
                )
        except Exception as e:
            raise ValueError("Could not refresh access token") from e


    @staticmethod
    def _extract_device_info(request: Request) -> DeviceInfoModel:
        """Extract device ID and user agent from request headers"""
        client_device_id = request.headers.get("X-Device-ID")
        if not client_device_id:
            client_device_id = TokenService._generate_device_fingerprint(request)

        user_agent = request.headers.get("User-Agent", "unknown-agent")

        device_name = "unknown-device"
        if "Mobile" in user_agent:
            device_name = "mobile-device"
        elif "Android" in user_agent:
            device_name = "android-device"
        elif "iPhone" in user_agent:
            device_name = "iphone-device"
        elif "Chrome" in user_agent:
            device_name = "chrome-browser"
        elif "Firefox" in user_agent:
            device_name = "firefox-browser"
        elif "Safari" in user_agent:
            device_name = "safari-browser"
        elif "Edge" in user_agent:
            device_name = "edge-browser"

        return DeviceInfoModel(
            device_id=client_device_id,
            device_name=device_name,
            ip_address=TokenService._extract_device_ip(request),
            user_agent=user_agent
        )


    @staticmethod
    def _generate_device_fingerprint(request: Request) -> str:
        """
        Generate a stable device fingerprint from request headers.
        
        Note: IP address is intentionally excluded to prevent fingerprint changes
        when users switch networks (e.g., WiFi to mobile data, VPN usage).
        IP is still logged in the session for security/audit purposes.
        """
        user_agent = request.headers.get("User-Agent", "")
        accept_language = request.headers.get("Accept-Language", "")
        accept_encoding = request.headers.get("Accept-Encoding", "")
        
        # Note: IP is NOT included in fingerprint for stability
        fingerprint_data = f"{user_agent}|{accept_language}|{accept_encoding}"
        device_fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()
        return f"fp_{device_fingerprint[:16]}"


    @staticmethod
    def _extract_device_ip(request: Request) -> str:
        """Extract client IP address from request headers"""
        client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.headers.get("X-Real-IP", "").strip()
        if not client_ip:
            client_ip = request.client.host if request.client else ""
        return client_ip


token_service = TokenService()
