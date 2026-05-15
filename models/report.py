"""Report and ScanConfig data models."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import os

# Import Finding for type hints
if False:  # TYPE_CHECKING would be more proper, but this works for runtime
    from models.finding import Finding


@dataclass
class Report:
    """Complete audit report for an AWS account."""

    account_id: str  # AWS account ID
    account_alias: str  # AWS account alias (or account_id if no alias)
    client_name: str  # Client name for report cover
    scan_date: datetime  # When the scan was performed
    regions_scanned: List[str]  # List of regions included in scan
    findings: List['Finding']  # All findings, sorted by savings DESC
    total_savings: float  # Sum of all finding savings
    cost_trends: Dict  # Cost Explorer data (service spend, trends)
    executive_summary: Optional[str] = None  # AI-generated summary
    recommendations: Optional[List[Dict]] = None  # Top 5 AI recommendations
    scan_duration_seconds: float = 0.0  # Total scan time
    scan_metadata: Dict = field(default_factory=dict)  # Additional context

    def __post_init__(self):
        """Validate and compute derived fields."""
        # Validate regions_scanned not empty
        if not self.regions_scanned:
            raise ValueError("regions_scanned cannot be empty")

        # Compute total_savings from findings if not set
        if self.total_savings == 0 and self.findings:
            self.total_savings = sum(f.monthly_savings for f in self.findings)

        # Sort findings by savings DESC
        self.findings.sort(key=lambda f: f.monthly_savings, reverse=True)

    @property
    def findings_count(self) -> int:
        """Total number of findings."""
        return len(self.findings)

    @property
    def findings_by_severity(self) -> Dict[str, int]:
        """Count findings by severity level."""
        counts = {"High": 0, "Medium": 0, "Low": 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def findings_by_type(self) -> Dict[str, int]:
        """Count findings by resource type."""
        counts = {}
        for finding in self.findings:
            counts[finding.resource_type] = counts.get(finding.resource_type, 0) + 1
        return counts

    def get_findings_by_region(self, region: str) -> List['Finding']:
        """Get all findings for a specific region."""
        return [f for f in self.findings if f.region == region]


@dataclass
class ScanConfig:
    """Configuration for audit scan."""

    aws_profile: str = "default"
    aws_role_arn: Optional[str] = None
    regions: Optional[List[str]] = None  # None = all enabled regions
    client_name: str = "Client"
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None  # e.g. OpenRouter: https://openrouter.ai/api/v1
    openai_model: str = "gpt-4o-mini"  # e.g. OpenRouter: openai/gpt-4o-mini
    openai_extra_body: Optional[Dict[str, Any]] = None  # e.g. OpenRouter reasoning: {"reasoning": {"enabled": True}}
    openai_default_headers: Optional[Dict[str, str]] = None  # e.g. HTTP-Referer, X-Title for OpenRouter
    skip_ai: bool = False
    output_dir: str = "./output"
    exclude_tags: Optional[List[Dict[str, str]]] = None  # Tag filters
    verbose: bool = False
    max_workers: int = 5  # ThreadPool workers for parallel scanning

    def __post_init__(self):
        """Validate configuration."""
        # Initialize exclude_tags if None
        if self.exclude_tags is None:
            self.exclude_tags = []

        # Validate OpenAI key if AI enabled
        if not self.skip_ai and not self.openai_api_key:
            raise ValueError(
                "OPENAI_API_KEY required when AI summaries enabled. "
                "Set key or use --skip-ai flag."
            )

        # Validate output directory exists or can be created
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)
