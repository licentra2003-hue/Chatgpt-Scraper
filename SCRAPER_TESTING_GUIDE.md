# ChatGPT Scraper Testing & Debugging Guide

This document outlines the systematic steps for testing and debugging the scraper system, covering both Docker-containerized execution and local host execution.

---

## 🏗️ 1. Docker-Based Testing

This is the primary method for testing the full production-like environment (Playwright on Ubuntu Jammy).

### Step A: Rebuild and Restart
Every time you modify the `scraper.py` or `main.py` code, you must rebuild the image to sync changes.
```powershell
# Rebuild the worker and recreate the container
docker-compose build worker && docker-compose up -d --force-recreate worker
```

### Step B: Trigger a Scrape Job
Use the `simple_api_test.py` script to send a POST request to the API container.
```powershell
python simple_api_test.py
```

### Step C: Track Logs in Real-Time
To see exactly what the scraper is doing (mouse moves, typing, waiting), follow the worker logs.
```powershell
# Continuous tracking (-f for follow, --tail for last N lines)
docker logs -f scraper-system-worker-1 --tail 50
```

### Step D: Extract Debug Artifacts
If the scraper fails, it saves a `debug_failed.png` inside the container. Extract it to your host to see the block screen.
```powershell
# Copy the last failure screenshot from container to host
docker cp scraper-system-worker-1:/app/debug_failed.png latest_block.png
```

---

## 💻 2. Local (Direct Windows) Testing

Used to verify if blocks are environment-specific (Docker/Linux vs. Windows).

### Step A: Start the Local API Server
Run this in a dedicated terminal. It uses your local Chrome/Playwright installation.
```powershell
python local_api_server.py
```

### Step B: Run the Test Client
In a second terminal, send the query to the local server (port 3005).
```powershell
python local_test.py
```

### Step C: Monitor Local Artifacts
Local screenshots are saved directly to the project root:
- Check `debug_failed.png` in the folder.
- Check terminal output for real-time progress.

---

## 🛠️ Debugging Command Reference

### Docker Management
| Goal | Command |
| :--- | :--- |
| **Check Container Status** | `docker ps` |
| **Stop All Services** | `docker-compose down` |
| **View API Logs** | `docker logs -f scraper-api-new` |
| **List Files in Worker** | `docker exec scraper-system-worker-1 ls -la /app` |
| **Find PNGs in Container** | `docker exec scraper-system-worker-1 find /app -name "*.png"` |
| **Check Worker Health** | `docker inspect scraper-system-worker-1` |

### Environment Validation
Before testing, ensure your `.env` is correctly configured:
- `PROXY_SERVER`: Should be active for Cloudflare bypass.
- `HEADLESS`: `True` for Docker, can be `False` for local debugging to see the browser.

---

## 🚨 Common Block States (What to look for)

1. **Shadow Ban / Infinite Loading**: Characterized by a pulsing black dot in the response div but zero text streaming.
2. **Soft Block**: A red toast message saying *"Something went wrong"* or a visible "Retry" button.
3. **Cloudflare Challenge**: Stuck on a page titled *"Just a moment..."* with a checkbox. Usually solved via Proxy or improved `stealth_js`.
