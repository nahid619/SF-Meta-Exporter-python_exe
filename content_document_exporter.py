"""
ContentDocument export functionality - exports metadata and downloads files
"""
import os
import re
import csv
import requests
from typing import List, Dict, Tuple, Optional
from salesforce_client import SalesforceClient


class ContentDocumentExporter:
    """Handles ContentDocument metadata export and file downloads from Salesforce"""

    def __init__(self, sf_client: SalesforceClient):
        """Initialize with Salesforce client"""
        self.sf_client = sf_client
        self.sf = sf_client.sf
        self.base_url = sf_client.base_url
        self.headers = sf_client.headers

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def export_content_documents(
        self,
        output_path: str,
        filters: Optional[Dict] = None,
    ) -> Tuple[str, Dict]:
        """
        Export ContentDocument metadata to CSV and download file versions.

        Args:
            output_path: Path for the CSV file.
            filters:     Optional dict produced by the filter modal in gui.py.
                         Supported keys (all optional):
                           created_from      – YYYY-MM-DD  (inclusive lower bound on ContentDocument)
                           created_to        – YYYY-MM-DD  (inclusive upper bound on ContentDocument)
                           modified_from     – YYYY-MM-DD
                           modified_to       – YYYY-MM-DD
                           file_type         – partial string  (LIKE '%…%')
                           file_extension    – partial string  (LIKE '%…%')
                           title             – partial string  (LIKE '%…%')
                           is_archived       – 'True' | 'False'
                           is_latest_version – 'True' | 'False'  ← ContentVersion level filter

        Returns:
            Tuple of (csv_path, statistics_dict)
        """
        self._log_status("=== Starting ContentDocument Export ===")

        if filters:
            self._log_status(f"Active filters: {filters}")

        stats = {
            'total_documents': 0,
            'total_versions': 0,
            'successful_downloads': 0,
            'failed_downloads': 0,
            'total_size_bytes': 0,
            'failed_files': [],
        }

        # Create Documents folder in same directory as CSV
        csv_dir = os.path.dirname(output_path)
        documents_folder = os.path.join(csv_dir, "Documents")

        if not os.path.exists(documents_folder):
            os.makedirs(documents_folder)
            self._log_status(f"Created folder: {documents_folder}")

        # Query ContentDocuments (with optional ContentDocument-level filters)
        self._log_status("Querying ContentDocument records...")
        content_documents = self._query_content_documents(filters)
        stats['total_documents'] = len(content_documents)

        self._log_status(f"Found {len(content_documents)} ContentDocument records")

        if len(content_documents) == 0:
            self._log_status("No ContentDocument records found in org")
            self._create_csv_file([], output_path)
            return output_path, stats

        # Extract ContentVersion-level filter once, before the loop
        latest_only = (filters or {}).get("is_latest_version") == "True"
        if latest_only:
            self._log_status("Version filter: downloading latest version only")

        all_version_data = []

        for doc_index, doc in enumerate(content_documents, 1):
            doc_id = doc['Id']
            title = doc['Title']
            file_extension = doc.get('FileExtension', '')

            self._log_status(f"\n[{doc_index}/{len(content_documents)}] Processing: {title}")

            # Pass latest_only down — adds AND IsLatest = true to the query when set
            versions = self._query_all_versions(doc_id, latest_only=latest_only)

            if not versions:
                self._log_status(f"  ⚠️ No versions found for {title}")
                continue

            stats['total_versions'] += len(versions)
            total_versions_count = len(versions)

            self._log_status(f"  Found {total_versions_count} version(s)")

            for version_index, version in enumerate(versions, 1):
                version_id = version['Id']
                version_number = version['VersionNumber']
                is_latest = version['IsLatest']
                content_size = version.get('ContentSize', 0)

                self._log_status(
                    f"  [{version_index}/{total_versions_count}] "
                    f"Downloading version {version_number}..."
                )

                try:
                    file_path = self._download_file(
                        document_id=doc_id,
                        title=title,
                        file_extension=file_extension,
                        version_id=version_id,
                        version_number=version_number,
                        destination_folder=documents_folder,
                    )

                    downloaded_filename = os.path.basename(file_path)
                    path_on_client = f"Documents/{downloaded_filename}"

                    stats['successful_downloads'] += 1
                    stats['total_size_bytes'] += content_size

                    self._log_status(f"    ✅ Downloaded: {downloaded_filename}")

                    all_version_data.append({
                        'document': doc,
                        'version': version,
                        'downloaded_filename': downloaded_filename,
                        'path_on_client': path_on_client,
                        'version_number': version_number,
                        'is_latest': is_latest,
                        'total_versions': total_versions_count,
                    })

                except Exception as e:
                    error_msg = str(e)
                    self._log_status(f"    ❌ ERROR: {error_msg}")
                    stats['failed_downloads'] += 1

                    if file_extension:
                        filename = f"{title}_{doc_id}_v{version_number}.{file_extension}"
                    else:
                        filename = f"{title}_{doc_id}_v{version_number}"

                    stats['failed_files'].append({
                        'filename': filename,
                        'id': doc_id,
                        'version': version_number,
                        'reason': error_msg,
                    })

        self._log_status("\n=== Creating CSV File ===")
        final_output_path = self._create_csv_file(all_version_data, output_path)
        
        # Write failed records to a separate CSV alongside the main file
        stats['failed_csv_path'] = ''
        if stats['failed_files']:
            failed_csv_path = self._create_failed_csv_file(
                stats['failed_files'], output_path
            )
            stats['failed_csv_path'] = failed_csv_path

        return final_output_path, stats

    # ──────────────────────────────────────────────────────────────────────────
    # Filter / SOQL helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_where_clause(self, filters: Optional[Dict]) -> str:
        """
        Convert the filter dict from the GUI modal into a SOQL WHERE clause
        for the ContentDocument object.

        Note: is_latest_version is a ContentVersion-level filter and is NOT
        included here — it is handled separately in _query_all_versions().

        Returns an empty string when no applicable filters are active.
        """
        if not filters:
            return ""

        clauses: List[str] = []

        # ── Created Date ──────────────────────────────────────────────────────
        if filters.get("created_from"):
            dt = self._to_sf_datetime(filters["created_from"], start_of_day=True)
            if dt:
                clauses.append(f"CreatedDate >= {dt}")

        if filters.get("created_to"):
            dt = self._to_sf_datetime(filters["created_to"], start_of_day=False)
            if dt:
                clauses.append(f"CreatedDate <= {dt}")

        # ── Last Modified Date ────────────────────────────────────────────────
        if filters.get("modified_from"):
            dt = self._to_sf_datetime(filters["modified_from"], start_of_day=True)
            if dt:
                clauses.append(f"LastModifiedDate >= {dt}")

        if filters.get("modified_to"):
            dt = self._to_sf_datetime(filters["modified_to"], start_of_day=False)
            if dt:
                clauses.append(f"LastModifiedDate <= {dt}")

        # ── Text LIKE filters ─────────────────────────────────────────────────
        if filters.get("file_type"):
            safe = self._escape_soql_string(filters["file_type"])
            clauses.append(f"FileType LIKE '%{safe}%'")

        if filters.get("file_extension"):
            safe = self._escape_soql_string(filters["file_extension"])
            clauses.append(f"FileExtension LIKE '%{safe}%'")

        if filters.get("title"):
            safe = self._escape_soql_string(filters["title"])
            clauses.append(f"Title LIKE '%{safe}%'")

        # ── IsArchived boolean ────────────────────────────────────────────────
        is_archived = filters.get("is_archived", "")
        if is_archived in ("True", "False"):
            clauses.append(f"IsArchived = {is_archived.lower()}")

        if not clauses:
            return ""

        return "WHERE " + " AND ".join(clauses)

    @staticmethod
    def _to_sf_datetime(date_str: str, start_of_day: bool) -> str:
        """
        Convert 'YYYY-MM-DD' → Salesforce datetime literal.

        start_of_day=True  → 'YYYY-MM-DDT00:00:00Z'
        start_of_day=False → 'YYYY-MM-DDT23:59:59Z'
        """
        if not date_str:
            return ""
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
            return ""
        time_part = "T00:00:00Z" if start_of_day else "T23:59:59Z"
        return f"{date_str}{time_part}"

    @staticmethod
    def _escape_soql_string(value: str) -> str:
        """Escape single quotes to prevent SOQL injection in LIKE clauses."""
        return value.replace("'", "\\'")

    # ──────────────────────────────────────────────────────────────────────────
    # Salesforce query methods
    # ──────────────────────────────────────────────────────────────────────────

    def _query_content_documents(self, filters: Optional[Dict] = None) -> List[Dict]:
        """Query ContentDocument records, optionally filtered."""
        try:
            where_clause = self._build_where_clause(filters)

            query = f"""
                SELECT Id, Title, FileExtension, FileType, ContentSize,
                       CreatedDate, CreatedById, LastModifiedDate, LastModifiedById,
                       OwnerId, ParentId, IsArchived, IsDeleted,
                       ArchivedDate, ArchivedById, Description,
                       PublishStatus, LatestPublishedVersionId
                FROM ContentDocument
                {where_clause}
                ORDER BY CreatedDate DESC
            """

            self._log_status(f"SOQL: {' '.join(query.split())}")

            result = self.sf.query_all(query)
            return result['records']

        except Exception as e:
            self._log_status(f"ERROR querying ContentDocument: {str(e)}")
            raise

    def _query_all_versions(
        self,
        document_id: str,
        latest_only: bool = False,
    ) -> List[Dict]:
        """
        Query ContentVersion records for a specific ContentDocument.

        Args:
            document_id: ContentDocument Id.
            latest_only: When True, adds AND IsLatest = true so only the
                         single latest version is returned. Defaults to False
                         (all versions are returned).

        Returns:
            List of ContentVersion records.
        """
        try:
            version_filter = " AND IsLatest = true" if latest_only else ""

            query = f"""
                SELECT Id, ContentDocumentId, VersionNumber, IsLatest,
                    ContentSize, CreatedDate, LastModifiedDate
                FROM ContentVersion
                WHERE ContentDocumentId = '{document_id}'{version_filter}
                ORDER BY VersionNumber ASC
            """

            result = self.sf.query(query)
            return result['records']

        except Exception as e:
            self._log_status(f"    ⚠️ Error querying versions for {document_id}: {str(e)}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # File download
    # ──────────────────────────────────────────────────────────────────────────

    def _download_file(
        self,
        document_id: str,
        title: str,
        file_extension: str,
        version_id: str,
        version_number: int,
        destination_folder: str,
    ) -> str:
        """
        Download a single file version from Salesforce.

        Args:
            document_id:        ContentDocument Id
            title:              Document title
            file_extension:     File extension
            version_id:         ContentVersion Id
            version_number:     Version number (1, 2, 3, …)
            destination_folder: Folder to save the file

        Returns:
            Full path of downloaded file
        """
        try:
            if file_extension:
                filename = f"{title}_{document_id}_v{version_number}.{file_extension}"
            else:
                filename = f"{title}_{document_id}_v{version_number}"

            safe_filename = self._sanitize_filename(filename)

            download_url = (
                f"{self.base_url}/services/data/v{self.sf_client.api_version}"
                f"/sobjects/ContentVersion/{version_id}/VersionData"
            )

            response = requests.get(download_url, headers=self.headers, timeout=120)
            response.raise_for_status()

            file_path = os.path.join(destination_folder, safe_filename)
            with open(file_path, 'wb') as f:
                f.write(response.content)

            return file_path

        except Exception as e:
            raise Exception(f"Failed to download version {version_number}: {str(e)}")

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Remove characters that are invalid in filenames on Windows/macOS/Linux."""
        for char in '<>:"/\\|?*':
            filename = filename.replace(char, '_')
        return filename

    # ──────────────────────────────────────────────────────────────────────────
    # CSV output
    # ──────────────────────────────────────────────────────────────────────────

    def _create_csv_file(self, all_version_data: List[Dict], output_path: str) -> str:
        """
        Create CSV file with ContentVersion metadata (DataLoader-ready).

        Args:
            all_version_data: List of version data dictionaries
            output_path:      Path for the CSV file

        Returns:
            Path to created CSV file
        """
        headers = [
            # ── Required for DataLoader import ──────────────────────────────
            'Title',
            'PathOnClient',

            # ── Optional for DataLoader (migration support) ──────────────────
            'ContentDocumentId',
            'FirstPublishLocationId',
            'Description',
            'Origin',

            # ── Version metadata (reference) ─────────────────────────────────
            'VersionNumber',
            'IsLatestVersion',
            'Total_Versions_Available',

            # ── File metadata (reference) ─────────────────────────────────────
            'FileExtension',
            'FileType',
            'ContentSize (Bytes)',

            # ── Salesforce metadata (reference) ──────────────────────────────
            'CreatedDate',
            'LastModifiedDate',
            'OwnerId',
        ]

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)

            for version_data in all_version_data:
                doc = version_data['document']
                version = version_data['version']

                row = [
                    # ── Required for DataLoader ──────────────────────────────
                    doc.get('Title', ''),
                    version_data['path_on_client'],

                    # ── Optional for DataLoader ──────────────────────────────
                    doc.get('Id', ''),
                    '',                                              # FirstPublishLocationId (user fills)
                    doc.get('Description', ''),
                    'H',                                             # Origin: 'H' = uploaded

                    # ── Version metadata ─────────────────────────────────────
                    version_data['version_number'],
                    'TRUE' if version_data['is_latest'] else 'FALSE',
                    version_data['total_versions'],

                    # ── File metadata ─────────────────────────────────────────
                    doc.get('FileExtension', ''),
                    doc.get('FileType', ''),
                    version.get('ContentSize', 0),

                    # ── Salesforce metadata ───────────────────────────────────
                    version.get('CreatedDate', ''),
                    version.get('LastModifiedDate', ''),
                    doc.get('OwnerId', ''),
                ]

                writer.writerow(row)

        self._log_status(f"✅ CSV file created: {output_path}")
        self._log_status(f"✅ Total rows exported: {len(all_version_data)}")

        return output_path
    
    
    def _create_failed_csv_file(
        self, failed_files: List[Dict], main_output_path: str
    ) -> str:
        """
        Write a CSV listing every file that failed to download.

        The file is placed in the same directory as the main CSV and named
        by appending '_failed' to the base name, e.g.:
            export_20241201_120000.csv  →  export_20241201_120000_failed.csv

        Args:
            failed_files:     List of failure dicts from stats['failed_files'].
                              Each dict has keys: filename, id, version, reason.
            main_output_path: Full path of the successfully-written main CSV.

        Returns:
            Full path of the created failed-records CSV.
        """
        base, ext = os.path.splitext(main_output_path)
        failed_path = f"{base}_failed{ext}"

        headers = [
            'Filename',
            'ContentDocumentId',
            'VersionNumber',
            'Error Reason',
        ]

        with open(failed_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)

            for record in failed_files:
                writer.writerow([
                    record.get('filename', ''),
                    record.get('id', ''),
                    record.get('version', ''),
                    record.get('reason', ''),
                ])

        self._log_status(f"⚠️ Failed records CSV: {failed_path}")
        self._log_status(f"⚠️ Total failed records: {len(failed_files)}")

        return failed_path

    # ──────────────────────────────────────────────────────────────────────────
    # Logging
    # ──────────────────────────────────────────────────────────────────────────

    def _log_status(self, message: str):
        """Log status message via the Salesforce client's status callback."""
        if self.sf_client.status_callback:
            self.sf_client.status_callback(message, verbose=True)
