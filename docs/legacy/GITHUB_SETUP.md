# GitHub Setup Guide

## ✅ Local Git Setup Complete

Your local repository is ready:
- [x] Git initialized
- [x] `.gitignore` created
- [x] Initial commit created
- [x] `main` branch created
- [x] `test` branch created

## 🔗 Connect to GitHub

### Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `student-doc-redactor`
3. Description: `Redact PII from student assessment documents`
4. Choose **Private** (recommended for security tools)
5. **DO NOT** initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

### Step 2: Connect Your Local Repo

GitHub will show you commands. Use these instead (already customized):

```bash
cd "/Users/davidarmstrong/Antigravity/redaction tool"

# Add GitHub as remote
git remote add origin https://github.com/YOUR_USERNAME/student-doc-redactor.git

# Push main branch
git push -u origin main

# Push test branch
git push -u origin test
```

**Replace `YOUR_USERNAME`** with your GitHub username!

### Step 3: Verify Setup

After pushing, check:
- https://github.com/YOUR_USERNAME/student-doc-redactor
- You should see both `main` and `test` branches

## 🚀 Workflow: Test-First Development

Follow this workflow for all changes:

### Making Changes

```bash
# Start on test branch
git checkout test

# Make your changes to files
# ... edit code ...

# Stage and commit
git add .
git commit -m "Description of changes"

# Push to GitHub test branch
git push origin test
```

### Test the Changes

Test your changes thoroughly on the `test` branch before merging to `main`.

### Promote to Main

Once tested and working:

```bash
# Switch to main
git checkout main

# Merge test into main
git merge test

# Push to GitHub
git push origin main
```

## 📋 Quick Reference

### Check Current Branch
```bash
git branch
```

### Switch Branches
```bash
git checkout test    # Switch to test
git checkout main    # Switch to main
```

### View Commit History
```bash
git log --oneline --graph --all
```

### View Status
```bash
git status
```

### Create a New Feature

```bash
git checkout test
git checkout -b feature/new-feature-name
# ... make changes ...
git add .
git commit -m "Add new feature"
git checkout test
git merge feature/new-feature-name
git push origin test
```

## ⚠️ Important Notes

### Private Repository Recommended
This tool processes sensitive student data. Keep the repository **private** unless:
- You remove all sample documents
- You ensure no real student data is ever committed
- You're sharing only the code, not the data

### .gitignore Protection
The `.gitignore` file is configured to:
- Exclude virtual environments
- Exclude generated redacted folders
- Exclude temporary files
- **NOTE**: `sample/` folder is currently included for testing

### To Remove Sample Data Later
```bash
git rm -r sample/
git commit -m "Remove sample data before making public"
```

## 🔐 Security Best Practices

1. **Never commit real student data** to GitHub
2. Keep repository **private**
3. Review `.gitignore` regularly
4. Use GitHub's security features (branch protection, secrets)
5. Consider using Git LFS for large files if needed

## 🎯 Next Steps

1. Create GitHub repository (Step 1 above)
2. Connect local repo to GitHub (Step 2 above)
3. Verify both branches are on GitHub
4. Start using test-first workflow!

---

**Current Status**: Local git ready, waiting for GitHub connection
