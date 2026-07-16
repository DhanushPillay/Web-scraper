# PythonAnywhere Deployment Checklist

Use this checklist to verify your deployment is complete and working correctly.

---

## **Pre-Deployment (Local)**

- [ ] Flask app has `app = Flask(__name__)` at module level (for WSGI)
- [ ] `requirements.txt` includes all dependencies
- [ ] `app.py` scheduler initialization is outside `if __name__ == '__main__'` block (✅ already done)
- [ ] Database file path uses relative path `"sniffer.db"` (✅ already done)
- [ ] All template files in `templates/` folder
- [ ] All static files in `static/` folder
- [ ] Project tested locally with `python app.py`

---

## **PythonAnywhere Setup**

### **Account & Basics**
- [ ] PythonAnywhere account created and verified
- [ ] Email confirmed
- [ ] Logged into dashboard

### **Web App Creation**
- [ ] Web app created with Python 3.12
- [ ] Web app shows in "Web" tab
- [ ] Web app URL generated (e.g., `username.pythonanywhere.com`)

### **File Upload**
- [ ] Project ZIP created with all files
- [ ] ZIP uploaded to PythonAnywhere
- [ ] ZIP extracted to `/home/username/mysite/`
- [ ] File structure verified:
  - [ ] `app.py` exists
  - [ ] `requirements.txt` exists
  - [ ] `database.py` exists
  - [ ] `web_scraper.py` exists
  - [ ] `templates/` folder exists
  - [ ] `static/` folder exists

### **Virtual Environment**
- [ ] Virtualenv created for Python 3.12
- [ ] Virtualenv path shown in "Virtualenv" section
- [ ] Dependencies installed: `pip install -r requirements.txt`
- [ ] All packages installed without errors:
  - [ ] flask
  - [ ] requests
  - [ ] beautifulsoup4
  - [ ] newspaper3k
  - [ ] nltk
  - [ ] feedparser
  - [ ] apscheduler
  - [ ] gunicorn

### **WSGI Configuration**
- [ ] WSGI file (`/var/www/username_pythonanywhere_com_wsgi.py`) edited
- [ ] WSGI file contains:
  - [ ] `import sys`
  - [ ] `sys.path.insert(0, '/home/username/mysite')`
  - [ ] `from app import app as application`
- [ ] WSGI file saved (Ctrl+S)
- [ ] Username replaced with actual PythonAnywhere username

### **Web App Settings**
- [ ] Python version set to 3.12
- [ ] Virtualenv path correct
- [ ] WSGI file path correct
- [ ] Source code path set to `/home/username/mysite`

---

## **Deployment**

- [ ] **"Reload"** button clicked (green button at top of "Web" tab)
- [ ] Waited 10-30 seconds for server restart
- [ ] No immediate 500 errors

---

## **Post-Deployment Testing**

### **Basic Functionality**
- [ ] Web app URL accessible: `https://username.pythonanywhere.com`
- [ ] Homepage loads (GET `/`)
- [ ] No 404 errors for static files (CSS, JS, images)
- [ ] API endpoints respond:
  - [ ] GET `/articles` returns JSON
  - [ ] GET `/health` returns status (if available)

### **Database**
- [ ] Make a write request (trigger article scrape or add data)
- [ ] Verify database file created (`sniffer.db`)
- [ ] Stop and reload web app
- [ ] Data persists after reload ✅ **(CRITICAL: proves SQLite works)**

### **Scheduler**
- [ ] Check **"Server log"** for message: `"Background scheduler started"`
- [ ] Wait 15 minutes or check for scraper execution in logs
- [ ] Look for `[Scheduler] Running background scrape...` messages
- [ ] Verify articles added to database by scheduler

### **Errors**
- [ ] No error messages in **"Error log"** tab
- [ ] No 500 errors in access logs
- [ ] Check **"Server log"** for warnings or missing imports

---

## **Performance & Limits**

### **Resource Monitoring**
- [ ] CPU usage under 100 seconds/day (free tier limit)
- [ ] Storage under 512MB (free tier limit)
- [ ] Check **"CPU usage"** graph on "Web" tab
- [ ] Monitor storage in **"Files"** tab

### **Expected Usage**
- [ ] Baseline web traffic: 1-5 CPU-seconds/day
- [ ] Each scraper run: 5-15 CPU-seconds (depending on sources)
- [ ] 4 scraper runs/day (every 15 min): ~40 CPU-seconds/day
- [ ] Total estimated: 45-50 CPU-seconds/day ✅ (under 100 limit)

---

## **Optional Enhancements**

- [ ] Email alerts configured in **"Web"** → **"Web app settings"**
- [ ] Static site header/footer configured
- [ ] Error logging enhanced (custom error pages)
- [ ] Database backup strategy planned

---

## **Verification Summary**

Before considering deployment complete, verify:

1. ✅ **Flask app loads** → Homepage renders
2. ✅ **Routes work** → API endpoints respond
3. ✅ **Database persists** → Write, reload, data still there
4. ✅ **Scheduler running** → "[Scheduler]" messages in logs
5. ✅ **Within limits** → CPU < 100 sec/day, Storage < 512MB
6. ✅ **No errors** → Error log is clean or only info-level

---

## **Troubleshooting Quick Links**

- **Web app not loading**: Check WSGI file, verify import works
- **500 errors**: Check "Error log" for Python exceptions
- **Scheduler not running**: Check "Server log" for import/initialization errors
- **Database missing**: Normal; created on first write
- **Slow performance**: Check CPU usage, reduce scraper frequency if needed
- **Storage full**: Archive old articles or upgrade plan

---

**When all items are checked, your deployment is complete!** 🎉

Next: Monitor the app for a few days to ensure stability and usage is within free tier limits.
