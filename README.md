# Streamlit-based-Town-Dashboard


## How to Download SQLite in Windows:
### Download SQLite:
Navigate to the official SQLite download page and download the precompiled binaries for Windows (typically sqlite-tools-win32-x86-*.zip).
### Extract Files:
Create a dedicated folder for SQLite (e.g., C:\sqlite) and extract the contents of the downloaded zip file into this folder. You should find sqlite3.exe, sqlite3.dll, and sqlite3.def among the extracted files.
### Add to System Path:
  - Right-click on "This PC" or "Computer" and select "Properties." 
  - Click on "Advanced system settings," then "Environment Variables."
  - In the "System variables" section, locate the "Path" variable and click "Edit." 
  - Add the path to your SQLite folder (e.g., C:\sqlite) to the Path variable.
### Verify Installation:
Open a new Command Prompt window and type sqlite3. If installed correctly, the SQLite command-line interface will launch. 

## Install the dependencies and run the code

  - In-order to install the dependences make an environment **"python -m venv env"**
  - then enable the environment using **"env/Scripts/activate"**
  - run the commend **"pip install -r requirements.txt"**
  - and finally run **"streamlit run main.py"**

