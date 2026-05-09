"""
Utility functions for the application
"""
from datetime import timedelta
from typing import Dict


def format_runtime(seconds: float) -> str:
    """Format runtime in HH:MM:SS format"""
    td = timedelta(seconds=int(seconds))
    hours, remainder = divmod(td.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def print_picklist_statistics(stats: Dict, runtime_formatted: str, output_file: str):
    """Prints comprehensive picklist statistics to the console"""
    print("\n" + "=" * 70)
    print("✅ PICKLIST EXPORT COMPLETED SUCCESSFULLY! (Statistics Detail)")
    print("=" * 70)
    print(f"Total Runtime: {runtime_formatted}")
    print(f"Total Objects in List:          {stats['total_objects']}")
    print(f"✅ Successfully Processed:       {stats['successful_objects']}")
    print(f"❌ Failed to Process:            {stats['failed_objects']}")
    print(f"⚠️  Objects Not Found in Org:    {stats['objects_not_found']}")
    print(f"Total Picklist Fields:          {stats['total_picklist_fields']}")
    print(f"Total Picklist Values:          {stats['total_values']}")
    print(f"✅ Active Values:                {stats['total_active_values']}")
    print(f"❌ Inactive Values:              {stats['total_inactive_values']}")
    print(f"Output File: {output_file}")
    if stats['failed_objects'] > 0:
        print("\n❌ FAILED OBJECTS (REASONS):")
        for detail in stats['failed_object_details']:
            print(f"   • {detail['name']}: {detail['reason']}")
    print("=" * 70)


def print_metadata_statistics(stats: Dict, runtime_formatted: str, output_file: str):
    """Prints comprehensive metadata statistics to the console"""
    print("\n" + "=" * 70)
    print("✅ METADATA EXPORT COMPLETED SUCCESSFULLY! (Statistics Detail)")
    print("=" * 70)
    print(f"Total Runtime: {runtime_formatted}")
    print(f"Total Objects in List:          {stats['total_objects']}")
    print(f"✅ Successfully Processed:       {stats['successful_objects']}")
    print(f"❌ Failed to Process:            {stats['failed_objects']}")
    print(f"Total Fields Exported:          {stats['total_fields']}")
    print(f"Output File: {output_file}")
    if stats['failed_objects'] > 0:
        print("\n❌ FAILED OBJECTS (REASONS):")
        for detail in stats['failed_object_details']:
            print(f"   • {detail['name']}: {detail['reason']}")
    print("=" * 70)


def print_content_document_statistics(stats: Dict, runtime_formatted: str, output_file: str, documents_folder: str):
    """Prints comprehensive ContentDocument statistics to the console"""
    print("\n" + "=" * 70)
    print("✅ CONTENTDOCUMENT EXPORT COMPLETED SUCCESSFULLY! (Statistics Detail)")
    print("=" * 70)
    print(f"Total Runtime: {runtime_formatted}")
    print(f"Total ContentDocuments Found:   {stats['total_documents']}")
    print(f"Total Versions Found:           {stats['total_versions']}")
    print(f"✅ Successfully Downloaded:      {stats['successful_downloads']}")
    print(f"❌ Failed Downloads:             {stats['failed_downloads']}")

    # Format file size
    total_mb = stats['total_size_bytes'] / (1024 * 1024)
    print(f"Total Size Downloaded:          {total_mb:.2f} MB")

    print(f"CSV File: {output_file}")
    print(f"Files Folder: {documents_folder}")

    if stats['failed_downloads'] > 0:
        print("\n❌ FAILED FILES (REASONS):")
        for detail in stats['failed_files']:
            print(f"   • {detail['filename']} (ID: {detail['id']}, Version: {detail['version']}): {detail['reason']}")
    print("=" * 70)