from pydantic import BaseModel
from typing import Optional


class AWSCredentials(BaseModel):
    access_key: str
    secret_key: str
    session_token: Optional[str] = None
    region: Optional[str] = "us-east-1"


class GCPCredentials(BaseModel):
    project_id: str
    credentials_json: str
    region: Optional[str] = "us-central1"


class AzureCredentials(BaseModel):
    subscription_id: str
    tenant_id: str
    client_id: str
    client_secret: str
    region: Optional[str] = "eastus"
