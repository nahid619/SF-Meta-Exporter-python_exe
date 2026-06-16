"""
ContentDocument export functionality - exports metadata and downloads files
"""
import os
import re
import csv
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple, Optional, Set
from salesforce_client import SalesforceClient


class ContentDocumentExporter:
    """Handles ContentDocument metadata export and file downloads from Salesforce"""

    def __init__(self, sf_client: SalesforceClient):
        """Initialize with Salesforce client"""
        self.sf_client = sf_client
        self.sf = sf_client.sf
        self.base_url = sf_client.base_url
        self.headers = sf_client.headers

    # Max ContentDocument Ids per "Id IN (...)" SOQL clause. Keeps the query
    # string comfortably under Salesforce's 20,000-character SOQL limit, even
    # combined with the other field filters (date ranges, LIKE clauses, etc.).
    _ID_CHUNK_SIZE  = 400   # max Ids per SOQL IN clause
    _DEFAULT_WORKERS = 5    # concurrent download threads

    # Shared CSV column order used by both incremental writer and _create_csv_file
    _CSV_HEADERS = [
        'Title', 'PathOnClient',
        'ContentDocumentId', 'FirstPublishLocationId', 'Description', 'Origin',
        'VersionNumber', 'IsLatestVersion', 'Total_Versions_Available',
        'FileExtension', 'FileType', 'ContentSize (Bytes)',
        'CreatedDate', 'LastModifiedDate', 'OwnerId',
    ]

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def export_content_documents(
        self,
        output_path: str,
        filters: Optional[Dict] = None,
        object_types: Optional[List[str]] = None,
        max_workers: int = None,
    ) -> Tuple[str, Dict]:
        """
        Export ContentDocument metadata to CSV and download all file versions.

        Args:
            output_path:  Path for the CSV file.
            filters:      Optional dict produced by the filter modal in gui.py.
                          Supported keys (all optional):
                            created_from   – YYYY-MM-DD  (inclusive lower bound)
                            created_to     – YYYY-MM-DD  (inclusive upper bound)
                            modified_from  – YYYY-MM-DD
                            modified_to    – YYYY-MM-DD
                            file_type      – partial string  (LIKE '%…%')
                            file_extension – partial string  (LIKE '%…%')
                            title          – partial string  (LIKE '%…%')
                            is_archived    – 'True' | 'False'  (omit key or set '' for "Any")
            object_types: Optional list of object API names (e.g. ['Account', 'Case']).
                          When provided, only files linked to a record of one of
                          these object types are downloaded — mirrors the
                          "filter by parent object" behaviour already used for
                          legacy Attachments, but implemented via
                          ContentDocumentLink since ContentDocument has no
                          direct Parent/Type field.

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
            'object_types_filtered': [],
        }

        # Create Documents folder in same directory as CSV
        csv_dir = os.path.dirname(output_path)
        documents_folder = os.path.join(csv_dir, "Documents")

        if not os.path.exists(documents_folder):
            os.makedirs(documents_folder)
            self._log_status(f"Created folder: {documents_folder}")

        # ── Resolve object-type restriction ──────────────────────────────────
        # ContentDocument has no Parent/Type field like legacy Attachment does,
        # so "filter by object" has to go through the ContentDocumentLink
        # bridge object instead (see _query_linked_document_ids).
        restrict_to_ids: Optional[Set[str]] = None
        if object_types:
            self._log_status(f"Filtering by linked object type(s): {', '.join(object_types)}")
            restrict_to_ids = set()
            for obj_type in object_types:
                linked_ids = self._query_linked_document_ids(obj_type)
                self._log_status(f"  {obj_type}: {len(linked_ids)} linked document(s)")
                restrict_to_ids |= linked_ids
            stats['object_types_filtered'] = object_types

        # Query ContentDocuments (with optional field filters + object restriction)
        self._log_status("Querying ContentDocument records...")
        content_documents = self._query_content_documents(filters, restrict_to_ids)
        stats['total_documents'] = len(content_documents)

        self._log_status(f"Found {len(content_documents)} ContentDocument records")

        if len(content_documents) == 0:
            if restrict_to_ids is not None and len(restrict_to_ids) == 0:
                self._log_status("No documents are linked to the selected object type(s)")
            else:
                self._log_status("No ContentDocument records found in org")
            self._create_csv_file([], output_path)
            return output_path, stats

        # ── Phase 2: batch-query all versions in one go ──────────────────────
        # Old approach: 1 SOQL per document (10,000 docs = 10,000 round trips).
        # New approach: chunk all doc IDs → ~25 queries total.
        doc_ids = [doc['Id'] for doc in content_documents]
        n_batches = (len(doc_ids) + self._ID_CHUNK_SIZE - 1) // self._ID_CHUNK_SIZE
        self._log_status(
            f"\n=== Batch querying versions "
            f"({len(doc_ids)} docs → {n_batches} SOQL queries) ==="
        )
        versions_map = self._query_versions_batch(doc_ids, filters)

        # Build flat task list so the executor can pick any item next
        download_tasks: List[Tuple[Dict, Dict, int]] = []
        for doc in content_documents:
            versions = versions_map.get(doc['Id'], [])
            if not versions:
                self._log_status(f"  ⚠️ No versions found for {doc.get('Title', doc['Id'])}")
                continue
            stats['total_versions'] += len(versions)
            for version in versions:
                download_tasks.append((doc, version, len(versions)))

        total_tasks = len(download_tasks)
        workers = max_workers if max_workers is not None else self._DEFAULT_WORKERS
        self._log_status(
            f"\n=== Downloading {total_tasks} file version(s) "
            f"(concurrent workers = {workers}) ==="
        )

        # ── Phase 3: concurrent downloads + incremental CSV ───────────────────
        # The CSV is opened immediately so every completed download is persisted
        # to disk right away. If the run is interrupted partway through, the
        # partial CSV already contains all rows that finished successfully.
        io_lock = threading.Lock()   # guards both CSV writes and stats counters
        completed_count = 0

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(self._CSV_HEADERS)
            csvfile.flush()

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_task = {
                    executor.submit(
                        self._download_file,
                        doc['Id'],
                        doc['Title'],
                        doc.get('FileExtension', ''),
                        version['Id'],
                        version['VersionNumber'],
                        documents_folder,
                    ): (doc, version, total_v)
                    for doc, version, total_v in download_tasks
                }

                for future in as_completed(future_to_task):
                    doc, version, total_v = future_to_task[future]
                    completed_count += 1

                    try:
                        file_path   = future.result()
                        filename    = os.path.basename(file_path)
                        path_on_client = f"Documents/{filename}"
                        is_latest   = version['IsLatest']
                        content_size = version.get('ContentSize', 0)

                        row = self._build_csv_row(
                            doc=doc,
                            version=version,
                            path_on_client=path_on_client,
                            is_latest=is_latest,
                            total_versions=total_v,
                        )

                        with io_lock:
                            stats['successful_downloads'] += 1
                            stats['total_size_bytes']     += content_size
                            writer.writerow(row)
                            csvfile.flush()   # guarantee row hits disk now

                        self._log_status(
                            f"  [{completed_count}/{total_tasks}] ✅ {filename}"
                        )

                    except Exception as e:
                        ext      = doc.get('FileExtension', '')
                        ver_num  = version.get('VersionNumber', '?')
                        fallback = (
                            f"{doc.get('Title', 'unknown')}_{doc['Id']}_v{ver_num}"
                            + (f".{ext}" if ext else "")
                        )
                        self._log_status(
                            f"  [{completed_count}/{total_tasks}] ❌ FAILED: {fallback} — {e}"
                        )
                        with io_lock:
                            stats['failed_downloads'] += 1
                            stats['failed_files'].append({
                                'filename': fallback,
                                'id':       doc['Id'],
                                'version':  ver_num,
                                'reason':   str(e),
                            })

        self._log_status(f"\n✅ Incremental CSV saved: {output_path}")
        self._log_status(
            f"✅ {stats['successful_downloads']} downloaded, "
            f"{stats['failed_downloads']} failed, "
            f"out of {total_tasks} total"
        )
        return output_path, stats

    # ──────────────────────────────────────────────────────────────────────────
    # Filter / SOQL helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _build_where_clause(self, filters: Optional[Dict]) -> str:
        """
        Convert the filter dict from the GUI modal into a SOQL WHERE clause.

        Date values arrive as 'YYYY-MM-DD' strings and are converted to the
        Salesforce datetime literal format (YYYY-MM-DDThh:mm:ssZ).

        Returns an empty string when no filters are active.
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
        # Basic sanity check – must match YYYY-MM-DD
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

    def _query_linked_document_ids(self, object_type: str) -> Set[str]:
        """
        Return the ContentDocumentIds linked to any record of `object_type`.

        Salesforce Files don't carry a Parent/Type field the way legacy
        Attachments do — the link lives on ContentDocumentLink.LinkedEntityId,
        a polymorphic field that can't be filtered by LinkedEntity.Type
        directly. The standard workaround is a semi-join scoping
        LinkedEntityId to the target object's own Id space:

            SELECT ContentDocumentId FROM ContentDocumentLink
            WHERE LinkedEntityId IN (SELECT Id FROM {object_type})
        """
        try:
            query = (
                "SELECT ContentDocumentId "
                "FROM ContentDocumentLink "
                f"WHERE LinkedEntityId IN (SELECT Id FROM {object_type})"
            )
            self._log_status(f"SOQL: {' '.join(query.split())}")

            result = self.sf.query_all(query)
            return {r['ContentDocumentId'] for r in result['records']}

        except Exception as e:
            self._log_status(f"  ⚠️ Error querying ContentDocumentLink for {object_type}: {str(e)}")
            return set()

    def _query_content_documents(
        self,
        filters: Optional[Dict] = None,
        restrict_to_ids: Optional[Set[str]] = None,
    ) -> List[Dict]:
        """
        Query ContentDocument records, optionally filtered and/or restricted
        to a specific set of Ids (the linked-object filter resolves to this).
        """
        if restrict_to_ids is not None and len(restrict_to_ids) == 0:
            return []

        try:
            base_where = self._build_where_clause(filters)

            if not restrict_to_ids:
                query = self._build_content_document_query(base_where)
                self._log_status(f"SOQL: {' '.join(query.split())}")  # compact log
                result = self.sf.query_all(query)
                return result['records']

            # Batch the Id list so each "Id IN (...)" clause stays well under
            # Salesforce's SOQL length limit, then merge the batched results.
            all_records: List[Dict] = []
            for batch in self._chunk(sorted(restrict_to_ids), self._ID_CHUNK_SIZE):
                id_clause = "Id IN (" + ",".join(f"'{doc_id}'" for doc_id in batch) + ")"
                where_clause = self._combine_where(base_where, id_clause)
                query = self._build_content_document_query(where_clause)
                self._log_status(f"SOQL: {' '.join(query.split())}")  # compact log
                result = self.sf.query_all(query)
                all_records.extend(result['records'])

            return all_records

        except Exception as e:
            self._log_status(f"ERROR querying ContentDocument: {str(e)}")
            raise

    @staticmethod
    def _build_content_document_query(where_clause: str) -> str:
        """Build the ContentDocument SELECT statement for a given WHERE clause."""
        return f"""
            SELECT Id, Title, FileExtension, FileType, ContentSize,
                   CreatedDate, CreatedById, LastModifiedDate, LastModifiedById,
                   OwnerId, ParentId, IsArchived, IsDeleted,
                   ArchivedDate, ArchivedById, Description,
                   PublishStatus, LatestPublishedVersionId
            FROM ContentDocument
            {where_clause}
            ORDER BY CreatedDate DESC
        """

    @staticmethod
    def _combine_where(base_where: str, extra_condition: str) -> str:
        """Combine an existing 'WHERE ...' clause (or '') with one more bare condition."""
        if base_where:
            return f"{base_where} AND {extra_condition}"
        return f"WHERE {extra_condition}"

    @staticmethod
    def _chunk(items: List, size: int):
        """Yield successive `size`-length slices of `items`."""
        for i in range(0, len(items), size):
            yield items[i:i + size]

    def _query_versions_batch(
        self,
        document_ids: List[str],
        filters: Optional[Dict] = None,
    ) -> Dict[str, List[Dict]]:
        """
        Batch-query ContentVersion records for every document in one pass.

        Instead of one SOQL per document, all IDs are chunked into batches of
        _ID_CHUNK_SIZE and each batch fires a single query.  For 10,000 docs
        this drops ~10,000 round trips to ~25.

        Args:
            document_ids: ContentDocument Ids to look up.
            filters:      Optional filter dict — respects the 'is_latest' key.

        Returns:
            Dict mapping each ContentDocumentId to its list of version records,
            ordered by VersionNumber ASC.
        """
        is_latest_filter = (filters or {}).get("is_latest", "")
        is_latest_clause = ""
        if is_latest_filter == "True":
            is_latest_clause = " AND IsLatest = true"
        elif is_latest_filter == "False":
            is_latest_clause = " AND IsLatest = false"

        versions_map: Dict[str, List[Dict]] = {}
        batches = list(self._chunk(document_ids, self._ID_CHUNK_SIZE))

        for batch_num, batch in enumerate(batches, 1):
            id_list = ",".join(f"'{did}'" for did in batch)
            query = f"""
                SELECT Id, ContentDocumentId, VersionNumber, IsLatest,
                       ContentSize, CreatedDate, LastModifiedDate
                FROM   ContentVersion
                WHERE  ContentDocumentId IN ({id_list}){is_latest_clause}
                ORDER BY ContentDocumentId ASC, VersionNumber ASC
            """
            self._log_status(
                f"  Version batch {batch_num}/{len(batches)} "
                f"({len(batch)} documents)..."
            )
            try:
                result = self.sf.query_all(query)
                for record in result['records']:
                    doc_id = record['ContentDocumentId']
                    versions_map.setdefault(doc_id, []).append(record)
            except Exception as e:
                self._log_status(f"  ⚠️ Version batch {batch_num} error: {e}")

        return versions_map

    @staticmethod
    def _build_csv_row(
        doc: Dict,
        version: Dict,
        path_on_client: str,
        is_latest: bool,
        total_versions: int,
    ) -> List:
        """
        Build a single CSV data row from a document + version pair.

        Extracted so both the incremental writer in export_content_documents
        and the bulk writer in _create_csv_file share identical column logic.
        """
        return [
            doc.get('Title', ''),
            path_on_client,
            doc.get('Id', ''),
            '',                                          # FirstPublishLocationId (user fills in)
            doc.get('Description', ''),
            'H',                                         # Origin: 'H' = Content uploaded by user
            version.get('VersionNumber', ''),
            'TRUE' if is_latest else 'FALSE',
            total_versions,
            doc.get('FileExtension', ''),
            doc.get('FileType', ''),
            version.get('ContentSize', 0),
            version.get('CreatedDate', ''),
            version.get('LastModifiedDate', ''),
            doc.get('OwnerId', ''),
        ]

    def _query_all_versions(self, document_id: str) -> List[Dict]:
        """
        Query all versions for a specific ContentDocument.

        Args:
            document_id: ContentDocument Id

        Returns:
            List of ContentVersion records with version info
        """
        try:
            query = f"""
                SELECT Id, ContentDocumentId, VersionNumber, IsLatest,
                    ContentSize, CreatedDate, LastModifiedDate
                FROM ContentVersion
                WHERE ContentDocumentId = '{document_id}'
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

    # ──────────────────────────────────────────────────────────────────────────
    # Logging
    # ──────────────────────────────────────────────────────────────────────────

    def _log_status(self, message: str):
        """Log status message via the Salesforce client's status callback."""
        if self.sf_client.status_callback:
            self.sf_client.status_callback(message, verbose=True)