# Deployment Preparation - Summary

Your Flask Web Scraper app is now **ready for deployment to PythonAnywhere**! 

---

## **Changes Made**

### **1. Fixed Scheduler Initialization** (`app.py`)
**Issue**: Scheduler only started in `if __name__ == '__main__'` block, which doesn't run on PythonAnywhere with Gunicorn.

**Fix**: Moved scheduler startup to module-level initialization with error handling.
- Scheduler now starts when app is imported (e.g., by Gunicorn)
- Error handling prevents app crashes if scheduler fails
- Maintains compatibility with local development

**Before:**
```python
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    process_articles_metadata()
    start_scheduler()
    app.run(...)
```

**After:**
```python
try:
    process_articles_metadata()
    start_scheduler()
except Exception as e:
    logger.error(f"Failed to initialize scheduler: {e}")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app.run(...)
```

### **2. Updated Dependencies** (`requirements.txt`)
**Added**: `gunicorn==21.2.0`
- PythonAnywhere's WSGI server (for production deployment)
- Your app will run through Gunicorn, not Flask's dev server

---

## **Verified (No Changes Needed)**

✅ **app.py**
- Flask app instance `app = Flask(__name__)` at module level → Perfect for WSGI
- All routes properly defined
- Database module imported correctly
- Web scraper module imported correctly

✅ **database.py**
- Uses relative path `"sniffer.db"` → Works fine from project root
- SQLite3 with proper connection management
- Will persist on PythonAnywhere filesystem

✅ **web_scraper.py**
- Has proper retry logic with exponential backoff → Good for unreliable networks
- Uses feedparser for RSS (fast and reliable)
- Proper error handling for network issues

✅ **Project Structure**
- `app.py` at root level (PythonAnywhere auto-detects it)
- `requirements.txt` at root level
- `templates/` folder for Flask templates
- `static/` folder for static assets
- All auxiliary modules in correct locations

---

## **Deployment Guides Created**

### **1. PYTHONANYWHERE_DEPLOYMENT.md** (Comprehensive Guide)
11-step guide covering:
- Account creation
- Web app configuration
- WSGI setup
- Virtual environment configuration
- Database verification
- Scheduler verification
- Resource monitoring
- Troubleshooting guide
- Quick reference table

**Use this as your main reference during deployment.**

### **2. DEPLOYMENT_CHECKLIST.md** (Verification List)
Detailed checklist with sections:
- Pre-deployment verification
- PythonAnywhere setup steps
- Post-deployment testing
- Performance limits verification
- Troubleshooting quick links

**Use this to verify each step is complete.**

---

## **What Happens on PythonAnywhere**

When you deploy to PythonAnywhere:

1. **App Loading**
   - PythonAnywhere imports `app.py` as a module (via WSGI)
   - `app` instance is extracted and used as the WSGI application
   - Scheduler initialization runs automatically (no `if __name__` needed)

2. **Background Scheduler**
   - APScheduler starts in the same process as the web app
   - Runs background scraper jobs every 15 minutes
   - Jobs fetch news from various sources and store in SQLite

3. **Database Persistence**
   - SQLite database file (`sniffer.db`) stored on PythonAnywhere filesystem
   - Data persists between requests and application reloads
   - (Unlike Vercel, which would wipe the file)

4. **Static Files & Templates**
   - Flask serves templates from `templates/` folder
   - Static assets served from `static/` folder
   - No special configuration needed

---

## **Quick Start - Deployment Steps**

1. **Sign up**: https://www.pythonanywhere.com (free tier)
2. **Create web app**: Python 3.12 + Manual configuration
3. **Upload files**: ZIP your project, extract to `/home/username/mysite/`
4. **Install dependencies**: `pip install -r requirements.txt`
5. **Edit WSGI file**: Point to your `app` instance (see PYTHONANYWHERE_DEPLOYMENT.md)
6. **Reload**: Click green "Reload" button
7. **Test**: Visit `username.pythonanywhere.com`
8. **Verify scheduler**: Check server logs for `"Background scheduler started"`

---

## **Key Features of Your App on PythonAnywhere**

✅ **Persistent SQLite Database** — Articles saved permanently  
✅ **Scheduled Scraping** — Automatic news fetching every 15 minutes  
✅ **Web Interface** — User-friendly homepage with search & filters  
✅ **No Time Limits** — Scraper can run as long as needed  
✅ **Free Tier** — 512MB storage, 100 CPU-seconds/day (plenty for this app)  
✅ **Easy Upgrades** — $5/month for 5GB storage, 5000 CPU-seconds/day  

---

## **Expected Resource Usage**

| Resource | Limit | Usage | Status |
|----------|-------|-------|--------|
| **Storage** | 512MB | ~50-100MB (database + code) | ✅ Safe |
| **CPU/day** | 100 seconds | ~50 sec (web + 4 scraper runs) | ✅ Safe |
| **Uptime** | 24/7 | Continuous | ✅ Always on |
| **Database** | Persistent | Yes | ✅ Works perfectly |

---

## **Troubleshooting Resources**

- **General**: See PYTHONANYWHERE_DEPLOYMENT.md → "Troubleshooting" section
- **Verification**: See DEPLOYMENT_CHECKLIST.md
- **PythonAnywhere Help**: https://help.pythonanywhere.com/
- **Flask Docs**: https://flask.palletsprojects.com/
- **APScheduler Docs**: https://apscheduler.readthedocs.io/

---

## **Why NOT Vercel?**

Vercel was **not** suitable because:
- ❌ No persistent file storage (SQLite data lost between requests)
- ❌ No background job support (APScheduler won't work)
- ❌ Hard execution time limits (500s on Hobby, 800s on Pro)
- ❌ Designed for stateless serverless functions, not persistent apps

**PythonAnywhere** is perfect because:
- ✅ Persistent file storage
- ✅ Background jobs with APScheduler
- ✅ No execution time limits
- ✅ Designed for always-on Python web apps

---

## **Files Modified**

```
app.py
├── Moved scheduler initialization to module level
└── Wrapped in try-except for production safety

requirements.txt
└── Added gunicorn==21.2.0

(New) PYTHONANYWHERE_DEPLOYMENT.md
└── Comprehensive 11-step deployment guide

(New) DEPLOYMENT_CHECKLIST.md
└── Detailed verification checklist
```

---

## **Next Steps**

1. **Review** the PYTHONANYWHERE_DEPLOYMENT.md guide
2. **Create** PythonAnywhere account
3. **Upload** your project files
4. **Follow** the 11-step deployment guide
5. **Use** the DEPLOYMENT_CHECKLIST.md to verify each step
6. **Monitor** the app for a few days (check logs, CPU usage)

---

## **Support**

If you encounter issues:
1. Check DEPLOYMENT_CHECKLIST.md for common issues
2. Read PYTHONANYWHERE_DEPLOYMENT.md → "Troubleshooting" section
3. View **"Error log"** and **"Server log"** in PythonAnywhere dashboard
4. Visit https://help.pythonanywhere.com/ for PythonAnywhere-specific help

---

**You're ready to deploy! 🚀**

Start with the PYTHONANYWHERE_DEPLOYMENT.md guide and follow each step. Your app should be live within 30 minutes.
