"""
Metadata Switch Manager - Handles enabling/disabling Salesforce automation components
FIXED: Deployment, Rollback, Batch Updates, and Trigger Timeouts
"""
import base64
import time
import xml.etree.ElementTree as ET
from typing import Dict, List, Tuple, Optional, Callable
from datetime import datetime
import requests
from simple_salesforce import Salesforce
from trigger_deployer import TriggerDeployer


class MetadataComponent:
    """Represents a single metadata component"""
    
    def __init__(self, name: str, full_name: str, is_active: bool, 
                 component_type: str, metadata: dict = None, record_id: str = None):
        self.name = name
        self.full_name = full_name
        self.is_active = is_active
        self.original_is_active = is_active  # Store original state
        self.component_type = component_type
        self.metadata = metadata or {}
        self.record_id = record_id  # Store the Salesforce record ID
        self.modified = False
    
    def toggle(self):
        """Toggle the active state"""
        self.is_active = not self.is_active
        self.modified = (self.is_active != self.original_is_active)
    
    def set_active(self, active: bool):
        """Set specific active state"""
        self.is_active = active
        self.modified = (self.is_active != self.original_is_active)
    
    def rollback(self):
        """Rollback to original state"""
        self.is_active = self.original_is_active
        self.modified = False
    
    def commit_changes(self):
        """Commit current state as the new original (after successful deploy)"""
        self.original_is_active = self.is_active
        self.modified = False


