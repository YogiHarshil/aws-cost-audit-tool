"""Finding data model for wasteful AWS resources."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


def _utc_now() -> datetime:
    """Timezone-aware UTC now (replaces deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


@dataclass
class Finding:
    """Represents a single wasteful AWS resource."""

    resource_id: str  # e.g., "i-1234567890abcdef0", "vol-abc123"
    resource_type: str  # "EC2", "RDS", "EBS", "EIP", "S3"
    region: str  # AWS region code, e.g., "us-east-1"
    issue_type: str  # "stopped", "low_utilization", "unattached", etc.
    description: str  # Human-readable explanation of the issue
    monthly_savings: float  # Estimated monthly savings in USD
    severity: str  # "High", "Medium", or "Low"
    details: Dict  # Additional metadata (instance type, size, tags, etc.)
    ai_explanation: Optional[str] = None  # AI-generated explanation (nullable)
    discovered_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self):
        """Validate field values."""
        # Validate severity
        if self.severity not in ["High", "Medium", "Low"]:
            raise ValueError(f"Invalid severity: {self.severity}")

        # Validate monthly_savings
        if self.monthly_savings < 0:
            raise ValueError(f"Negative savings not allowed: {self.monthly_savings}")

        # Validate resource_type
        valid_types = [
            "EC2", "RDS", "EBS", "EIP", "S3", "Cost Explorer",
            "EBS Snapshot", "Reserved Instance",
            "SavingsPlans", "TrustedAdvisor",  # New scanner types
        ]
        if self.resource_type not in valid_types:
            raise ValueError(f"Invalid resource_type: {self.resource_type}")
