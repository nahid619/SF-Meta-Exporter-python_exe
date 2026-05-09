"""
ContentDocument export functionality - exports metadata and downloads files
"""
import os
import csv
import requests
from typing import List, Dict, Tuple
from salesforce_client import SalesforceClient


class ContentDocumentExporter:
    """Handles ContentDocument metadata export and file downloads from Salesforce"""
    
    def __init__(self, sf_client: SalesforceClient):
        """Initialize with Salesforce client"""
        self.sf_client = sf_client
        self.sf = sf_client.sf
        self.base_url = sf_client.base_url
        self.headers = sf_client.headers
    
    
    def export_content_documents(self, output_path: str) -> Tuple[str, Dict]:
        """
        Export ContentDocument metadata to CSV and download all file versions
        
        Args:
            output_path: Path for the CSV file
            
        Returns:
            Tuple of (csv_path, statistics_dict)
        """
        self._log_status("=== Starting ContentDocument Export ===")
        
        stats = {
            'total_documents': 0,
            'total_versions': 0,
            'successful_downloads': 0,
            'failed_downloads': 0,
            'total_size_bytes': 0,
            'failed_files': []
        }
        
        # Create Documents folder in same directory as CSV
        csv_dir = os.path.dirname(output_path)
        documents_folder = os.path.join(csv_dir, "Documents")
        
        if not os.path.exists(documents_folder):
            os.makedirs(documents_folder)
            self._log_status(f"Created folder: {documents_folder}")
        
        # Query all ContentDocuments
        self._log_status("Querying ContentDocument records...")
        content_documents = self._query_content_documents()
        stats['total_documents'] = len(content_documents)
        
        self._log_status(f"Found {len(content_documents)} ContentDocument records")
        
        if len(content_documents) == 0:
            self._log_status("No ContentDocument records found in org")
            # Still create empty CSV
            self._create_csv_file([], output_path)
            return output_path, stats
        
        # This will hold all version data for CSV
        all_version_data = []
        
        # Process each ContentDocument
        for doc_index, doc in enumerate(content_documents, 1):
            doc_id = doc['Id']
            title = doc['Title']
            file_extension = doc.get('FileExtension', '')
            
            self._log_status(f"\n[{doc_index}/{len(content_documents)}] Processing: {title}")
            
            # Query all versions for this document
            versions = self._query_all_versions(doc_id)
            
            if not versions:
                self._log_status(f"  ⚠️ No versions found for {title}")
                continue
            
            stats['total_versions'] += len(versions)
            total_versions_count = len(versions)
            
            self._log_status(f"  Found {total_versions_count} version(s)")
            
            # Download each version
            for version_index, version in enumerate(versions, 1):
                version_id = version['Id']
                version_number = version['VersionNumber']
                is_latest = version['IsLatest']
                content_size = version.get('ContentSize', 0)
                
                self._log_status(f"  [{version_index}/{total_versions_count}] Downloading version {version_number}...")
                
                try:
                    # Download the file
                    file_path = self._download_file(
                        document_id=doc_id,
                        title=title,
                        file_extension=file_extension,
                        version_id=version_id,
                        version_number=version_number,
                        destination_folder=documents_folder
                    )
                    
                    # Extract just the filename from full path
                    downloaded_filename = os.path.basename(file_path)
                    
                    # Build PathOnClient (relative path for DataLoader)
                    path_on_client = f"Documents/{downloaded_filename}"
                    
                    stats['successful_downloads'] += 1
                    stats['total_size_bytes'] += content_size
                    
                    self._log_status(f"    ✅ Downloaded: {downloaded_filename}")
                    
                    # Build version data for CSV
                    version_data = {
                        'document': doc,
                        'version': version,
                        'downloaded_filename': downloaded_filename,
                        'path_on_client': path_on_client,
                        'version_number': version_number,
                        'is_latest': is_latest,
                        'total_versions': total_versions_count
                    }
                    
                    all_version_data.append(version_data)
                    
                except Exception as e:
                    error_msg = str(e)
                    self._log_status(f"    ❌ ERROR: {error_msg}")
                    stats['failed_downloads'] += 1
                    
                    # Build filename for error reporting
                    if file_extension:
                        filename = f"{title}_{doc_id}_v{version_number}.{file_extension}"
                    else:
                        filename = f"{title}_{doc_id}_v{version_number}"
                    
                    stats['failed_files'].append({
                        'filename': filename,
                        'id': doc_id,
                        'version': version_number,
                        'reason': error_msg
                    })
        
        # Create CSV with all version data
        self._log_status("\n=== Creating CSV File ===")
        final_output_path = self._create_csv_file(all_version_data, output_path)
        
        return final_output_path, stats
    
    
    def _query_content_documents(self) -> List[Dict]:
        """Query all ContentDocument records with standard fields"""
        try:
            # Query ContentDocument with standard fields
            query = """
                SELECT Id, Title, FileExtension, FileType, ContentSize, 
                       CreatedDate, CreatedById, LastModifiedDate, LastModifiedById,
                       OwnerId, ParentId, IsArchived, IsDeleted, 
                       ArchivedDate, ArchivedById, Description,
                       PublishStatus, LatestPublishedVersionId
                FROM ContentDocument
                ORDER BY CreatedDate DESC
            """
            
            result = self.sf.query_all(query)
            return result['records']
            
        except Exception as e:
            self._log_status(f"ERROR querying ContentDocument: {str(e)}")
            raise
        
    def _query_all_versions(self, document_id: str) -> List[Dict]:
        """
        Query all versions for a specific ContentDocument
        
        Args:
            document_id: ContentDocument Id
            
        Returns:
            List of ContentVersion records with version info
        """
        try:
            # Query ALL versions (removed IsLatest = true filter)
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
    
    def _download_file(self, document_id: str, title: str, file_extension: str, 
                    version_id: str, version_number: int, destination_folder: str) -> str:
        """
        Download a single file version from Salesforce
        
        Args:
            document_id: ContentDocument Id
            title: Document title
            file_extension: File extension
            version_id: ContentVersion Id
            version_number: Version number (1, 2, 3, etc.)
            destination_folder: Folder to save the file
            
        Returns:
            Full path of downloaded file
        """
        try:
            # Build filename: {Title}_{ContentDocumentId}_v{VersionNumber}.{Extension}
            if file_extension:
                filename = f"{title}_{document_id}_v{version_number}.{file_extension}"
            else:
                filename = f"{title}_{document_id}_v{version_number}"
            
            # Sanitize filename to remove invalid characters
            safe_filename = self._sanitize_filename(filename)
            
            # Build download URL
            download_url = f"{self.base_url}/services/data/v{self.sf_client.api_version}/sobjects/ContentVersion/{version_id}/VersionData"
            
            # Download the file
            response = requests.get(download_url, headers=self.headers, timeout=120)
            response.raise_for_status()
            
            # Full file path
            file_path = os.path.join(destination_folder, safe_filename)
            
            # Write file to disk
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            return file_path
            
        except Exception as e:
            raise Exception(f"Failed to download version {version_number}: {str(e)}")
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename
    

    
    def _create_csv_file(self, all_version_data: List[Dict], output_path: str) -> str:
        """
        Create CSV file with ContentVersion metadata (DataLoader-ready)
        
        Args:
            all_version_data: List of version data dictionaries
            output_path: Path for the CSV file
            
        Returns:
            Path to created CSV file
        """
        # CSV headers (DataLoader-compatible)
        headers = [
            # ========== REQUIRED for DataLoader Import ==========
            'Title',
            'PathOnClient',
            
            # ========== OPTIONAL for DataLoader (Migration Support) ==========
            'ContentDocumentId',
            'FirstPublishLocationId',
            'Description',
            'Origin',
            
            # ========== VERSION METADATA (Reference) ==========
            'VersionNumber',
            'IsLatestVersion',
            'Total_Versions_Available',
            
            # ========== FILE METADATA (Reference) ==========
            'FileExtension',
            'FileType',
            'ContentSize (Bytes)',
            
            # ========== SALESFORCE METADATA (Reference) ==========
            'CreatedDate',
            'LastModifiedDate',
            'OwnerId'
        ]
        
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(headers)
            
            for version_data in all_version_data:
                doc = version_data['document']
                version = version_data['version']
                
                row = [
                    # ========== REQUIRED for DataLoader ==========
                    doc.get('Title', ''),                           # Title
                    version_data['path_on_client'],                 # PathOnClient (Documents/Report_069gL000C1_v1.pdf)
                    
                    # ========== OPTIONAL for DataLoader ==========
                    doc.get('Id', ''),                              # ContentDocumentId
                    '',                                              # FirstPublishLocationId (blank - user fills)
                    doc.get('Description', ''),                     # Description (blank or from doc)
                    'H',                                             # Origin ('H' = uploaded)
                    
                    # ========== VERSION METADATA ==========
                    version_data['version_number'],                 # VersionNumber (1, 2, 3...)
                    'TRUE' if version_data['is_latest'] else 'FALSE',  # IsLatestVersion
                    version_data['total_versions'],                 # Total_Versions_Available
                    
                    # ========== FILE METADATA ==========
                    doc.get('FileExtension', ''),                   # FileExtension
                    doc.get('FileType', ''),                        # FileType
                    version.get('ContentSize', 0),                  # ContentSize (Bytes)
                    
                    # ========== SALESFORCE METADATA ==========
                    version.get('CreatedDate', ''),                 # CreatedDate
                    version.get('LastModifiedDate', ''),            # LastModifiedDate
                    doc.get('OwnerId', '')                          # OwnerId
                ]
                
                writer.writerow(row)
        
        self._log_status(f"✅ CSV file created: {output_path}")
        self._log_status(f"✅ Total rows exported: {len(all_version_data)}")
        
        return output_path
    
    def _log_status(self, message: str):
        """Log status message"""
        if self.sf_client.status_callback:
            self.sf_client.status_callback(message, verbose=True)
