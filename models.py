"""
Data models for Salesforce field and picklist information
UPDATED: Enhanced MetadataField with additional columns
"""
from typing import List, Dict, Optional


class FieldInfo:
    """Represents picklist field metadata"""
    def __init__(self, api_name: str, label: str, is_global: bool = False):
        self.api_name = api_name
        self.label = label
        self.is_global = is_global


class PicklistValueDetail:
    """Represents a single picklist value"""
    def __init__(self, label: str, value: str, is_active: bool = True):
        self.label = label
        self.value = value
        self.is_active = is_active


class ProcessingResult:
    """Stores processing results for an object"""
    def __init__(self):
        self.values_processed = 0
        self.inactive_values = 0
        self.rows: List[List[str]] = []
        self.picklist_fields_count = 0
        self.object_exists = True
        self.error_message = None
        self.global_picklist_count = 0


class MetadataField:
    """
    Represents metadata for a single field
    
    ✅ UPDATED: Added new columns for comprehensive metadata
    """
    def __init__(
        self, 
        object_name: str, 
        field_label: str, 
        api_name: str, 
        data_type: str,  # ✅ NEW: Raw data type (string, number, etc.)
        length: str = "",  # ✅ NEW: Field length/size
        field_type: str = "",  # ✅ ENHANCED: More detailed type info
        required: str = "",  # ✅ NEW: Yes/No if field is required
        picklist_values: str = "",  # ✅ NEW: Comma-separated picklist values
        formula: str = "", 
        external_id: str = "",  # ✅ NEW: Yes/No if external ID
        track_history: str = "",  # ✅ NEW: Yes/No if history tracking enabled
        description: str = "",  # ✅ NEW: Field description
        help_text: str = "", 
        attributes: str = "", 
        field_usage: str = ""
    ):
        self.object_name = object_name
        self.field_label = field_label
        self.api_name = api_name
        self.data_type = data_type  # ✅ NEW
        self.length = length  # ✅ NEW
        self.field_type = field_type  # ✅ ENHANCED
        self.required = required  # ✅ NEW
        self.picklist_values = picklist_values  # ✅ NEW
        self.formula = formula
        self.external_id = external_id  # ✅ NEW
        self.track_history = track_history  # ✅ NEW
        self.description = description  # ✅ NEW
        self.help_text = help_text
        self.attributes = attributes
        self.field_usage = field_usage
    
    def to_row(self) -> List[str]:
        """
        Convert to Excel row format
        
        ✅ UPDATED: New column order with all fields
        """
        return [
            self.object_name,
            self.field_label,
            self.api_name,
            self.data_type,  # ✅ NEW
            self.length,  # ✅ NEW
            self.field_type,  # ✅ ENHANCED
            self.required,  # ✅ NEW
            self.picklist_values,  # ✅ NEW
            self.formula,
            self.external_id,  # ✅ NEW (was "Extend ID")
            self.track_history,  # ✅ NEW
            self.description,  # ✅ NEW
            self.help_text,
            self.attributes,
            self.field_usage
        ]