class MetadataSwitchManager:
    """Manages metadata component switching operations"""
    
    def __init__(self, sf: Salesforce, status_callback: Callable = None):
        self.sf = sf
        self.status_callback = status_callback
        self.base_url = f"https://{sf.sf_instance}"
        self.session_id = sf.session_id
        self.api_version = sf.sf_version
        self.headers = {
            'Authorization': f'Bearer {self.session_id}',
            'Content-Type': 'application/json'
        }
        
        # Component storage
        self.validation_rules: List[MetadataComponent] = []
        self.workflow_rules: List[MetadataComponent] = []
        self.flows: List[MetadataComponent] = []
        self.triggers: List[MetadataComponent] = []
    
    def fetch_all_components(self) -> Dict[str, int]:
        """Fetch all automation components from Salesforce"""
        self._log("=== Fetching Automation Components ===")
        
        stats = {
            'validation_rules': 0,
            'workflow_rules': 0,
            'flows': 0,
            'triggers': 0
        }
        
        try:
            # Fetch Validation Rules
            self._log("Fetching Validation Rules...")
            self.validation_rules = self._fetch_validation_rules()
            stats['validation_rules'] = len(self.validation_rules)
            self._log(f"✅ Found {stats['validation_rules']} Validation Rules")
            
            # Fetch Workflow Rules
            self._log("Fetching Workflow Rules...")
            self.workflow_rules = self._fetch_workflow_rules()
            stats['workflow_rules'] = len(self.workflow_rules)
            self._log(f"✅ Found {stats['workflow_rules']} Workflow Rules")
            
            # Fetch Flows (Process Builder)
            self._log("Fetching Process Flows...")
            self.flows = self._fetch_flows()
            stats['flows'] = len(self.flows)
            self._log(f"✅ Found {stats['flows']} Process Flows")
            
            # Fetch Apex Triggers
            self._log("Fetching Apex Triggers...")
            self.triggers = self._fetch_triggers()
            stats['triggers'] = len(self.triggers)
            self._log(f"✅ Found {stats['triggers']} Apex Triggers")
            
            self._log("=== Fetch Complete ===")
            return stats
            
        except Exception as e:
            self._log(f"❌ Error fetching components: {str(e)}")
            raise
    
    def _fetch_validation_rules(self) -> List[MetadataComponent]:
        """Fetch all validation rules using Tooling API"""
        components = []
        
        try:
            query = """
                SELECT Id, ValidationName, EntityDefinition.QualifiedApiName, 
                       Active
                FROM ValidationRule
                ORDER BY ValidationName
            """
            
            result = self._tooling_query(query)
            
            for record in result.get('records', []):
                entity = record.get('EntityDefinition', {})
                object_name = entity.get('QualifiedApiName', 'Unknown')
                val_name = record.get('ValidationName', '')
                is_active = record.get('Active', False)
                metadata = record.get('Metadata', {})
                record_id = record.get('Id', '')
                
                full_name = f"{object_name}.{val_name}"
                display_name = f"{object_name} - {val_name}"
                
                component = MetadataComponent(
                    name=display_name,
                    full_name=full_name,
                    is_active=is_active,
                    component_type="ValidationRule",
                    metadata=metadata,
                    record_id=record_id
                )
                components.append(component)
        
        except Exception as e:
            self._log(f"Error fetching validation rules: {str(e)}")
        
        return components
    
    def _fetch_workflow_rules(self) -> List[MetadataComponent]:
        """Fetch all workflow rules using Tooling API"""
        components = []
        
        try:
            query = """
                SELECT Id, Name, TableEnumOrId
                FROM WorkflowRule
                ORDER BY TableEnumOrId, Name
            """
            
            result = self._tooling_query(query)
            
            for record in result.get('records', []):
                name = record.get('Name', '')
                object_name = record.get('TableEnumOrId', 'Unknown')
                metadata = record.get('Metadata', {})
                is_active = metadata.get('active', False)
                record_id = record.get('Id', '')
                
                full_name = f"{object_name}.{name}"
                display_name = f"{object_name} - {name}"
                
                component = MetadataComponent(
                    name=display_name,
                    full_name=full_name,
                    is_active=is_active,
                    component_type="WorkflowRule",
                    metadata=metadata,
                    record_id=record_id
                )
                components.append(component)
        
        except Exception as e:
            self._log(f"Error fetching workflow rules: {str(e)}")
        
        return components
    
    def _fetch_flows(self) -> List[MetadataComponent]:
        """Fetch all flows (Process Builder, Record-Triggered, etc.) using Tooling API"""
        components = []
        
        try:
            # Query FlowDefinition first to get the active/latest version of each flow
            query = """
                SELECT Id, ActiveVersionId, LatestVersionId, DeveloperName, MasterLabel
                FROM FlowDefinition
                ORDER BY MasterLabel
            """
            
            definitions_result = self._tooling_query(query)
            
            if not definitions_result.get('records'):
                self._log("No flow definitions found")
                return components
            
            # For each flow definition, fetch its active or latest version
            for definition in definitions_result['records']:
                # Prefer ActiveVersionId, fallback to LatestVersionId
                flow_version_id = definition.get('ActiveVersionId') or definition.get('LatestVersionId')
                
                if not flow_version_id:
                    continue
                
                # Now query the actual Flow record for this specific version
                flow_query = f"""
                    SELECT Id, MasterLabel, ProcessType, Status, VersionNumber
                    FROM Flow
                    WHERE Id = '{flow_version_id}'
                """
                
                flow_result = self._tooling_query(flow_query)
                
                if not flow_result.get('records'):
                    continue
                
                record = flow_result['records'][0]
                name = record.get('MasterLabel', '')
                process_type = record.get('ProcessType', 'Flow')
                status = record.get('Status', 'Draft')
                version = record.get('VersionNumber', 1)
                is_active = (status == 'Active')
                record_id = record.get('Id', '')
                
                # Create display name with process type for clarity
                if process_type == 'Workflow':
                    type_label = 'Process Builder'
                elif process_type == 'AutoLaunchedFlow':
                    type_label = 'Autolaunched Flow'
                elif process_type == 'CustomEvent':
                    type_label = 'Record-Triggered Flow'
                elif process_type == 'InvocableProcess':
                    type_label = 'Invocable Process'
                else:
                    type_label = process_type
                
                display_name = f"{name} ({type_label})"
                
                component = MetadataComponent(
                    name=display_name,
                    full_name=name,
                    is_active=is_active,
                    component_type="Flow",
                    metadata={
                        'status': status,
                        'processType': process_type,
                        'versionNumber': version,
                        'definitionId' : definition.get('Id')
                },
                    record_id=record_id,
                )
                components.append(component)
        
        except Exception as e:
            self._log(f"Error fetching flows: {str(e)}")
        
        return components
    
    def _fetch_triggers(self) -> List[MetadataComponent]:
        """Fetch all Apex triggers using Tooling API"""
        components = []
        
        try:
            query = """
                SELECT Id, Name, TableEnumOrId, Status, Body, ApiVersion
                FROM ApexTrigger
                ORDER BY TableEnumOrId, Name
            """
            
            result = self._tooling_query(query)
            
            for record in result.get('records', []):
                name = record.get('Name', '')
                object_name = record.get('TableEnumOrId', 'Unknown')
                status = record.get('Status', 'Inactive')
                is_active = (status == 'Active')
                body = record.get('Body', '')
                record_id = record.get('Id', '')
                api_version = record.get('ApiVersion', '')
                
                full_name = name
                display_name = f"{object_name} - {name}"
                
                component = MetadataComponent(
                    name=display_name,
                    full_name=full_name,
                    is_active=is_active,
                    component_type="ApexTrigger",
                    metadata={'status': status, 'body': body, 'ApiVersion': api_version},
                    record_id=record_id
                )
                components.append(component)
        
        except Exception as e:
            self._log(f"Error fetching triggers: {str(e)}")
        
        return components
    
    def get_components(self, component_type: str) -> List[MetadataComponent]:
        """Get components by type"""
        if component_type == "ValidationRule":
            return self.validation_rules
        elif component_type == "WorkflowRule":
            return self.workflow_rules
        elif component_type == "Flow":
            return self.flows
        elif component_type == "ApexTrigger":
            return self.triggers
        return []
    
    def deploy_changes(self, component_type: str, 
                      components_to_deploy: List[MetadataComponent],
                      run_tests: bool = False) -> Tuple[bool, str]:
        """
        Deploy changes to Salesforce using BATCH updates
        
        Args:
            component_type: Type of components being deployed
            components_to_deploy: List of modified components
            run_tests: Whether to run all tests (required for triggers in production)
        
        Returns:
            Tuple of (success, message/error)
        """
        if not components_to_deploy:
            return True, "No changes to deploy"
        
        try:
            self._log(f"=== Deploying {len(components_to_deploy)} {component_type}(s) ===")
            
            # Use batch deployment for better performance
            if component_type == "ApexTrigger":
                # Triggers need special handling with longer timeout
                success, message = self._batch_deploy_triggers(components_to_deploy, run_tests)
            else:
                # Other components can be batch updated
                success, message = self._batch_deploy_components(component_type, components_to_deploy)
            
            if success:
                # Commit changes to all successfully deployed components
                for component in components_to_deploy:
                    component.commit_changes()
                self._log(f"✅ All changes committed as new baseline")
            
            return success, message
        
        except Exception as e:
            error_msg = f"❌ Deployment failed: {str(e)}"
            self._log(error_msg)
            return False, error_msg
    
    def _batch_deploy_components(self, component_type: str, 
                                 components: List[MetadataComponent]) -> Tuple[bool, str]:
        """Deploy non-trigger components in batches"""
        self._log(f"📦 Starting batch deployment for {len(components)} component(s)")
        
        # Split into batches of 10 for better reliability
        batch_size = 10
        batches = [components[i:i + batch_size] for i in range(0, len(components), batch_size)]
        
        total_success = 0
        total_failed = 0
        failed_components = []
        
        for batch_num, batch in enumerate(batches, 1):
            self._log(f"📦 Processing batch {batch_num}/{len(batches)} ({len(batch)} components)")
            
            for component in batch:
                try:
                    result = self._update_component(component)
                    if result:
                        total_success += 1
                        self._log(f"  ✅ {component.name}")
                    else:
                        total_failed += 1
                        failed_components.append(component.name)
                        self._log(f"  ❌ {component.name}")
                except Exception as e:
                    total_failed += 1
                    failed_components.append(component.name)
                    self._log(f"  ❌ {component.name}: {str(e)}")
            
            # Small delay between batches to avoid rate limits
            if batch_num < len(batches):
                time.sleep(0.5)
        
        if total_failed == 0:
            message = f"✅ Successfully deployed {total_success} component(s)"
            self._log(message)
            return True, message
        else:
            message = f"⚠️ Deployed {total_success} component(s), {total_failed} failed"
            if failed_components:
                message += f"\n\nFailed components:\n" + "\n".join(f"• {name}" for name in failed_components[:10])
                if len(failed_components) > 10:
                    message += f"\n... and {len(failed_components) - 10} more"
            self._log(message)
            return False, message
    
    def _batch_deploy_triggers(self, triggers: List[MetadataComponent], 
                               run_tests: bool) -> Tuple[bool, str]:
        """Deploy triggers with extended timeout and test execution"""
        self._log(f"⚡ Starting trigger deployment (this may take several minutes)")
        
        if run_tests:
            self._log("🧪 Note: All Apex tests will run for trigger deployments in production")
        
        success_count = 0
        failed_count = 0
        failed_triggers = []
        
        # Process triggers one at a time with extended timeout
        for idx, trigger in enumerate(triggers, 1):
            self._log(f"⚡ Deploying trigger {idx}/{len(triggers)}: {trigger.name}")
            
            try:
                # Use extended timeout for triggers (5 minutes)
                result = self._update_trigger_with_retry(trigger, timeout=300)
                
                if result:
                    success_count += 1
                    self._log(f"  ✅ Successfully deployed: {trigger.name}")
                else:
                    failed_count += 1
                    failed_triggers.append(trigger.name)
                    self._log(f"  ❌ Failed to deploy: {trigger.name}")
            
            except Exception as e:
                failed_count += 1
                failed_triggers.append(trigger.name)
                self._log(f"  ❌ Error deploying {trigger.name}: {str(e)}")
            
            # Delay between triggers to avoid overwhelming the org
            if idx < len(triggers):
                time.sleep(2)
        
        if failed_count == 0:
            message = f"✅ Successfully deployed {success_count} trigger(s)"
            self._log(message)
            return True, message
        else:
            message = f"⚠️ Deployed {success_count} trigger(s), {failed_count} failed"
            if failed_triggers:
                message += f"\n\nFailed triggers:\n" + "\n".join(f"• {name}" for name in failed_triggers)
            self._log(message)
            return False, message
    
    def _update_component(self, component: MetadataComponent) -> bool:
        """Update a single component using Tooling API"""
        try:
            if component.component_type == "ValidationRule":
                return self._update_validation_rule(component)
            elif component.component_type == "WorkflowRule":
                return self._update_workflow_rule(component)
            elif component.component_type == "Flow":
                return self._update_flow(component)
            elif component.component_type == "ApexTrigger":
                return self._update_trigger(component)
            return False
        except Exception as e:
            self._log(f"Error updating component: {str(e)}")
            return False
    
    def _update_validation_rule(self, component: MetadataComponent) -> bool:
        """Update validation rule active status"""
        try:
            if not component.record_id:
                self._log(f"❌ No record ID for {component.name}")
                return False
            
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/ValidationRule/{component.record_id}"

            response = requests.get(url, headers=self.headers)
            existing_metadata = response.json()['Metadata']

            existing_metadata['active'] = component.is_active
            payload = {
                "Metadata": existing_metadata
            }
            
            response = requests.patch(url, headers=self.headers, json=payload, timeout=60)
            
            if response.status_code == 204:
                return True
            else:
                self._log(f"❌ HTTP {response.status_code}: {response.text}")
                return False
        
        except Exception as e:
            self._log(f"Error updating validation rule: {str(e)}")
            return False
    
    def _update_workflow_rule(self, component: MetadataComponent) -> bool:
        """Update workflow rule active status"""
        try:
            if not component.record_id:
                self._log(f"❌ No record ID for {component.name}")
                return False

            # Step 1: Get the existing workflow rule metadata
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/WorkflowRule/{component.record_id}"
            response = requests.get(url, headers=self.headers)
            existing_metadata = response.json()['Metadata']

            # Step 2: Modify only the active field
            existing_metadata['active'] = component.is_active

            # Step 3: Update with complete metadata
            payload = {
                "Metadata": existing_metadata
            }
            
            response = requests.patch(url, headers=self.headers, json=payload, timeout=60)
            
            if response.status_code == 204:
                return True
            else:
                self._log(f"❌ HTTP {response.status_code}: {response.text}")
                return False
        
        except Exception as e:
            self._log(f"Error updating workflow rule: {str(e)}")
            return False
    
    def _update_flow(self, component: MetadataComponent) -> bool:
        """Update flow status"""
        try:
            if not component.record_id:
                self._log(f"❌ No record ID for {component.name}")
                return False

            # Step 1: Get the Flow record to find its DefinitionId
            # flow_url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/Flow/{component.record_id}"
            # flow_response = requests.get(flow_url, headers=self.headers, timeout=60)
            # flow_data = flow_response.json()

            definition_id = component.metadata.get('definitionId')

            # Step 2: Get the existing FlowDefinition metadata
            definition_url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/FlowDefinition/{definition_id}"
            definition_response = requests.get(definition_url, headers=self.headers, timeout=60)
            existing_metadata = definition_response.json().get('Metadata', {})

            # Step 3: Update the metadata with ActiveVersion
            if component.is_active:
                # existing_metadata['activeVersionNumber'] = flow_data['VersionNumber']
                existing_metadata['activeVersionNumber'] = component.metadata.get('versionNumber')
            else:
                existing_metadata['activeVersionNumber'] = 0  # 0 means no active version

            payload = {
                "Metadata": existing_metadata
            }

            response = requests.patch(definition_url, headers=self.headers, json=payload, timeout=60)
            
            if response.status_code == 204:
                return True
            else:
                self._log(f"❌ HTTP {response.status_code}: {response.text}")
                return False
        
        except Exception as e:
            self._log(f"Error updating flow: {str(e)}")
            return False
    
    def _update_trigger(self, component: MetadataComponent) -> bool:
        """Update trigger status with standard timeout"""
        return self._update_trigger_with_retry(component, timeout=60)

    def _update_trigger_with_retry(self, component: MetadataComponent,
                                   timeout: int = 300, max_retries: int = 3) -> bool:
        """Update trigger status using MetadataContainer deployment"""
        try:
            if not component.record_id:
                self._log(f"❌ No record ID for {component.name}")
                return False

            # Extract trigger data from component metadata
            trigger_body = component.metadata.get('body')
            api_version = component.metadata.get('ApiVersion')

            if not trigger_body or not api_version:
                self._log(f"❌ Missing trigger body or API version for {component.name}")
                return False

            # Use TriggerDeployer to handle the deployment
            deployer = TriggerDeployer(
                base_url=self.base_url,
                api_version=self.api_version,
                headers=self.headers,
                logger=self._log
            )

            # Retry logic for transient failures
            for attempt in range(max_retries):
                success, message = deployer.deploy_trigger(
                    trigger_id=component.record_id,
                    trigger_body=trigger_body,
                    api_version=api_version,
                    is_active=component.is_active,
                    timeout=timeout
                )

                if success:
                    return True

                # Check if error is retryable (network/timeout issues)
                if "timeout" in message.lower() or "network" in message.lower():
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        self._log(f"⚠️ {message}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        continue

                # Non-retryable error (compilation, validation, etc.)
                self._log(f"❌ {message}")
                return False

            # All retries exhausted
            self._log(f"❌ Failed after {max_retries} attempts")
            return False

        except Exception as e:
            self._log(f"Error updating trigger: {str(e)}")
            return False
    
    def _tooling_query(self, soql: str) -> dict:
        """Execute Tooling API query"""
        try:
            import urllib.parse
            encoded_query = urllib.parse.quote(soql)
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/query/?q={encoded_query}"
            response = requests.get(url, headers=self.headers, timeout=60)
            
            if response.status_code == 200:
                return response.json()
            else:
                self._log(f"Tooling API error: {response.status_code} - {response.text}")
                return {'records': []}
        
        except Exception as e:
            self._log(f"Tooling API exception: {str(e)}")
            return {'records': []}
    
    def get_modified_count(self, component_type: str) -> int:
        """Get count of modified components"""
        components = self.get_components(component_type)
        return sum(1 for c in components if c.modified)
    
    def rollback_all(self, component_type: str):
        """Rollback all components to original state"""
        components = self.get_components(component_type)
        rollback_count = 0
        
        for component in components:
            if component.modified:
                component.rollback()
                rollback_count += 1
        
        if rollback_count > 0:
            self._log(f"✅ Rolled back {rollback_count} {component_type}(s) to original state")
        else:
            self._log(f"ℹ️ No modified {component_type}(s) to rollback")
    
    def _log(self, message: str):
        """Log status message"""
        if self.status_callback:
            self.status_callback(message, verbose=True)