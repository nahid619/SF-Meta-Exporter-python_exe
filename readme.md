# 🚀 Salesforce Metadata Exporter

A comprehensive Python desktop application for exporting, managing, and analyzing Salesforce metadata with an intuitive graphical interface.

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/gitplatform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](README.md)

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Installation](#-installation)
- [Quick Start Guide](#-quick-start-guide)
- [Feature Modules](#-feature-modules)
- [Project Structure](#-project-structure)
- [Configuration](#-configuration)
- [Troubleshooting](#-troubleshooting)
- [Building Executable](#-building-executable)
- [Contributing](#-contributing)

---

## 🎯 Overview

**Salesforce Metadata Exporter** is a powerful desktop application for Salesforce metadata management, data extraction, and automation control. Built with Python and CustomTkinter for DevOps engineers, Salesforce administrators, and data analysts.

### System Requirements

- **Python**: 3.10 or higher
- **OS**: Windows 10+, macOS 10.14+, Linux (Ubuntu 20.04+)
- **RAM**: 4 GB minimum (8 GB recommended)
- **Salesforce**: API access with appropriate permissions

---

## ✨ Key Features

### 🔐 Authentication
- Production, Sandbox, and Custom Domain support
- Optional security token (IP whitelisting)
- Session management with reconnection

### 📊 Six Powerful Modules

1. **Picklist Exporter** → Excel with active/inactive status
2. **Metadata Exporter** → CSV with field usage tracking across 13+ metadata types
3. **ContentDocument Downloader** → Bulk file download with metadata
4. **SOQL Query Runner** → Interactive queries with smart autocomplete
5. **Salesforce Switch** → Bulk enable/disable automation (Validation Rules, Workflows, Flows, Triggers)
6. **Report Exporter** → Native Excel export preserving ALL formatting (groupings, subtotals, colors)

### 🚀 Performance Highlights

- **Concurrent Downloads**: 10+ parallel operations
- **Virtual Scrolling**: Handle 10,000+ items without lag
- **Batch Processing**: Smart retry logic with exponential backoff
- **Progress Tracking**: Real-time ETA and speed metrics

---

## 📦 Installation

### Step 1: Create Virtual Environment

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

**Required Packages:**
- `customtkinter` - Modern GUI framework
- `simple-salesforce` - Salesforce API wrapper
- `requests` - HTTP library
- `openpyxl` - Excel file operations
- `darkdetect` - System theme detection
- `psutil` - System monitoring

### Step 3: Run Application
```bash
python main.py
```

---

## 🚀 Quick Start Guide

### 1. Login to Salesforce

**Production/Sandbox:**
- Select org type
- Enter username, password, security token
- Click "Login to Salesforce"

**Custom Domain (My Domain):**
- Check "🌐 Use Custom Domain"
- Enter domain (e.g., `mycompany.my.salesforce.com`)
- Enter credentials

💡 **Tip**: Leave security token blank if your IP is whitelisted.

### 2. Export Picklist Data
```
1. Select objects (Account, Contact, etc.)
2. Click "Export Picklist Data"
3. Choose save location → Excel file created
```

**Output**: Object, Field Label, Field API, Picklist Value Label, Value API, Status

### 3. Export Metadata with Field Usage
```
1. Select objects
2. Click "Export Metadata"
3. Wait for usage analysis (~1-2 minutes)
4. Review CSV with "Field Usage" column
```

**Field Usage Tracks**: Page Layouts, Validation Rules, Workflows, Flows, Apex Classes, Triggers, Visualforce Pages, Lightning Components, Email Templates, Custom Buttons

### 4. Download Files
```
1. Click "Download Files" (no selection needed)
2. Choose save location
3. Files download to Documents/ subfolder
4. CSV metadata created
```

### 5. Run SOQL Queries
```
1. Click "Run SOQL"
2. Type query: SELECT Id, Name FROM Account
3. Press Ctrl+Space for field suggestions
4. Press Ctrl+Enter to execute
5. Export results to CSV
```

### 6. Salesforce Switch (Automation Control)
```
⚠️ CRITICAL: Triggers take 5-15 minutes (runs all Apex tests)

1. Click "Salesforce Switch"
2. Wait for components to load
3. Search/filter components
4. Select components or click "DISABLE ALL"
5. Click "🚀 DEPLOY CHANGES"
6. Use "🔄 ROLLBACK" to undo before deployment
```

### 7. Report Exporter
```
1. Click "📊 Report Export"
2. Search reports by keyword
3. Select reports (individual or entire folders)
4. Choose format: Excel (.xlsx) or CSV
5. Click "🚀 EXPORT REPORTS"
6. Monitor progress with ETA
7. Cancel anytime (saves partial exports)
```

**Excel Format**: Preserves groupings, subtotals, grand totals, formatting, merged cells (same as Salesforce UI)

---

## 📁 Project Structure
```
salesforce-metadata-exporter/
│
├── main.py                          # Entry point
├── gui.py                           # Main GUI (login, export)
├── config.py                        # Configuration
├── requirements.txt                 # Dependencies
│── salesforce_client.py             # Authentication
│── threading_helper.py              # Background threads
│── utils.py                         # Utilities
│── picklist_exporter.py             # Picklist export
│── metadata_exporter.py             # Metadata export
│── content_document_exporter.py     # File downloads
│── field_usage_tracker.py           # Usage analysis
│── soql_runner.py                   # Query execution
│── soql_query_frame.py              # SOQL UI
│── metadata_switch_manager.py       # Component manager
│── salesforce_switch_frame.py       # Switch UI
│── trigger_deployer.py              # Trigger deployment
└── Report Exporter/
    ├── main_app.py                  # Report UI
    ├── exporter.py                  # Export engine
    └── virtual_tree.py              # Virtual scrolling
```

**Total Lines of Code**: ~9,100 lines across 20+ modules

---

## ⚙️ Configuration

### API Settings (`config.py`)
```python
API_VERSION = '65.0'  # Salesforce API version
WINDOW_GEOMETRY = "1200x800"  # Default window size
APPEARANCE_MODE = "System"  # Light/Dark/System
```

### Environment Variables (Optional)
```bash
# Set custom API version
export SF_API_VERSION="62.0"

# Set default org type
export SF_ORG_TYPE="Production"
```

---

## 🔧 Troubleshooting

### Login Issues

**"Custom Domain Not Found"**
- ✅ Check domain spelling (no `https://`)
- ✅ Ensure My Domain is active in Salesforce
- ✅ Use format: `mycompany.my.salesforce.com`

**"Invalid Username or Password"**
- ✅ Verify credentials in Salesforce
- ✅ Check if account is locked
- ✅ Try resetting password

**"Security Token Required"**
- ✅ Get token: Setup → My Personal Information → Reset Security Token
- ✅ Or whitelist your IP in Salesforce

### Export Errors

**"Some objects failed to export"**
- Objects may require specific permissions
- Check status log for details
- Verify object API names

**"Field usage tracking incomplete"**
- Large orgs may timeout
- Partial results are still saved
- Re-run for specific objects

### Performance Issues

**"Application slow with 10,000+ reports"**
- ✅ Use search to filter results
- ✅ Select fewer reports per export
- ✅ Use CSV format (faster than Excel)

**"Export cancelled unexpectedly"**
- Check internet connection
- Verify Salesforce API limits not exceeded
- Review error logs in status window

### Salesforce Switch Issues

**"Trigger deployment takes 15+ minutes"**
- ✅ Expected behavior (runs ALL Apex tests)
- ✅ Deploy during maintenance windows
- ✅ Consider disabling in batches

**"Some components failed to deploy"**
- Check error messages in summary
- Components may have dependencies
- Retry individual components

---

## 🏗️ Building Executable for macOS ".app"

Create a standalone macOS executable or .app bundle
(no Python installation required on the target machine).

⚠️ Important
- The build must be created on macOS
- Python must be installed on the build machine
- Requires macOS 11+ for universal builds

### Create a virtual environment
```bash
python3 -m venv venv
```

### Activate the virtual environment
```bash
source venv/bin/activate
```

### Upgrade pip
```bash
pip install --upgrade pip
```

### Install the dependencies
```bash
pip install -r requirements.txt
```

### Install PyInstaller for creating the build
```bash
pip install pyinstaller
```

### Build Single File Executable

**Recommended (most portable):**
For Intel + Apple Silicon architecture (Universal Binary)
```bash
pyinstaller \
  --onefile \
  --windowed \
  --name "SF_Meta_Exporter" \
  --icon=app_icon.icns \
  --target-arch universal2 \
  --add-data "app_icon.icns:." \
  main.py
```

**Single architecture (either Apple Silicon or Intel):**
```bash
pyinstaller \
  --onefile \
  --windowed \
  --name "SF_Meta_Exporter" \
  --icon=app_icon.icns \
  --add-data "app_icon.icns:." \
  main.py
```
---
---
## 🏗️ Building Executable

Create a portable `.exe` file for Windows deployment (no Python installation required).

### Prerequisites
```bash
pip install pyinstaller
```

### Build Single File Executable

**Recommended (most portable):**
```bash
pyinstaller --onefile --windowed --name "SF_Meta_Exporter" --icon=app_icon.ico main.py
```

**Alternative (faster startup):**
```bash
pyinstaller --windowed --name "SF_Meta_Exporter" --icon=app_icon.ico main.py
```

### Build Options

| Flag | Purpose |
|------|---------|
| `--onefile` | Single .exe (more portable) |
| `--windowed` | Hide console window (GUI only) |
| `--name` | Custom executable name |
| `--icon` | Custom icon file (.ico) |

### Find Your Executable
```
dist/
└── SF_Meta_Exporter.exe  ← Your portable application
```

### Distribution

1. Copy `.exe` from `dist/` folder
2. Test on target machine
3. No Python installation needed!
4. Distribute as single file

**File Size**: ~50-80 MB (includes Python runtime + all dependencies)

**Note**: First run may be slow (extracts to temp directory). Subsequent runs are faster.

---

## 🤝 Contributing

Contributions welcome! Please follow these guidelines:

1. Fork the repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

### Development Setup
```bash
# Clone repository
git clone https://github.com/your-username/salesforce-metadata-exporter.git
cd salesforce-metadata-exporter

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Install dependencies with dev tools
pip install -r requirements.txt
pip install pytest black pylint

# Run tests
pytest tests/

# Format code
black .

# Lint code
pylint *.py
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **CustomTkinter** - Modern GUI framework
- **Simple-Salesforce** - Salesforce API wrapper
- **Salesforce Developer Community** - API documentation and support

---

## 📞 Support

For issues, questions, or feature requests:

1. Check the [Troubleshooting](#-troubleshooting) section
2. Review status logs in the application
3. Open an issue on [GitHub](https://github.com/your-username/salesforce-metadata-exporter/issues)
4. Contact: your-email@example.com

---

**Version**: 2.0.0  
**Last Updated**: December 2024  
**Author**: Your Name

---

Made with ❤️ for the Salesforce community