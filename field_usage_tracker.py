"""
Enhanced Field usage tracking functionality for Salesforce metadata
"""
from typing import Dict, List, Set
from simple_salesforce import Salesforce
import urllib.parse
import re


class FieldUsageTracker:
    """Tracks where fields are used across Salesforce metadata"""

    def __init__(self, sf: Salesforce, status_callback=None):
        """Initialize with Salesforce connection"""
        self.sf = sf
        self.status_callback = status_callback
        # Cache to store usage data
        self.usage_cache: Dict[str, Dict[str, List[str]]] = {}

    def get_field_usage(self, object_name: str, field_api_name: str) -> str:
        """
        Get formatted usage string for a field
        Returns format like:
        Page Layouts
        - Layout1
        - Layout2

        Apex Classes
        - Class1
        """
        if object_name not in self.usage_cache:
            self._build_usage_cache_for_object(object_name)

        field_key = f"{object_name}.{field_api_name}"
        usage_data = self.usage_cache.get(object_name, {}).get(field_key, {})

        if not usage_data:
            return ""

        # Format the usage data
        formatted_sections = []

        # Define the order of sections
        section_order = [
            'Page Layouts',
            'Record Types',
            'Validation Rules',
            'Workflows',
            'Flows',
            'Process Builder',
            'Apex Classes',
            'Apex Triggers',
            'Visualforce Pages',
            'Visualforce Components',
            'Lightning Components',
            'Custom Buttons/Links',
            'Email Templates'
        ]

        for section in section_order:
            if section in usage_data and usage_data[section]:
                formatted_sections.append(f"{section}")
                for item in sorted(usage_data[section]):
                    formatted_sections.append(f"- {item}")
                formatted_sections.append("")  # Empty line between sections

        return "\n".join(formatted_sections).strip()

    def _build_usage_cache_for_object(self, object_name: str):
        """Build usage cache for all fields in an object"""
        self._log_status(f"  Building field usage cache for {object_name}...")

        usage_data = {}

        try:
            # Query Validation Rules
            validation_usage = self._get_validation_rule_usage(object_name)
            self._merge_usage_data(usage_data, validation_usage, 'Validation Rules')

            # Query Workflows
            workflow_usage = self._get_workflow_usage(object_name)
            self._merge_usage_data(usage_data, workflow_usage, 'Workflows')

            # Query Flows
            flow_usage = self._get_flow_usage(object_name)
            self._merge_usage_data(usage_data, flow_usage, 'Flows')

            # Query Apex Classes
            apex_usage = self._get_apex_usage(object_name)
            self._merge_usage_data(usage_data, apex_usage, 'Apex Classes')

            # Query Apex Triggers
            trigger_usage = self._get_trigger_usage(object_name)
            self._merge_usage_data(usage_data, trigger_usage, 'Apex Triggers')

            # Query Visualforce Pages
            vf_page_usage = self._get_visualforce_page_usage(object_name)
            self._merge_usage_data(usage_data, vf_page_usage, 'Visualforce Pages')

            # Query Visualforce Components
            vf_comp_usage = self._get_visualforce_component_usage(object_name)
            self._merge_usage_data(usage_data, vf_comp_usage, 'Visualforce Components')

            # Query Page Layouts (ENHANCED)
            page_layout_usage = self._get_page_layout_usage(object_name)
            self._merge_usage_data(usage_data, page_layout_usage, 'Page Layouts')

            # Query Record Types
            record_type_usage = self._get_record_type_usage(object_name)
            self._merge_usage_data(usage_data, record_type_usage, 'Record Types')

            # Query Custom Buttons/Links
            button_usage = self._get_custom_button_usage(object_name)
            self._merge_usage_data(usage_data, button_usage, 'Custom Buttons/Links')

            # Query Email Templates
            email_template_usage = self._get_email_template_usage(object_name)
            self._merge_usage_data(usage_data, email_template_usage, 'Email Templates')

            # Query Lightning Components (Aura)
            aura_usage = self._get_aura_component_usage(object_name)
            self._merge_usage_data(usage_data, aura_usage, 'Lightning Components')

            self.usage_cache[object_name] = usage_data
            self._log_status(f"  ✅ Usage cache built")

        except Exception as e:
            self._log_status(f"  ⚠️  Warning: Could not build complete usage cache: {str(e)}")
            self.usage_cache[object_name] = usage_data

    def _merge_usage_data(self, usage_data: Dict, field_usage: Dict[str, Set[str]], category: str):
        """Merge field usage data into the main usage dictionary"""
        for field_key, items in field_usage.items():
            if field_key not in usage_data:
                usage_data[field_key] = {}
            if category not in usage_data[field_key]:
                usage_data[field_key][category] = []
            usage_data[field_key][category].extend(sorted(items))

    def _tooling_query(self, soql: str):
        """Execute a Tooling API query with proper URL encoding"""
        try:
            encoded_query = urllib.parse.quote(soql)
            url = f"tooling/query/?q={encoded_query}"
            return self.sf.restful(url, method='GET')
        except Exception as e:
            self._log_status(f"    ⚠️  Tooling query error: {str(e)}")
            return {'records': []}

    def _get_page_layout_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get page layout usage for object fields using Tooling API (ENHANCED)"""
        field_usage = {}

        try:
            # First, get list of layout IDs (without Metadata - avoids the "no more than one row" error)
            soql = f"SELECT Id, Name FROM Layout WHERE EntityDefinitionId = '{object_name}'"
            result = self._tooling_query(soql)

            # Now query each layout individually with Metadata
            for layout in result.get('records', []):
                layout_id = layout.get('Id', '')
                layout_name = layout.get('Name', '')

                if not layout_id:
                    continue

                try:
                    # Query individual layout with Metadata (only 1 row at a time)
                    soql_single = f"SELECT Id, Name, Metadata FROM Layout WHERE Id = '{layout_id}'"
                    single_result = self._tooling_query(soql_single)

                    if not single_result.get('records'):
                        continue

                    metadata = single_result['records'][0].get('Metadata', {})

                    if not metadata:
                        continue

                    # Parse layoutItems to find fields on the layout
                    layout_sections = metadata.get('layoutSections', [])
                    
                    # Safety check: ensure layout_sections is not None
                    if not layout_sections:
                        layout_sections = []

                    for section in layout_sections:
                        layout_columns = section.get('layoutColumns', [])
                        
                        # Safety check: ensure layout_columns is not None
                        if not layout_columns:
                            layout_columns = []

                        for column in layout_columns:
                            layout_items = column.get('layoutItems', [])
                            
                            # Safety check: ensure layout_items is not None
                            if not layout_items:
                                layout_items = []

                            for item in layout_items:
                                field_name = item.get('field')
                                if field_name:
                                    field_key = f"{object_name}.{field_name}"
                                    if field_key not in field_usage:
                                        field_usage[field_key] = set()
                                    field_usage[field_key].add(layout_name)

                except Exception as layout_error:
                    self._log_status(f"    ⚠️  Could not query layout {layout_name}: {str(layout_error)}")
                    continue

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query page layouts: {str(e)}")

        return field_usage

    def _get_record_type_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get record type usage for picklist values"""
        field_usage = {}

        try:
            soql = f"SELECT Id, Name, DeveloperName FROM RecordType WHERE SobjectType = '{object_name}'"
            result = self.sf.query(soql)

            # Note: RecordType field-level dependencies require metadata API
            # For now, we just note which record types exist for the object
            for rt in result.get('records', []):
                rt_name = rt.get('Name', '')
                # This would need Metadata API to get field-level details
                # Placeholder for future enhancement

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query record types: {str(e)}")

        return field_usage

    def _get_workflow_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get workflow rule usage for object fields"""
        field_usage = {}

        try:
            soql = f"SELECT Name, Metadata FROM WorkflowRule WHERE TableEnumOrId = '{object_name}'"
            result = self._tooling_query(soql)

            for rule in result.get('records', []):
                rule_name = rule.get('Name', '')
                metadata = rule.get('Metadata', {})

                if not metadata:
                    continue

                # Parse formula from workflow criteria
                formula = metadata.get('formula', '')
                if formula:
                    fields = self._extract_fields_from_formula(formula, object_name)
                    for field in fields:
                        field_key = f"{object_name}.{field}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(rule_name)

                # Parse workflow actions
                actions = metadata.get('actions', [])
                for action in actions:
                    # Field updates
                    if action.get('type') == 'FieldUpdate':
                        field_name = action.get('name', '')
                        if field_name:
                            field_key = f"{object_name}.{field_name}"
                            if field_key not in field_usage:
                                field_usage[field_key] = set()
                            field_usage[field_key].add(f"{rule_name} (Field Update)")

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query workflows: {str(e)}")

        return field_usage

    def _get_flow_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get flow usage for object fields"""
        field_usage = {}

        try:
            # Query active flows
            soql = "SELECT Id, MasterLabel, ProcessType, Status FROM Flow WHERE Status = 'Active'"
            result = self._tooling_query(soql)

            # Note: Full flow parsing requires Metadata API
            # This is a simplified version that checks flow metadata
            for flow in result.get('records', []):
                flow_name = flow.get('MasterLabel', '')
                # Would need to parse flow metadata XML to find field references
                # Placeholder for future enhancement

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query flows: {str(e)}")

        return field_usage

    def _get_custom_button_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get custom button/link usage for object fields"""
        field_usage = {}

        try:
            # WebLink correct field is 'SobjectType' not 'PageOrSobjectType'
            soql = f"SELECT Id, Name, Url FROM WebLink WHERE PageOrSobjectType = '{object_name}'"
            # result = self._tooling_query(soql) # No need to use tooling API
            result = self.sf.query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for button in result.get('records', []):
                button_name = button.get('Name', '')
                url = button.get('Url', '')

                if not url:
                    continue

                # Check if URL contains field references
                for field_name in field_names:
                    # Look for merge field patterns: {!Field__c} or {!ObjectName.Field__c}
                    if field_name in url or f"{{!{field_name}}}" in url:
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(button_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query custom buttons: {str(e)}")

        return field_usage

    def _get_email_template_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get email template usage for object fields"""
        field_usage = {}

        try:
            # Query email templates that might reference this object
            soql = "SELECT Id, Name, Body, HtmlValue FROM EmailTemplate LIMIT 1000"
            result = self.sf.query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for template in result.get('records', []):
                template_name = template.get('Name', '')
                body = template.get('Body', '') or ''
                html_value = template.get('HtmlValue', '') or ''

                combined_content = body + ' ' + html_value

                # Look for merge field patterns
                for field_name in field_names:
                    # Patterns: {!ObjectName.Field__c} or {!Field__c}
                    pattern = f"{{!.*{field_name}.*}}"
                    if re.search(pattern, combined_content, re.IGNORECASE):
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(template_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query email templates: {str(e)}")

        return field_usage

    def _get_aura_component_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get Lightning (Aura) component usage for object fields"""
        field_usage = {}

        try:
            # AuraDefinition correct fields: AuraDefinitionBundleId, Format, Source
            # We need to query differently - get bundle info first
            soql = "SELECT AuraDefinitionBundleId, AuraDefinitionBundle.DeveloperName, Source FROM AuraDefinition WHERE DefType = 'COMPONENT' LIMIT 1000"
            result = self._tooling_query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for component in result.get('records', []):
                # Get component name from the bundle relationship
                bundle = component.get('AuraDefinitionBundle', {})
                comp_name = bundle.get('DeveloperName', 'Unknown') if bundle else 'Unknown'
                source = component.get('Source', '')

                if not source:
                    continue

                # Check if component references the object
                if object_name not in source:
                    continue

                # Look for field references
                for field_name in field_names:
                    if field_name in source:
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(comp_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query Lightning components: {str(e)}")

        return field_usage

    def _get_validation_rule_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get validation rule usage for object fields (FIXED: Query one record at a time)"""
        field_usage = {}

        try:
            # First, get list of ValidationRule IDs (without Metadata - avoids the "no more than one row" error)
            soql = f"SELECT Id, ValidationName FROM ValidationRule WHERE EntityDefinition.QualifiedApiName = '{object_name}'"
            result = self._tooling_query(soql)

            # Now query each validation rule individually with Metadata
            for rule in result.get('records', []):
                rule_id = rule.get('Id', '')
                rule_name = rule.get('ValidationName', '')

                if not rule_id:
                    continue

                try:
                    # Query individual validation rule with Metadata (only 1 row at a time)
                    soql_single = f"SELECT Id, ValidationName, Metadata FROM ValidationRule WHERE Id = '{rule_id}'"
                    single_result = self._tooling_query(soql_single)

                    if not single_result.get('records'):
                        continue

                    metadata = single_result['records'][0].get('Metadata', {})

                    if not metadata:
                        continue

                    # Parse the error display field if available
                    error_field = metadata.get('errorDisplayField')
                    if error_field:
                        field_key = f"{object_name}.{error_field}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(rule_name)

                    # Extract fields from formula
                    formula = metadata.get('errorConditionFormula', '')
                    if formula:
                        fields = self._extract_fields_from_formula(formula, object_name)
                        for field in fields:
                            field_key = f"{object_name}.{field}"
                            if field_key not in field_usage:
                                field_usage[field_key] = set()
                            field_usage[field_key].add(rule_name)

                except Exception as e:
                    self._log_status(f"    ⚠️  Could not query validation rule {rule_name}: {str(e)}")

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query validation rules: {str(e)}")

        return field_usage

    def _get_apex_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get Apex class usage for object fields"""
        field_usage = {}

        try:
            soql = "SELECT Name, Body FROM ApexClass LIMIT 500"
            result = self._tooling_query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for apex_class in result.get('records', []):
                class_name = apex_class.get('Name', '')
                body = apex_class.get('Body', '')

                if not body:
                    continue

                # Check if this class references the object
                if object_name not in body:
                    continue

                # Look for field references
                for field_name in field_names:
                    # Look for common patterns: obj.field, field__c, etc.
                    if self._is_field_referenced_in_code(field_name, body):
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(class_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query Apex classes: {str(e)}")

        return field_usage

    def _get_trigger_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get Apex trigger usage for object fields"""
        field_usage = {}

        try:
            soql = f"SELECT Name, Body FROM ApexTrigger WHERE TableEnumOrId = '{object_name}'"
            result = self._tooling_query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for trigger in result.get('records', []):
                trigger_name = trigger.get('Name', '')
                body = trigger.get('Body', '')

                if not body:
                    continue

                for field_name in field_names:
                    if self._is_field_referenced_in_code(field_name, body):
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(trigger_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query triggers: {str(e)}")

        return field_usage

    def _get_visualforce_page_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get Visualforce page usage for object fields"""
        field_usage = {}

        try:
            soql = "SELECT Name, Markup FROM ApexPage LIMIT 500"
            result = self._tooling_query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for page in result.get('records', []):
                page_name = page.get('Name', '')
                markup = page.get('Markup', '')

                if not markup:
                    continue

                if object_name not in markup:
                    continue

                for field_name in field_names:
                    # Look for VF patterns: {!obj.field} or value="{!field}"
                    if self._is_field_referenced_in_vf(field_name, markup):
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(page_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query Visualforce pages: {str(e)}")

        return field_usage

    def _get_visualforce_component_usage(self, object_name: str) -> Dict[str, Set[str]]:
        """Get Visualforce component usage for object fields"""
        field_usage = {}

        try:
            soql = "SELECT Name, Markup FROM ApexComponent LIMIT 500"
            result = self._tooling_query(soql)

            obj_describe = getattr(self.sf, object_name).describe()
            field_names = [field.get('name', '') for field in obj_describe['fields']]

            for component in result.get('records', []):
                comp_name = component.get('Name', '')
                markup = component.get('Markup', '')

                if not markup:
                    continue

                if object_name not in markup:
                    continue

                for field_name in field_names:
                    if self._is_field_referenced_in_vf(field_name, markup):
                        field_key = f"{object_name}.{field_name}"
                        if field_key not in field_usage:
                            field_usage[field_key] = set()
                        field_usage[field_key].add(comp_name)

        except Exception as e:
            self._log_status(f"    ⚠️  Could not query Visualforce components: {str(e)}")

        return field_usage

    def _extract_fields_from_formula(self, formula: str, object_name: str) -> List[str]:
        """Extract field names from formula (ENHANCED)"""
        fields = []

        # Pattern 1: Custom fields (Field__c)
        custom_field_pattern = r'\b([A-Za-z][A-Za-z0-9_]*__c)\b'
        matches = re.findall(custom_field_pattern, formula)
        fields.extend(matches)

        # Pattern 2: Standard fields (common ones)
        standard_fields = ['Name', 'Id', 'CreatedDate', 'LastModifiedDate', 'OwnerId',
                          'CreatedById', 'LastModifiedById', 'IsDeleted']
        for std_field in standard_fields:
            if re.search(r'\b' + std_field + r'\b', formula):
                fields.append(std_field)

        return list(set(fields))  # Remove duplicates

    def _is_field_referenced_in_code(self, field_name: str, code: str) -> bool:
        """Check if field is referenced in Apex code (ENHANCED)"""
        # Pattern 1: Direct field reference with dot notation: obj.Field__c
        pattern1 = r'\.\s*' + re.escape(field_name) + r'\b'

        # Pattern 2: String reference: 'Field__c' or "Field__c"
        pattern2 = r'["\']' + re.escape(field_name) + r'["\']'

        # Pattern 3: Map key reference: ['Field__c'] or ['Field__c']
        pattern3 = r'\[\s*["\']' + re.escape(field_name) + r'["\']\s*\]'

        return (re.search(pattern1, code) is not None or
                re.search(pattern2, code) is not None or
                re.search(pattern3, code) is not None)

    def _is_field_referenced_in_vf(self, field_name: str, markup: str) -> bool:
        """Check if field is referenced in Visualforce markup (ENHANCED)"""
        # Pattern 1: Merge field: {!field} or {!obj.field}
        pattern1 = r'\{!.*' + re.escape(field_name) + r'.*\}'

        # Pattern 2: Value attribute: value="{!field}"
        pattern2 = r'value\s*=\s*["\']?\{!.*' + re.escape(field_name) + r'.*\}["\']?'

        return (re.search(pattern1, markup, re.IGNORECASE) is not None or
                re.search(pattern2, markup, re.IGNORECASE) is not None)

    def _log_status(self, message: str):
        """Log status message"""
        if self.status_callback:
            self.status_callback(message, verbose=True)