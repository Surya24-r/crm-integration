"""Shared client instances."""
from app.crm_client import CrmClient
from app.zoho_client import ZohoClient

crm = CrmClient()
zoho = ZohoClient()