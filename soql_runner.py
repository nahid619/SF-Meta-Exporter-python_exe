"""
SOQL Query Runner - Execute SOQL queries and export results
"""
import csv
import re
from typing import List, Dict, Tuple, Optional, Set
from datetime import datetime
from salesforce_client import SalesforceClient


class SOQLRunner:
    """Handles SOQL query execution and result processing"""
    
    def __init__(self, sf_client: SalesforceClient):
        """Initialize with Salesforce client"""
        self.sf_client = sf_client
        self.sf = sf_client.sf
        # Cache for object and field metadata
        self.object_cache: Dict[str, Dict] = {}
        self.all_objects: List[str] = []
    
    def execute_query(self, soql: str) -> Tuple[List[Dict], int, Optional[str]]:
        """
        Execute a SOQL query and return results
        
        Args:
            soql: SOQL query string
            
        Returns:
            Tuple of (records, total_count, error_message)
            If successful: (records, count, None)
            If failed: ([], 0, error_message)
        """
        try:
            # Clean the query
            soql = soql.strip()
            
            if not soql:
                return [], 0, "Query cannot be empty"
            
            # Execute query
            result = self.sf.query_all(soql)
            
            records = result.get('records', [])
            total_count = result.get('totalSize', len(records))
            
            # Clean records (remove attributes metadata)
            cleaned_records = self._clean_records(records)
            
            return cleaned_records, total_count, None
            
        except Exception as e:
            error_msg = str(e)
            return [], 0, error_msg
    
    def export_to_csv(self, records: List[Dict], output_path: str) -> str:
        """
        Export query results to CSV
        
        Args:
            records: List of record dictionaries
            output_path: Path to save CSV file
            
        Returns:
            Path to created CSV file
        """
        if not records:
            raise ValueError("No records to export")
        
        # Get all unique field names from records
        all_fields = set()
        for record in records:
            all_fields.update(record.keys())
        
        # Sort fields for consistent column order
        headers = sorted(list(all_fields))
        
        # Write CSV
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(records)
        
        return output_path
    
    def get_object_from_query(self, soql: str) -> Optional[str]:
        """
        Extract object name from SOQL query
        
        Args:
            soql: SOQL query string
            
        Returns:
            Object API name or None
        """
        try:
            # Pattern to match FROM clause
            # Handles: FROM Object, FROM Object WHERE, FROM Object LIMIT, etc.
            pattern = r'\bFROM\s+([A-Za-z0-9_]+)'
            match = re.search(pattern, soql, re.IGNORECASE)
            
            if match:
                return match.group(1)
            
            return None
            
        except Exception:
            return None
    
    def get_field_suggestions(self, object_name: str) -> List[Dict[str, str]]:
        """
        Get field suggestions for an object
        
        Args:
            object_name: Salesforce object API name
            
        Returns:
            List of field dictionaries with 'name', 'label', 'type'
        """
        try:
            # Check cache first
            if object_name not in self.object_cache:
                self._cache_object_metadata(object_name)
            
            return self.object_cache.get(object_name, {}).get('fields', [])
            
        except Exception:
            return []
    
    def get_all_objects(self) -> List[str]:
        """
        Get all queryable objects in the org
        
        Returns:
            List of object API names
        """
        if not self.all_objects:
            self.all_objects = self.sf_client.get_all_objects()
        
        return self.all_objects
    
    def validate_query(self, soql: str) -> Tuple[bool, Optional[str]]:
        """
        Validate SOQL query syntax (basic validation)
        
        Args:
            soql: SOQL query string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        soql = soql.strip()
        
        if not soql:
            return False, "Query cannot be empty"
        
        # Check for SELECT
        if not re.search(r'\bSELECT\b', soql, re.IGNORECASE):
            return False, "Query must start with SELECT"
        
        # Check for FROM
        if not re.search(r'\bFROM\b', soql, re.IGNORECASE):
            return False, "Query must contain FROM clause"
        
        # Check for basic SQL injection patterns (basic security)
        dangerous_patterns = [r';', r'--', r'/\*', r'\*/', r'\bEXEC\b', r'\bEXECUTE\b']
        for pattern in dangerous_patterns:
            if re.search(pattern, soql, re.IGNORECASE):
                return False, "Query contains potentially dangerous characters"
        
        return True, None
    
    def _clean_records(self, records: List[Dict]) -> List[Dict]:
        """
        Clean records by removing Salesforce metadata attributes
        
        Args:
            records: Raw records from Salesforce
            
        Returns:
            Cleaned records
        """
        cleaned = []
        
        for record in records:
            clean_record = {}
            for key, value in record.items():
                # Skip attributes metadata
                if key == 'attributes':
                    continue
                
                # Handle relationship fields (nested objects)
                if isinstance(value, dict):
                    # If it's a related record, flatten it
                    if 'attributes' in value:
                        # This is a relationship query result
                        for sub_key, sub_value in value.items():
                            if sub_key != 'attributes':
                                clean_record[f"{key}.{sub_key}"] = sub_value
                    else:
                        # Keep as-is if no attributes
                        clean_record[key] = str(value)
                else:
                    clean_record[key] = value
            
            cleaned.append(clean_record)
        
        return cleaned
    
    def _cache_object_metadata(self, object_name: str):
        """
        Cache object metadata for field suggestions
        
        Args:
            object_name: Salesforce object API name
        """
        try:
            describe = getattr(self.sf, object_name).describe()
            
            fields = []
            for field in describe.get('fields', []):
                fields.append({
                    'name': field.get('name', ''),
                    'label': field.get('label', ''),
                    'type': field.get('type', ''),
                    'referenceTo': field.get('referenceTo', [])
                })
            
            self.object_cache[object_name] = {
                'label': describe.get('label', ''),
                'fields': fields
            }
            
        except Exception:
            self.object_cache[object_name] = {'fields': []}
    
    def get_query_history(self) -> List[str]:
        """
        Get query history (placeholder for future implementation)
        
        Returns:
            List of recent queries
        """
        # This could be implemented to save/load from a file
        return []
    
    def format_query(self, soql: str) -> str:
        """
        Format SOQL query for better readability
        
        Args:
            soql: SOQL query string
            
        Returns:
            Formatted query
        """
        # Basic formatting
        formatted = soql.strip()
        
        # Add newlines after major clauses
        formatted = re.sub(r'\bFROM\b', '\nFROM', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bWHERE\b', '\nWHERE', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bORDER BY\b', '\nORDER BY', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bGROUP BY\b', '\nGROUP BY', formatted, flags=re.IGNORECASE)
        formatted = re.sub(r'\bLIMIT\b', '\nLIMIT', formatted, flags=re.IGNORECASE)
        
        return formatted
