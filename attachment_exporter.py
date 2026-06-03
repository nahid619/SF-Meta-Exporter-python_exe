# FILE PATH: attachment_exporter.py  (place in project root, same level as content_document_exporter.py)
"""
Attachment export functionality — downloads legacy Salesforce Attachment records
filtered by parent object type and saves them with a DataLoader-compatible CSV manifest.
"""
import os
import csv
import requests
from typing import List, Dict, Tuple
from salesforce_client import SalesforceClient


class AttachmentExporter:
    """Handles legacy Attachment downloads from Salesforce, filtered by parent object type."""

    def __init__(self, sf_client: SalesforceClient):
        self.sf_client = sf_client
        self.sf        = sf_client.sf
        self.base_url  = sf_client.base_url
        self.headers   = sf_client.headers

    # ── Public entry point ────────────────────────────────────────────────────

    def export_attachments(
        self,
        output_path: str,
        selected_objects: List[str],
        status_callback=None,
    ) -> Tuple[str, Dict]:
        """
        Download Attachment records whose Parent.Type is in selected_objects.

        Args:
            output_path:      Full path for the attachment_manifest.csv file.
            selected_objects: List of object API names (e.g. ['Account', 'Case']).
            status_callback:  Optional callable(message: str) for live UI updates.

        Returns:
            Tuple of (csv_path, stats_dict)
        """
        self._cb = status_callback  # store for internal use

        self._log("=== Starting Legacy Attachment Export ===")
        self._log(f"Objects selected: {', '.join(selected_objects)}")

        stats = {
            'total_attachments':   0,
            'successful_downloads': 0,
            'failed_downloads':     0,
            'total_size_bytes':     0,
            'failed_files':         [],
            'objects_processed':    [],
        }

        # Create Attachments/ folder next to the CSV
        csv_dir           = os.path.dirname(output_path)
        attachments_folder = os.path.join(csv_dir, "Attachments")
        if not os.path.exists(attachments_folder):
            os.makedirs(attachments_folder)
            self._log(f"Created folder: {attachments_folder}")

        all_manifest_rows = []

        # ── Process each selected object type in sequence ─────────────────────
        for obj_type in selected_objects:
            self._log(f"\n── {obj_type} ──")
            self._log(f"Querying Attachments where Parent.Type = '{obj_type}'…")

            try:
                records = self._query_attachments_for_object(obj_type)
            except Exception as e:
                self._log(f"  ❌ Query failed for {obj_type}: {e}")
                stats['objects_processed'].append({
                    'object': obj_type, 'found': 0,
                    'downloaded': 0, 'failed': 0,
                })
                continue

            found = len(records)
            stats['total_attachments'] += found
            self._log(f"  Found {found} Attachment(s)")

            obj_downloaded = 0
            obj_failed     = 0

            for idx, attachment in enumerate(records, 1):
                att_id   = attachment['Id']
                name     = attachment.get('Name') or 'untitled'
                filename = self._build_filename(att_id, name)
                filepath = os.path.join(attachments_folder, filename)
                path_in_zip = f"Attachments/{filename}"

                self._log(f"  [{idx}/{found}] {filename}")

                parent_name = (attachment.get('Parent') or {}).get('Name', '')
                owner_name  = (attachment.get('Owner')  or {}).get('Name', '')

                try:
                    body_bytes = self._download_body(att_id)

                    with open(filepath, 'wb') as f:
                        f.write(body_bytes)

                    size_bytes = len(body_bytes)
                    stats['total_size_bytes']      += size_bytes
                    stats['successful_downloads']  += 1
                    obj_downloaded                 += 1

                    self._log(
                        f"    ✓ {filename} ({size_bytes / 1024:.1f} KB)"
                        + (f" — {obj_type}: {parent_name}" if parent_name else "")
                    )

                    all_manifest_rows.append(self._build_row(
                        attachment, obj_type, parent_name, owner_name,
                        path_in_zip, success=True,
                    ))

                except Exception as e:
                    stats['failed_downloads'] += 1
                    obj_failed               += 1
                    stats['failed_files'].append({
                        'id': att_id, 'filename': filename, 'reason': str(e),
                    })
                    self._log(f"    ✗ {filename}: {e}")

                    all_manifest_rows.append(self._build_row(
                        attachment, obj_type, parent_name, owner_name,
                        path_in_zip, success=False, error=str(e),
                    ))

            self._log(
                f"  {obj_type} done — "
                f"{obj_downloaded} downloaded, {obj_failed} failed"
            )
            stats['objects_processed'].append({
                'object':     obj_type,
                'found':      found,
                'downloaded': obj_downloaded,
                'failed':     obj_failed,
            })

        # ── Write CSV manifest ─────────────────────────────────────────────────
        self._log("\nWriting attachment_manifest.csv…")
        self._write_csv(output_path, all_manifest_rows)
        self._log(f"CSV saved: {output_path}")
        self._log(
            f"\n=== Done — {stats['successful_downloads']} downloaded, "
            f"{stats['failed_downloads']} failed, "
            f"{stats['total_size_bytes'] / 1024 / 1024:.1f} MB ==="
        )

        return output_path, stats

    # ── Salesforce queries ────────────────────────────────────────────────────

    def _query_attachments_for_object(self, object_type: str) -> List[Dict]:
        """Query all Attachments where Parent.Type = object_type."""
        soql = (
            "SELECT Id, Name, ParentId, Parent.Type, Parent.Name, "
            "ContentType, BodyLength, IsPrivate, Description, "
            "OwnerId, Owner.Name, CreatedById, CreatedDate, "
            "LastModifiedById, LastModifiedDate "
            f"FROM Attachment WHERE Parent.Type = '{object_type}' "
            "ORDER BY CreatedDate DESC"
        )
        result  = self.sf.query_all(soql)
        return result.get('records', [])

    # ── File download ─────────────────────────────────────────────────────────

    def _download_body(self, attachment_id: str, max_attempts: int = 3) -> bytes:
        """Download the binary body of one Attachment with retry."""
        url = (
            f"{self.base_url}/services/data/"
            f"v{self.sf_client.api_version}/"
            f"sobjects/Attachment/{attachment_id}/Body"
        )
        for attempt in range(1, max_attempts + 1):
            try:
                resp = requests.get(url, headers=self.headers, timeout=120)
                if resp.status_code != 200:
                    raise Exception(f"HTTP {resp.status_code}")
                return resp.content
            except Exception as e:
                if attempt == max_attempts:
                    raise
                import time
                time.sleep(attempt)  # linear back-off: 1s, 2s

    # ── Filename builder ──────────────────────────────────────────────────────

    @staticmethod
    def _build_filename(attachment_id: str, name: str) -> str:
        """
        {Name}_{Id}.{ext}  — name first, extension always last.
        Mirrors the web app's buildAttachmentFilename().
        """
        safe = "".join(
            c if c not in r'<>:"/\|?*' and ord(c) >= 32 else '_'
            for c in str(name or 'untitled')
        )[:200].strip()

        dot = safe.rfind('.')
        has_ext = 0 < dot < len(safe) - 1
        base = safe[:dot] if has_ext else safe
        ext  = safe[dot:] if has_ext else ''       # e.g. ".pdf"
        return f"{base}_{attachment_id}{ext}"

    # ── CSV helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_row(
        attachment: Dict,
        parent_type: str,
        parent_name: str,
        owner_name: str,
        path_in_zip: str,
        success: bool,
        error: str = '',
    ) -> List[str]:
        return [
            attachment.get('Id', ''),
            attachment.get('Name', ''),
            attachment.get('ParentId', ''),
            parent_type,
            parent_name,
            attachment.get('ContentType', ''),
            str(attachment.get('BodyLength', 0)),
            'TRUE' if attachment.get('IsPrivate') else 'FALSE',
            attachment.get('Description', '') or '',
            attachment.get('OwnerId', ''),
            owner_name,
            attachment.get('CreatedById', ''),
            attachment.get('CreatedDate', ''),
            attachment.get('LastModifiedById', ''),
            attachment.get('LastModifiedDate', ''),
            path_in_zip,
            'Success' if success else 'Failed',
            error,
        ]

    CSV_HEADERS = [
        'Id', 'Name', 'ParentId', 'ParentType', 'ParentName',
        'ContentType', 'BodyLength (Bytes)', 'IsPrivate', 'Description',
        'OwnerId', 'OwnerName', 'CreatedById', 'CreatedDate',
        'LastModifiedById', 'LastModifiedDate',
        'PathInFolder', 'DownloadStatus', 'FailureReason',
    ]

    def _write_csv(self, output_path: str, rows: List[List[str]]):
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(self.CSV_HEADERS)
            writer.writerows(rows)

    # ── Internal logger ───────────────────────────────────────────────────────

    def _log(self, message: str):
        if self._cb:
            self._cb(message)
        print(message)