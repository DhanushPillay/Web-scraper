# PythonAnywhere Deployment Guide

This guide covers deploying your Sniffer Flask app to PythonAnywhere (free tier).

---

## **Why PythonAnywhere?**

✅ **Persistent SQLite storage** — Database survives between requests  
✅ **Background jobs with APScheduler** — News scraper runs on schedule  
✅ **No execution time limits** — Long-running operations supported  
✅ **Free tier** — 512MB storage, 100 CPU-seconds/day  
✅ **Simple deployment** — Upload code or use Git  

---

## **Project Structure**

Your project is already structured correctly for PythonAnywhere:

```
e:\Personal Projects\Web scraper/
├── app.py                          ← Flask app (WSGI entry point)
├── requirements.txt                ← Python dependencies
├── database.py                     ← SQLite database module
├── web_scraper.py                  ← Web scraping logic
├── templates/
│   └── index.html                  ← Flask templates
├── static/
│   └── service-worker.js           ← Static assets
└── sniffer.db                     ← SQLite database (created on first run)
```

---

## **Prerequisites**

- PythonAnywhere free account (signup at https://www.pythonanywhere.com)
- Your Flask app files (ready to upload)
- (Optional) GitHub account for Git-based deployment

---

## **Step 1: Create PythonAnywhere Account**

1. Go to https://www.pythonanywhere.com
2. Click **"Sign up for a free account"**
3. Complete registration and verify email
4. Log in to your PythonAnywhere dashboard

---

## **Step 2: Create a Web App**

1. Click the **"Web"** tab in top menu
2. Click **"Add a new web app"**
3. Choose **"Manual configuration"** (not the template option)
4. Select **Python 3.12** (or latest available)
5. Click **"Next"**
6. You'll see a confirmation; click **"Next"** again

---

## **Step 3: Upload Your Project Files**

### **Option A: Upload ZIP File** (Recommended for first-time)

1. On your local machine, create a ZIP file of your project:
   ```powershell
   # In PowerShell, from project directory
   Compress-Archive -Path . -DestinationPath web_scraper.zip
   ```

2. On PythonAnywhere:
   - Click **"Files"** tab
   - Navigate to `/home/username/`
   - Click **"Upload a file"**
   - Select your `web_scraper.zip`
   - Click **"Upload"**

3. Extract the ZIP:
   - In file browser, right-click on `web_scraper.zip`
   - Click **"Extract here"**
   - Confirm

4. Rename folder to `mysite`:
   - Right-click extracted folder
   - Click **"Rename"**
   - Name it `mysite`

### **Option B: Clone from GitHub** (If your code is on GitHub)

In PythonAnywhere Bash console:
```bash
cd ~
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git mysite
cd mysite
```

---

## **Step 4: Configure Python Virtual Environment**

1. Go to **"Web"** tab → Select your web app
2. Scroll down to **"Virtualenv"** section
3. Click **"Add a new virtualenv"**
4. Select **Python 3.12**, click **"Next"**
5. Wait for creation (1-2 minutes)

Once created:
1. Click the virtualenv path to open console
2. Run:
   ```bash
   pip install -r /home/username/mysite/requirements.txt
   ```

---

## **Step 5: Configure WSGI File**

The WSGI file is how PythonAnywhere runs your Flask app. You need to create/edit it:

1. Go to **"Web"** tab → Select your web app
2. Under **"WSGI configuration file"**, click the filename (e.g., `/var/www/username_pythonanywhere_com_wsgi.py`)
3. **Delete all existing content** and replace with:

```python
# ============================================================================
# WSGI configuration file for PythonAnywhere
# ============================================================================
import sys
import os

# Add your project directory to the Python path
project_folder = '/home/username/mysite'
sys.path.insert(0, project_folder)

# Set environment variables (optional)
os.environ['FLASK_ENV'] = 'production'

# Import and run your Flask app
from app import app as application
```

4. **Replace `username` with your actual PythonAnywhere username** (e.g., `/home/john_doe/mysite`)
5. Click **"Save"** (Ctrl+S)

---

## **Step 6: Configure Web App Settings**

1. Go to **"Web"** tab → Select your web app
2. Verify:
   - **"Python version"**: Python 3.12
   - **"Virtualenv"**: Shows your virtualenv path
   - **"WSGI configuration file"**: Points to the file you just edited
   - **"Source code"**: `/home/username/mysite`

3. Click the green **"Reload"** button at top to apply changes
4. Wait 10-30 seconds for the server to restart

---

## **Step 7: Test Your Web App**

1. Visit your web app URL: `https://username.pythonanywhere.com`
2. Homepage should load
3. Test key routes:
   - `/` — Homepage
   - `/articles` — List articles
   - `/health` — Health check endpoint (if available)

**If you see errors:**
- Click **"Error log"** tab to see detailed errors
- Common issues:
  - Module import errors → Check `requirements.txt` is installed
  - "sniffer.db not found" → OK, it will be created on first request
  - WSGI file syntax error → Check file for Python syntax errors

---

## **Step 8: Verify Database Persistence**

1. Make a request that adds articles to the database (e.g., trigger scraper via web interface)
2. Stop and reload the web app (click "Reload" button)
3. Check if articles are still there
4. If yes, SQLite persistence works ✅

---

## **Step 9: Configure Background Scheduler**

Your app uses **APScheduler** to run the news scraper every 15 minutes. The scheduler starts automatically when the app loads.

### **Verify Scheduler is Running:**

1. Go to **"Web"** → **"Log files"** section
2. Click **"Server log"**
3. Look for this message:
   ```
   Background scheduler started (scraping every 15 minutes)
   ```

If you see it, the scheduler is running ✅

### **Monitor Scheduler Execution:**

1. Watch the **"Server log"** for:
   ```
   [Scheduler] Running background scrape...
   [Scheduler] Added X articles
   ```

2. If jobs aren't running, check **"Error log"** for issues

### **Alternative: PythonAnywhere Scheduled Tasks** (Optional)

If you prefer, you can use PythonAnywhere's native task scheduler instead:

1. Go to **"Tasks"** tab
2. Click **"Create a new scheduled task"**
3. Set time: **Daily at 12:00 AM** (or your preference)
4. Command: `curl https://username.pythonanywhere.com/api/scrape`

This calls your scraper endpoint instead of APScheduler. Choose either approach.

---

## **Step 10: Monitor Resource Usage**

### **CPU Usage** (Free tier: 100 seconds/day)

1. Go to **"Web"** → **"CPU usage"**
2. Monitor your usage:
   - Light web traffic: ~1-5 sec/day
   - Scraper jobs: ~10-30 sec per run (depends on number of sources)
   - **Expected for your app**: ~30-50 sec/day (2-3 scraper runs + web requests)

If you exceed 100 seconds:
- **Upgrade to Developer plan**: $5/month → 5000 CPU-seconds/day
- Or optimize scraper (fewer sources, longer intervals)

### **Storage** (Free tier: 512MB)

1. Go to **"Files"** tab
2. View your project folder size
3. Database will grow as articles accumulate

If database gets large (>200MB):
- Archive old articles (add cleanup logic to app)
- Or upgrade plan for more storage

---

## **Step 11: Set Up Email Alerts** (Optional)

Get notified of errors:

1. Go to **"Web"** → **"Web app settings"**
2. Find **"Error logging"** section
3. Check **"Email alerts"**
4. Errors will be emailed to you

---

## **Troubleshooting**

### **Problem: "ImportError: No module named 'app'"**

**Solution:** 
- Check WSGI file paths (username must match your PythonAnywhere username)
- Verify project uploaded to `/home/username/mysite/`

### **Problem: "sniffer.db permission denied"**

**Solution:**
- Database file should be created automatically
- If stuck, delete the file and reload the app

### **Problem: Scheduler not running**

**Solution:**
- Check **"Server log"** for `"Background scheduler started"` message
- If not there, check **"Error log"** for import/initialization errors
- Try reloading the web app again

### **Problem: Requests to external APIs fail**

**Solution:**
- PythonAnywhere has firewall restrictions
- Some external URLs might be blocked
- Check **"Error log"** for connection timeout messages
- Web scraping usually works; API calls might need whitelisting

### **Problem: Website too slow**

**Solution:**
- Check CPU usage (might be hitting limits)
- Reduce scraper frequency (change `minutes=15` in app.py to `minutes=30`)
- Cache results to reduce scraper runs

---

## **Maintenance**

### **Regular Tasks**

1. **Weekly**: Check "Error log" for issues
2. **Weekly**: Monitor CPU and storage usage
3. **Monthly**: Review article count; archive old data if needed
4. **Monthly**: Check scheduler is running (look for "[Scheduler]" messages)

### **Updating Code**

To update your app after making local changes:

1. Create a new ZIP or Git push
2. Upload/pull files to `/home/username/mysite/`
3. Click **"Reload"** button to restart the web app

---

## **Upgrading from Free Tier**

When ready to move to paid tier:

1. Go to **"Account"** → **"Billing"**
2. Choose **"Developer plan"** ($5/month):
   - 5GB storage
   - 5000 CPU-seconds/day
   - More reliable with web app always on
   - Email support

---

## **Useful Links**

- **PythonAnywhere Help**: https://help.pythonanywhere.com/
- **Python Docs**: https://docs.python.org/3/
- **Flask Docs**: https://flask.palletsprojects.com/
- **APScheduler Docs**: https://apscheduler.readthedocs.io/

---

## **Quick Reference**

| Task | Location |
|------|----------|
| View web app URL | **Web** tab |
| Reload web app | **Web** tab → Green "Reload" button |
| Check errors | **Web** → **"Error log"** tab |
| Check server logs | **Web** → **"Log files"** → **"Server log"** |
| Upload files | **Files** tab |
| View/edit files | **Files** → Browse or right-click → **"Edit"** |
| Create scheduled task | **Tasks** tab |
| Configure virtualenv | **Web** → **"Virtualenv"** section |
| Edit WSGI file | **Web** → Click WSGI filename |
| Monitor usage | **Web** → **"CPU usage"** or **"Storage"** |

---

**You're ready to deploy!** Start with Step 1 and work through each step. If you run into issues, check the troubleshooting section or visit https://help.pythonanywhere.com/
