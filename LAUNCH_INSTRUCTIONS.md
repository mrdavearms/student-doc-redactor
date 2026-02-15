# 🚀 How to Launch Student Doc Redactor

## ✅ Quick Launch (Recommended)

Open Terminal and run:

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
./run.sh
```

Your browser will automatically open to the app.

## Alternative: Manual Launch

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"
source venv/bin/activate
streamlit run app.py
```

## What You'll See

1. Terminal will show:
   ```
   You can now view your Streamlit app in your browser.

   Local URL: http://localhost:8501
   Network URL: http://192.168.x.x:8501
   ```

2. Your default browser will open automatically to `http://localhost:8501`

3. You'll see the Student Doc Redactor welcome screen

## First Time Testing

Try the app with the sample data:

1. **Folder path**: `/Users/davidarmstrong/Antigravity/redaction tool/sample`
2. **Student name**: `Joe Bloggs`
3. **Parent names**: _(leave blank or add if you know them)_
4. Click **Start Processing**

## Stopping the App

In Terminal, press: **Ctrl + C**

## Troubleshooting

### "Address already in use"
Another Streamlit app is running on port 8501. Either:
- Stop the other app
- Or Streamlit will automatically use port 8502 (check Terminal output)

### Browser doesn't open
Manually go to: http://localhost:8501

### "Permission denied: run.sh"
Make it executable:
```bash
chmod +x run.sh
```

## Ready to Test! 🎯

The application is fully built and ready to test with your sample documents.
