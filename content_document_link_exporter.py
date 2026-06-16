"""
ContentDocument export scoped to a specific Salesforce object type via
ContentDocumentLink.

Inherits all download, CSV, version-query, and logging logic from
ContentDocumentExporter — only the initial query step is replaced with a
3-step batched approach that satisfies Salesforce's ContentDocumentLink
restriction (must filter by LinkedEntityId using = or IN).
"""
from typing import List, Dict, Set, Optional, Tuple
from content_document_exporter import ContentDocumentExporter


# Batch sizes — conservative to stay well within SOQL limits
RECORD_ID_CHUNK_SIZE = 200   # LinkedEntityId IN (200 ids)
DOC_ID_CHUNK_SIZE    = 200   # ContentDocument Id IN (200 ids)


class ContentDocumentLinkExporter(ContentDocumentExporter):
    """
    Extends ContentDocumentExporter to scope downloads to files linked to a
    specific Salesforce object type (e.g. Project__c, Account, Opportunity).

    Design
    ------
    Uses an instance-level mode flag (_linked_object_type) so that the
    inherited export_content_documents() pipeline calls our overridden
    _query_content_documents() transparently.  All download / CSV /
    version-query logic from the parent is re-used without duplication.

    3-Step Query Strategy
    ---------------------
    Step 1  SELECT Id FROM {ObjectType}
            → list of record Ids

    Step 2  SELECT ContentDocumentId FROM ContentDocumentLink
              WHERE LinkedEntityId IN (<chunk of record Ids>)
            → deduplicated set of ContentDocumentIds
            (chunked in batches of RECORD_ID_CHUNK_SIZE)

    Step 3  SELECT Id, Title, ... FROM ContentDocument
              WHERE Id IN (<chunk of doc Ids>)
              [AND <active date / text filters>]
            → final document records
            (chunked in batches of DOC_ID_CHUNK_SIZE)
    """

    def __init__(self, sf_client):
        super().__init__(sf_client)
        self._linked_object_type: Optional[str] = None   # mode flag

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def export_content_documents_for_object(
        self,
        output_path: str,
        object_type: str,
        filters: Optional[Dict] = None,
    ) -> Tuple[str, Dict]:
        """
        Export ContentDocuments linked to records of `object_type`, optionally
        narrowed by the same date / text filters used in the standard export.

        Args:
            output_path:  Path for the output CSV file.
            object_type:  Salesforce API name, e.g. 'Project__c', 'Account'.
            filters:      Optional filter dict from the Download Files modal.

        Returns:
            Tuple of (csv_path, statistics_dict)
        """
        self._linked_object_type = object_type
        try:
            # Delegates the entire download + CSV pipeline to the parent.
            # Our overridden _query_content_documents() handles the 3-step
            # query transparently inside that pipeline.
            return self.export_content_documents(output_path, filters)
        finally:
            self._linked_object_type = None   # always reset, even on exception

    # ──────────────────────────────────────────────────────────────────────────
    # Overridden query — plugs into the parent's pipeline
    # ──────────────────────────────────────────────────────────────────────────

    def _query_content_documents(self, filters: Optional[Dict] = None) -> List[Dict]:
        """
        When _linked_object_type is set, runs the 3-step batched query.
        Falls back to the standard parent query otherwise, keeping this class
        usable as a drop-in replacement for ContentDocumentExporter.
        """
        if not self._linked_object_type:
            return super()._query_content_documents(filters)

        object_type = self._linked_object_type

        # ── Step 1: record Ids from the target object ─────────────────────────
        self._log_status(f"[Step 1/3] Querying {object_type} record Ids...")
        record_ids = self._query_object_record_ids(object_type)
        self._log_status(f"[Step 1/3] Found {len(record_ids)} {object_type} record(s)")

        if not record_ids:
            self._log_status(
                f"No {object_type} records found — "
                "export will produce an empty CSV."
            )
            return []

        # ── Step 2: ContentDocumentIds via ContentDocumentLink (chunked) ──────
        self._log_status("[Step 2/3] Fetching linked ContentDocumentIds...")
        doc_id_set: Set[str] = set()
        id_chunks   = self._chunk(record_ids, RECORD_ID_CHUNK_SIZE)
        total_link_chunks = len(id_chunks)

        for i, chunk in enumerate(id_chunks, 1):
            self._log_status(
                f"[Step 2/3] ContentDocumentLink batch {i}/{total_link_chunks} "
                f"({len(chunk)} record Ids)..."
            )
            linked_ids = self._query_linked_document_ids(chunk)
            doc_id_set.update(linked_ids)

        self._log_status(
            f"[Step 2/3] Found {len(doc_id_set)} unique ContentDocument(s) "
            f"linked to {object_type}"
        )

        if not doc_id_set:
            self._log_status(
                "No linked ContentDocuments found — "
                "export will produce an empty CSV."
            )
            return []

        # ── Step 3: ContentDocument records by Ids + active modal filters ─────
        self._log_status("[Step 3/3] Querying ContentDocument records...")
        doc_id_list  = list(doc_id_set)
        doc_chunks   = self._chunk(doc_id_list, DOC_ID_CHUNK_SIZE)
        total_doc_chunks = len(doc_chunks)
        content_documents: List[Dict] = []

        for i, chunk in enumerate(doc_chunks, 1):
            self._log_status(
                f"[Step 3/3] ContentDocument batch {i}/{total_doc_chunks} "
                f"({len(chunk)} document Ids)..."
            )
            docs = self._query_content_documents_by_ids(chunk, filters)
            content_documents.extend(docs)

        # Match the ORDER BY CreatedDate DESC of the standard query
        content_documents.sort(
            key=lambda d: d.get("CreatedDate", ""),
            reverse=True
        )

        self._log_status(
            f"[Step 3/3] ContentDocument records after applying filters: "
            f"{len(content_documents)}"
        )
        return content_documents

    # ──────────────────────────────────────────────────────────────────────────
    # New private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _query_object_record_ids(self, object_type: str) -> List[str]:
        """Return all Id values from the given Salesforce object (Step 1)."""
        try:
            query  = f"SELECT Id FROM {object_type} ORDER BY Id ASC"
            result = self.sf.query_all(query)
            return [record["Id"] for record in result["records"]]
        except Exception as e:
            self._log_status(f"ERROR querying {object_type}: {str(e)}")
            raise

    def _query_linked_document_ids(self, record_id_chunk: List[str]) -> Set[str]:
        """
        Return the set of ContentDocumentIds linked to the given record Ids
        (Step 2).

        Filters by LinkedEntityId IN (...) — the only form Salesforce allows
        on ContentDocumentLink without a MALFORMED_QUERY error.
        """
        try:
            id_list = ", ".join(f"'{rid}'" for rid in record_id_chunk)
            query   = f"""
                SELECT ContentDocumentId
                FROM ContentDocumentLink
                WHERE LinkedEntityId IN ({id_list})
            """
            result = self.sf.query_all(query)
            return {record["ContentDocumentId"] for record in result["records"]}
        except Exception as e:
            self._log_status(f"ERROR querying ContentDocumentLink: {str(e)}")
            raise

    def _query_content_documents_by_ids(
        self,
        doc_id_chunk: List[str],
        filters: Optional[Dict],
    ) -> List[Dict]:
        """
        Query a batch of ContentDocument records by Id, combining the Id IN
        clause with any active modal filters (Step 3).

        Re-uses _build_where_clause() from the parent to avoid duplicating
        the filter-to-SOQL logic.
        """
        try:
            id_list   = ", ".join(f"'{did}'" for did in doc_id_chunk)
            id_clause = f"Id IN ({id_list})"

            # Reuse the parent's filter builder; strip its WHERE keyword so we
            # can prepend our own Id clause.
            filter_where = self._build_where_clause(filters)  # "WHERE x AND y" or ""
            if filter_where:
                extra        = filter_where[6:]               # strip leading "WHERE "
                where_clause = f"WHERE {id_clause} AND {extra}"
            else:
                where_clause = f"WHERE {id_clause}"

            query = f"""
                SELECT Id, Title, FileExtension, FileType, ContentSize,
                       CreatedDate, CreatedById, LastModifiedDate, LastModifiedById,
                       OwnerId, ParentId, IsArchived, IsDeleted,
                       ArchivedDate, ArchivedById, Description,
                       PublishStatus, LatestPublishedVersionId
                FROM ContentDocument
                {where_clause}
            """
            result = self.sf.query_all(query)
            return result["records"]
        except Exception as e:
            self._log_status(f"ERROR querying ContentDocument by Ids: {str(e)}")
            raise

    # ──────────────────────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _chunk(lst: List, size: int) -> List[List]:
        """Split a list into sub-lists of at most `size` items."""
        return [lst[i : i + size] for i in range(0, len(lst), size)]
