"""Custom deal fields. Created once by scripts/setup_crm_fields.py, resolved by name at runtime."""

# Fields the integration WRITES (it owns these; people should not edit them)
OWNED_FIELDS = {
    "Zoho Customer ID": "varchar",
    "Zoho Sales Order": "varchar",
    "Zoho Sync Status": "varchar",
    "Zoho Sync Error": "text",
    "Zoho SO Total": "double",
    "Zoho % Invoiced": "double",
    "Zoho % Collected": "double",
    "Zoho Invoiced Unpaid": "double",
    "Zoho Not Yet Invoiced": "double",
    "Zoho Next Due Date": "date",
    "Zoho Overdue": "varchar",
}

# Fields sales people fill in; the integration only READS these
INPUT_FIELDS = {
    "Customer TRN": "varchar",
    "Go-Live Date": "date",
}

ALL_FIELDS = {**OWNED_FIELDS, **INPUT_FIELDS}