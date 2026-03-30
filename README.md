# ⚙️ qw-register-helper - Simple Tool for Account Registration

[![Download Latest Release](https://img.shields.io/badge/Download-qw--register--helper-brightgreen?style=for-the-badge)](https://github.com/qwsedrtgh/qw-register-helper/releases)

---

## 🔽 Download the Software

You can get the latest version of qw-register-helper from the release page here:

[**Download or update here**](https://github.com/qwsedrtgh/qw-register-helper/releases)

This page holds all the available versions. Click on the latest release, then download the file marked for Windows. Once downloaded, you will be ready to install and run the application.

---

## 💻 System Requirements

- Windows 10 or later  
- Python 3.9 or higher installed  
- At least 100 MB free disk space  
- Internet connection to register accounts  

If you do not have Python installed, download it from the official site: https://www.python.org/downloads/windows/

---

## ⚙️ What Does This Software Do?

qw-register-helper helps users register multiple accounts automatically. It handles the process step-by-step, waits between attempts to avoid overload, and keeps track of success and failure counts. The tool can also activate accounts and generate official Qwen OAuth tokens if needed.

This tool targets users who need to register several accounts fast. It reduces manual work and handles the waiting times for you.

---

## 🚀 Getting Started: Step-by-Step Setup Guide

Follow these instructions carefully to run the software without programming knowledge.

### 1. Download the Release

Visit the releases page below and download the latest Windows version:

[**Go to download page**](https://github.com/qwsedrtgh/qw-register-helper/releases)

Save the file to a folder you can easily find, such as `Downloads` or your Desktop.

### 2. Prepare Your Computer

You need Python 3.9 or newer installed.

- To check if Python is installed, open **Command Prompt** and type:
  
  ```
  python --version
  ```

- If it shows a version less than 3.9 or an error, download and install Python from: https://www.python.org/downloads/windows/

Make sure to select “Add Python to PATH” during installation.

### 3. Set Up the Virtual Environment

Open **Command Prompt**, then type the following commands one-by-one:

```
cd <folder_where_you_saved_the_software>
python -m venv venv
venv\Scripts\activate
```

Replace `<folder_where_you_saved_the_software>` with the full path where you put the files.

This step creates and activates an isolated Python environment. This prevents conflicts with other programs.

### 4. Install Required Packages

With the virtual environment active, run:

```
pip install requests
```

This downloads and installs all necessary code qw-register-helper needs to work.

---

## 🛠 Configuration 

Before running, set some environment variables. These tell the software where to connect and protect your info.

Open **Command Prompt** and enter these commands, replacing the example URLs and keys with your own if you have them. If you do not have them, keep the defaults or leave blank for now.

```
set CLOUDFLARE_TEMP_EMAIL_BASE_URL=https://example.com/
set ADMIN_PASSWORDS=["***","***"]
set CLI_PROXY_API_BASE_URL=http://example.com:8317
set CLI_PROXY_API_KEY=sk-***
```

These values are needed for account creation, proxy API integration, and access control.

---

## ▶️ Running the Software

Run these commands to start the tool:

```
cd <folder_where_you_saved_the_software>
venv\Scripts\activate
python qwen_register.py
```

By default, the software will attempt to register 5 accounts.

### Customize number of accounts

You can ask it to register more or fewer accounts at once.

To register 1 account:

```
python qwen_register.py --count 1
```

To register 10 accounts:

```
python qwen_register.py --count 10
```

You can also set the environment variable `QWEN_REGISTER_COUNT` to choose the count.

---

## ⚙️ How It Works

- It tries to register multiple accounts in a batch.
- If one registration fails, it keeps going.
- It waits randomly between 10 and 30 seconds after each account.
- At the end, it shows how many succeeded and how many failed.
- Phase logs show on the screen (standard error).
- Final results output as JSON on the screen (standard output).

This setup helps avoid spam detection and handles errors neatly.

---

## 🔐 Automatic Activation and Token Generation (Optional)

To register accounts, activate them, generate official Qwen OAuth credentials, and upload them to CLIProxyAPI, run:

```
python qwen_register.py --count 5 ^
  --cli-proxy-api-base-url http://example.com:8317 ^
  --cli-proxy-api-key sk-*** ^
  --oauth-headed
```

Change the URLs and keys with your own values.

This option simplifies the process by automating multiple tasks after registration.

---

## 📂 File Structure and Important Files

After you unzip or download the release, the folder should contain:

- `qwen_register.py` – Main program script  
- `requirements.txt` (optional) – dependency list  
- `README.md` – this instruction file  

These are enough to run the application once Python and the packages are installed.

---

## 🆘 Troubleshooting Tips

- If you see errors about Python not working, verify Python is installed and in your PATH.
- If packages fail to install, try running Command Prompt as Administrator.
- If the script quits early or shows errors, double-check you set the environment variables.
- Use only Python 3.9 or higher; older versions are not supported.
- If the program freezes between accounts, check your internet connection.

---

## 🔗 Link to Get the Software Again

Visit the releases page at any time to download the latest version or updates:

[**https://github.com/qwsedrtgh/qw-register-helper/releases**](https://github.com/qwsedrtgh/qw-register-helper/releases)

Make sure you use the newest release for improved features and fixes.