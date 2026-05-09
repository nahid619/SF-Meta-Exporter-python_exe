"""
Salesforce connection and authentication handler
"""
from typing import List, Optional, Callable
from simple_salesforce import Salesforce
from simple_salesforce.exceptions import SalesforceExpiredSession


class SalesforceClient:
    """Handles Salesforce authentication and connection via OAuth session."""

    def _fetch_all_org_objects(self):
        """
        Fetches all SObjects (Standard and Custom) from the org.
        """
        self._log_status("Fetching all available SObjects from the organization...")

        try:
            if not self.sf:
                raise Exception("Salesforce connection not initialized")

            if not self.session_id:
                raise Exception("No valid Salesforce session")

            self._log_status("📞 Calling Salesforce describe() API...")

            try:
                response = self.sf.describe()
            except SalesforceExpiredSession as e:
                error_str = str(e).lower()

                if 'password has expired' in error_str or 'expired_password' in error_str:
                    self._log_status("❌ PASSWORD EXPIRED")
                    raise Exception(
                        "🔐 Your Salesforce password has expired!\n\n"
                        "To fix this:\n"
                        "1. Go to your Salesforce org\n"
                        "2. Reset your password (Setup → Change Password)\n"
                        "3. Get new security token (Setup → My Personal Info → Reset Security Token)\n"
                        "4. Use the new password + token to log in again\n\n"
                        f"Technical error: {str(e)}"
                    )
                else:
                    raise Exception(f"Session expired: {str(e)}")

            if not response or not isinstance(response, dict):
                raise Exception("Invalid response from Salesforce describe()")

            sobjects = response.get('sobjects', [])

            if not sobjects:
                self._log_status("⚠️ No SObjects returned from describe()")
                self.all_org_objects = []
                return

            self._log_status(f"📊 Received {len(sobjects)} total objects from Salesforce")

            queryable_objects = [
                obj['name'] for obj in sobjects
                if obj.get('queryable', False) and not obj.get('deprecatedAndHidden', False)
            ]

            self.all_org_objects = sorted(queryable_objects)

            if not self.all_org_objects:
                self._log_status("⚠️ No queryable objects found after filtering")
                self._log_status("⚠️ This usually means insufficient permissions")

                queryable_count = sum(1 for obj in sobjects if obj.get('queryable', False))
                deprecated_count = sum(1 for obj in sobjects if obj.get('deprecatedAndHidden', False))

                self._log_status("📊 Breakdown:")
                self._log_status(f"  - Total objects: {len(sobjects)}")
                self._log_status(f"  - Queryable: {queryable_count}")
                self._log_status(f"  - Deprecated: {deprecated_count}")
                self._log_status(f"  - Final (queryable + not deprecated): {len(self.all_org_objects)}")
            else:
                self._log_status(f"✅ Found {len(self.all_org_objects)} queryable objects")

                sample = ', '.join(self.all_org_objects[:5])
                if len(self.all_org_objects) > 5:
                    sample += f", ... (+{len(self.all_org_objects) - 5} more)"
                self._log_status(f"📦 Sample objects: {sample}")

        except Exception as e:
            error_msg = str(e)
            self._log_status(f"❌ Failed to fetch SObjects: {error_msg}")

            self.all_org_objects = []

            import traceback
            traceback_str = traceback.format_exc()
            print(f"❌ DETAILED ERROR in _fetch_all_org_objects:\n{traceback_str}")

            if 'password has expired' in error_msg.lower() or 'expired_password' in error_msg.lower():
                raise
            else:
                self._log_status("🔍 Technical details logged to console")

    @staticmethod
    def _fetch_org_api_version(instance_url: str, session_id: str) -> str:
        """
        Fetches the latest API version supported by this org.
        Calls GET {instance_url}/services/data/ — no auth required for this endpoint.
        Falls back to '64.0' if the request fails for any reason.
        """
        import requests
        fallback = '64.0'
        try:
            resp = requests.get(
                f"{instance_url.rstrip('/')}/services/data/",
                headers={"Authorization": f"Bearer {session_id}"},
                timeout=10,
            )
            if resp.status_code == 200:
                versions = resp.json()
                if versions and isinstance(versions, list):
                    latest = versions[-1].get("version", fallback)
                    return latest
        except Exception:
            pass
        return fallback

    @classmethod
    def from_session(cls, session_id: str, instance_url: str,
                     status_callback=None):
        """
        Create a SalesforceClient from an existing OAuth session
        (access_token + instance_url).

        This is the only supported login path — username/password
        is not used by this application.
        """
        obj = cls.__new__(cls)
        obj.status_callback = status_callback
        obj.all_org_objects = []
        obj.sf              = None
        obj.base_url        = None
        obj.session_id      = None
        obj.api_version     = cls._fetch_org_api_version(instance_url, session_id)
        obj.headers         = None

        obj._log_status("🔐 Connecting via OAuth session...")

        try:
            obj.sf = Salesforce(
                instance_url=instance_url,
                session_id=session_id,
            )

            obj.session_id = session_id
            obj.base_url   = instance_url
            obj.headers    = {
                "Authorization": f"Bearer {session_id}",
                "Content-Type":  "application/json",
            }

            obj._log_status(f"✅ Connected to: {instance_url}")
            obj._log_status(f"📡 API Version: v{obj.api_version}")
            obj._log_status("🔑 OAuth session established successfully")

            obj._fetch_all_org_objects()

        except Exception as e:
            obj.sf = None
            obj.all_org_objects = []
            obj._log_status(f"❌ OAuth connection failed: {str(e)}")
            raise

        return obj

    def get_all_objects(self) -> List[str]:
        """Accessor for the fetched object list."""
        return self.all_org_objects

    def _log_status(self, message: str):
        """Internal helper to send log messages back to the GUI."""
        if self.status_callback:
            self.status_callback(message, verbose=True)
