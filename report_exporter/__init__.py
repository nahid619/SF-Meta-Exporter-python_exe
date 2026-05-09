"""
Salesforce Report Exporter Module
Integrated into main application as 6th button

This module provides comprehensive Salesforce report export functionality
including search, selection, and bulk export capabilities.
"""

from .main_app import SalesforceExporterApp

__version__ = "1.0.0"
__all__ = ['SalesforceExporterApp']

# Module metadata
MODULE_NAME = "Report Exporter"
MODULE_DESCRIPTION = "Export Salesforce reports with advanced search and bulk operations"