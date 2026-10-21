"""Only API Gateway's verified JWT context can select a cloud tenant.

No function URL is deployed. Lambda invoke permissions must be restricted to API
Gateway/the release operator; raw client headers are never treated as claims.
"""
from dataclasses import dataclass
import time
from uuid import UUID, uuid5, NAMESPACE_URL

from fastapi import HTTPException, Request
from job_hunter.config import settings


@dataclass(frozen=True)
class CloudIdentity:
    user_id: UUID
    subject: str
    display_name: str


def cloud_identity(request: Request) -> CloudIdentity:
    claims = request.scope.get("aws.event", {}).get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    try:
        valid = (claims["iss"] == settings.cognito_issuer
                 and claims["client_id"] == settings.cognito_client_id
                 and claims["token_use"] == "access"
                 and float(claims["exp"]) > time.time()
                 and settings.api_scope in claims.get("scope", "").split())
        subject = str(UUID(claims["sub"]))
    except (KeyError, TypeError, ValueError):
        valid = False
        subject = ""
    if not valid:
        raise HTTPException(401, detail={"code": "AUTH_REQUIRED", "message": "Please sign in again"})
    # Derive the tenant ID before any DB lookup, so the RLS-protected users table
    # can bootstrap the caller without a privileged cross-tenant lookup function.
    user_id = uuid5(NAMESPACE_URL, f"{settings.cognito_issuer}#{subject}")
    return CloudIdentity(user_id, subject, "Job seeker")
