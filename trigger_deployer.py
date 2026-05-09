import time
import requests
from typing import Optional, Tuple


class TriggerDeployer:
    """Handles Salesforce Apex Trigger deployment via Tooling API MetadataContainer"""

    def __init__(self, base_url: str, api_version: str, headers: dict, logger=None):
        """
        Initialize the TriggerDeployer

        Args:
            base_url: Salesforce instance URL
            api_version: API version (e.g., "62.0")
            headers: Request headers with authorization
            logger: Optional logger function for logging messages
        """
        self.base_url = base_url
        self.api_version = api_version
        self.headers = headers
        self._log = logger if logger else print

    def deploy_trigger(self, trigger_id: str, trigger_body: str,
                       api_version: str, is_active: bool,
                       timeout: int = 300) -> Tuple[bool, str]:
        """
        Deploy a trigger with the specified active status

        Args:
            trigger_id: Salesforce ID of the trigger
            trigger_body: Current trigger code body
            api_version: API version of the trigger (e.g., "62.0")
            is_active: True to activate, False to deactivate
            timeout: Request timeout in seconds

        Returns:
            Tuple of (success: bool, message: str)
        """
        container_id = None

        try:
            # Step 1: Create MetadataContainer
            container_id = self._create_container(timeout)
            if not container_id:
                return False, "Failed to create metadata container"

            # Step 2: Create ApexTriggerMember
            member_created = self._create_trigger_member(
                container_id, trigger_id, trigger_body,
                api_version, is_active, timeout
            )
            if not member_created:
                self._cleanup_container(container_id)
                return False, "Failed to create trigger member"

            # Step 3: Deploy the container
            request_id = self._deploy_container(container_id, timeout)
            if not request_id:
                self._cleanup_container(container_id)
                return False, "Failed to initiate deployment"

            # Step 4: Monitor deployment
            success, message = self._monitor_deployment(request_id, timeout)

            # Cleanup container regardless of outcome
            self._cleanup_container(container_id)

            return success, message

        except Exception as e:
            if container_id:
                self._cleanup_container(container_id)
            return False, f"Deployment error: {str(e)}"

    def _create_container(self, timeout: int) -> Optional[str]:
        """Create a MetadataContainer"""
        try:
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/MetadataContainer"
            payload = {
                "Name": f"TriggerContainer_{int(time.time())}"
            }

            response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)

            if response.status_code == 201:
                return response.json()['id']
            else:
                self._log(f"❌ Failed to create container: {response.text}")
                return None

        except Exception as e:
            self._log(f"❌ Error creating container: {str(e)}")
            return None

    def _create_trigger_member(self, container_id: str, trigger_id: str,
                               trigger_body: str, api_version: float,
                               is_active: bool, timeout: int) -> bool:
        """Create an ApexTriggerMember in the container"""
        try:
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/ApexTriggerMember"
            status = "Active" if is_active else "Inactive"

            payload = {
                "MetadataContainerId": container_id,
                "ContentEntityId": trigger_id,
                "Body": trigger_body,
                "Metadata": {
                    "status": status,
                    "apiVersion": api_version
                }
            }

            response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)

            if response.status_code == 201:
                return True
            else:
                self._log(f"❌ Failed to create trigger member: {response.text}")
                return False

        except Exception as e:
            self._log(f"❌ Error creating trigger member: {str(e)}")
            return False

    def _deploy_container(self, container_id: str, timeout: int) -> Optional[str]:
        """Deploy the MetadataContainer"""
        try:
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/ContainerAsyncRequest"
            payload = {
                "MetadataContainerId": container_id,
                "IsCheckOnly": False
            }

            response = requests.post(url, headers=self.headers, json=payload, timeout=timeout)

            if response.status_code == 201:
                return response.json()['id']
            else:
                self._log(f"❌ Failed to deploy container: {response.text}")
                return None

        except Exception as e:
            self._log(f"❌ Error deploying container: {str(e)}")
            return None

    def _monitor_deployment(self, request_id: str, timeout: int) -> Tuple[bool, str]:
        """Monitor the deployment status"""
        try:
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/ContainerAsyncRequest/{request_id}"

            max_wait = timeout
            elapsed = 0
            poll_interval = 2

            while elapsed < max_wait:
                response = requests.get(url, headers=self.headers, timeout=30)

                if response.status_code != 200:
                    return False, f"Failed to check status: {response.text}"

                data = response.json()
                state = data.get('State')

                if state == 'Completed':
                    return True, "Deployment completed successfully"
                elif state == 'Failed':
                    error_msg = data.get('ErrorMsg', 'Unknown error')
                    return False, f"Deployment failed: {error_msg}"
                elif state == 'Error':
                    compile_errors = data.get('DeployDetails', {}).get('componentFailures', [])
                    error_details = "\n".join([err.get('problem', '') for err in compile_errors])
                    return False, f"Compilation error: {error_details}"
                elif state in ['Queued', 'Invalidated']:
                    time.sleep(poll_interval)
                    elapsed += poll_interval
                else:
                    # Unknown state, keep waiting
                    time.sleep(poll_interval)
                    elapsed += poll_interval

            return False, f"Deployment timed out after {timeout}s"

        except Exception as e:
            return False, f"Error monitoring deployment: {str(e)}"

    def _cleanup_container(self, container_id: str) -> None:
        """Delete the MetadataContainer"""
        try:
            url = f"{self.base_url}/services/data/v{self.api_version}/tooling/sobjects/MetadataContainer/{container_id}"
            requests.delete(url, headers=self.headers, timeout=30)
        except Exception as e:
            self._log(f"⚠️ Failed to cleanup container: {str(e)}")