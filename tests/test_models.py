"""Unit tests for data models (Finding, Report, ScanConfig)."""

import pytest
from datetime import datetime
from models.finding import Finding
from models.report import Report, ScanConfig


class TestFinding:
    """Tests for Finding dataclass."""

    def test_valid_finding_creation(self):
        """Test creating a valid Finding."""
        finding = Finding(
            resource_id="i-1234567890abcdef0",
            resource_type="EC2",
            region="us-east-1",
            issue_type="stopped",
            description="Instance stopped for 12 days",
            monthly_savings=43.80,
            severity="High",
            details={"instance_type": "t3.medium"}
        )
        assert finding.resource_id == "i-1234567890abcdef0"
        assert finding.severity == "High"
        assert finding.monthly_savings == 43.80
        assert isinstance(finding.discovered_at, datetime)

    def test_invalid_severity(self):
        """Test that invalid severity raises ValueError."""
        with pytest.raises(ValueError, match="Invalid severity"):
            Finding(
                resource_id="i-123",
                resource_type="EC2",
                region="us-east-1",
                issue_type="stopped",
                description="Test",
                monthly_savings=10.0,
                severity="Critical",  # Invalid
                details={}
            )

    def test_negative_savings(self):
        """Test that negative savings raise ValueError."""
        with pytest.raises(ValueError, match="Negative savings not allowed"):
            Finding(
                resource_id="i-123",
                resource_type="EC2",
                region="us-east-1",
                issue_type="stopped",
                description="Test",
                monthly_savings=-10.0,  # Invalid
                severity="High",
                details={}
            )

    def test_invalid_resource_type(self):
        """Test that invalid resource_type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid resource_type"):
            Finding(
                resource_id="i-123",
                resource_type="Lambda",  # Invalid
                region="us-east-1",
                issue_type="stopped",
                description="Test",
                monthly_savings=10.0,
                severity="High",
                details={}
            )

    def test_all_valid_resource_types(self):
        """Test all valid resource types."""
        valid_types = ["EC2", "RDS", "EBS", "EIP", "S3", "Cost Explorer"]
        for resource_type in valid_types:
            finding = Finding(
                resource_id="test-id",
                resource_type=resource_type,
                region="us-east-1",
                issue_type="test",
                description="Test",
                monthly_savings=10.0,
                severity="High",
                details={}
            )
            assert finding.resource_type == resource_type

    def test_all_valid_severities(self):
        """Test all valid severities."""
        for severity in ["High", "Medium", "Low"]:
            finding = Finding(
                resource_id="test-id",
                resource_type="EC2",
                region="us-east-1",
                issue_type="test",
                description="Test",
                monthly_savings=10.0,
                severity=severity,
                details={}
            )
            assert finding.severity == severity


class TestReport:
    """Tests for Report dataclass."""

    def create_sample_finding(self, savings: float = 100.0, severity: str = "High"):
        """Helper to create a sample finding."""
        return Finding(
            resource_id="test-id",
            resource_type="EC2",
            region="us-east-1",
            issue_type="test",
            description="Test finding",
            monthly_savings=savings,
            severity=severity,
            details={}
        )

    def test_valid_report_creation(self):
        """Test creating a valid Report."""
        finding1 = self.create_sample_finding(100.0, "High")
        finding2 = self.create_sample_finding(50.0, "Medium")

        report = Report(
            account_id="123456789012",
            account_alias="test-account",
            client_name="Test Client",
            scan_date=datetime(2026, 5, 13, 10, 0, 0),
            regions_scanned=["us-east-1", "us-west-2"],
            findings=[finding1, finding2],
            total_savings=0,  # Should be auto-computed
            cost_trends={"daily_costs": {}}
        )

        assert report.account_id == "123456789012"
        assert report.total_savings == 150.0  # Auto-computed
        assert len(report.findings) == 2

    def test_empty_regions_scanned(self):
        """Test that empty regions_scanned raises ValueError."""
        with pytest.raises(ValueError, match="regions_scanned cannot be empty"):
            Report(
                account_id="123456789012",
                account_alias="test",
                client_name="Test",
                scan_date=datetime.now(),
                regions_scanned=[],  # Invalid
                findings=[],
                total_savings=0,
                cost_trends={}
            )

    def test_findings_sorted_by_savings(self):
        """Test that findings are sorted by savings DESC."""
        finding1 = self.create_sample_finding(50.0, "Medium")
        finding2 = self.create_sample_finding(200.0, "High")
        finding3 = self.create_sample_finding(100.0, "Low")

        report = Report(
            account_id="123456789012",
            account_alias="test",
            client_name="Test",
            scan_date=datetime.now(),
            regions_scanned=["us-east-1"],
            findings=[finding1, finding2, finding3],
            total_savings=0,
            cost_trends={}
        )

        # Should be sorted DESC: 200, 100, 50
        assert report.findings[0].monthly_savings == 200.0
        assert report.findings[1].monthly_savings == 100.0
        assert report.findings[2].monthly_savings == 50.0

    def test_total_savings_auto_computed(self):
        """Test that total_savings is computed from findings if zero."""
        findings = [
            self.create_sample_finding(100.0),
            self.create_sample_finding(200.0),
            self.create_sample_finding(50.0)
        ]

        report = Report(
            account_id="123456789012",
            account_alias="test",
            client_name="Test",
            scan_date=datetime.now(),
            regions_scanned=["us-east-1"],
            findings=findings,
            total_savings=0,  # Should auto-compute to 350.0
            cost_trends={}
        )

        assert report.total_savings == 350.0

    def test_findings_by_severity(self):
        """Test findings_by_severity property."""
        findings = [
            self.create_sample_finding(100.0, "High"),
            self.create_sample_finding(50.0, "High"),
            self.create_sample_finding(30.0, "Medium"),
            self.create_sample_finding(10.0, "Low")
        ]

        report = Report(
            account_id="123456789012",
            account_alias="test",
            client_name="Test",
            scan_date=datetime.now(),
            regions_scanned=["us-east-1"],
            findings=findings,
            total_savings=0,
            cost_trends={}
        )

        severity_counts = report.findings_by_severity
        assert severity_counts["High"] == 2
        assert severity_counts["Medium"] == 1
        assert severity_counts["Low"] == 1

    def test_findings_count(self):
        """Test findings_count property."""
        findings = [self.create_sample_finding() for _ in range(5)]

        report = Report(
            account_id="123456789012",
            account_alias="test",
            client_name="Test",
            scan_date=datetime.now(),
            regions_scanned=["us-east-1"],
            findings=findings,
            total_savings=0,
            cost_trends={}
        )

        assert report.findings_count == 5


class TestScanConfig:
    """Tests for ScanConfig dataclass."""

    def test_valid_config_with_skip_ai(self):
        """Test creating config with skip_ai=True."""
        config = ScanConfig(
            aws_profile="test-profile",
            skip_ai=True
        )
        assert config.aws_profile == "test-profile"
        assert config.skip_ai is True
        assert config.exclude_tags == []  # Should initialize to empty list

    def test_config_requires_openai_key_without_skip_ai(self):
        """Test that OpenAI key is required when AI enabled."""
        with pytest.raises(ValueError, match="OPENAI_API_KEY required"):
            ScanConfig(
                aws_profile="test",
                skip_ai=False,
                openai_api_key=None  # Invalid without skip_ai
            )

    def test_config_with_openai_key(self):
        """Test config with OpenAI key provided."""
        config = ScanConfig(
            aws_profile="test",
            openai_api_key="sk-test-key",
            skip_ai=False
        )
        assert config.openai_api_key == "sk-test-key"

    def test_exclude_tags_initialization(self):
        """Test that exclude_tags initializes to empty list if None."""
        config = ScanConfig(
            skip_ai=True,
            exclude_tags=None
        )
        assert config.exclude_tags == []
        assert isinstance(config.exclude_tags, list)

    def test_output_dir_creation(self):
        """Test that output directory is created if it doesn't exist."""
        import os
        import tempfile

        test_dir = os.path.join(tempfile.gettempdir(), "test_audit_output")

        # Clean up if exists
        if os.path.exists(test_dir):
            os.rmdir(test_dir)

        config = ScanConfig(
            skip_ai=True,
            output_dir=test_dir
        )

        assert os.path.exists(test_dir)

        # Clean up
        os.rmdir(test_dir)
