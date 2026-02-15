# Git Workflow Guide - Student Doc Redactor

## ✅ Setup Complete!

Your repository is now connected to GitHub:
- **Repository**: https://github.com/mrdavearms/student-doc-redactor
- **Status**: Private (secure)
- **Branches**: `main` and `test` both pushed

## 🔄 Test-First Workflow

### Standard Development Cycle

```bash
# 1. Switch to test branch
git checkout test

# 2. Make your changes
# ... edit files in VS Code, etc. ...

# 3. Check what changed
git status
git diff

# 4. Stage changes
git add .
# OR stage specific files:
# git add src/core/pii_detector.py

# 5. Commit with descriptive message
git commit -m "Brief description of changes

More detailed explanation if needed."

# 6. Push to GitHub test branch
git push origin test

# 7. TEST THOROUGHLY on the test version
# Run ./run.sh and test all features

# 8. If everything works, merge to main
git checkout main
git merge test
git push origin main
```

## 📋 Common Scenarios

### Making a Bug Fix

```bash
git checkout test
# Fix the bug in your code
git add .
git commit -m "Fix: Correct Medicare number regex pattern"
git push origin test
# Test it
git checkout main
git merge test
git push origin main
```

### Adding a New Feature

```bash
git checkout test
# Add new feature code
git add .
git commit -m "Add fuzzy name matching for better detection"
git push origin test
# Test thoroughly
git checkout main
git merge test
git push origin main
```

### Updating Documentation

```bash
git checkout test
# Update README.md or other docs
git add README.md
git commit -m "Update installation instructions"
git push origin test
git checkout main
git merge test
git push origin main
```

## 🎯 Quick Commands

### Check Current Status
```bash
git status                 # What's changed?
git branch                 # Which branch am I on?
git log --oneline -5       # Last 5 commits
```

### View Changes
```bash
git diff                   # Unstaged changes
git diff --staged          # Staged changes
git diff main..test        # Differences between branches
```

### Undo Mistakes
```bash
# Undo unstaged changes to a file
git checkout -- filename.py

# Unstage a file (but keep changes)
git reset HEAD filename.py

# Undo last commit (keep changes)
git reset --soft HEAD~1

# Discard last commit entirely (DANGEROUS!)
git reset --hard HEAD~1
```

### View Repository on GitHub
```bash
gh repo view --web
# Or just open: https://github.com/mrdavearms/student-doc-redactor
```

## 🔒 Branch Protection (Optional)

To prevent accidentally pushing to main:

```bash
# Always work on test by default
git config branch.autosetupmerge always
```

Or set up branch protection rules on GitHub:
1. Go to repository Settings → Branches
2. Add rule for `main` branch
3. Require pull request reviews
4. Require status checks to pass

## 📊 Viewing Your Work

### See All Branches on GitHub
https://github.com/mrdavearms/student-doc-redactor/branches

### See All Commits
https://github.com/mrdavearms/student-doc-redactor/commits

### Compare Branches
https://github.com/mrdavearms/student-doc-redactor/compare/main...test

## 🚨 Emergency: Revert to Last Working Version

If something breaks badly:

```bash
# See recent commits
git log --oneline -10

# Revert to a specific commit
git checkout COMMIT_HASH

# Or reset test branch to match main
git checkout test
git reset --hard main
```

## 💡 Best Practices

1. **Always test on `test` branch first**
   - Never commit directly to `main` without testing

2. **Write meaningful commit messages**
   - Good: "Fix phone number regex to handle spaces"
   - Bad: "update code"

3. **Commit often**
   - Small, focused commits are better than large ones
   - Easier to track what changed
   - Easier to undo if needed

4. **Pull before you push** (when working across devices)
   ```bash
   git pull origin test  # Get latest changes
   # ... make your changes ...
   git push origin test
   ```

5. **Keep branches in sync**
   - After merging test → main, test is now behind
   - Update test to match main:
   ```bash
   git checkout test
   git merge main  # Fast-forward to latest
   git push origin test
   ```

## 🎉 Current Workflow Summary

```
test branch (development)
    ↓ make changes
    ↓ test thoroughly
    ↓ git merge
main branch (stable)
    ↓ git push
GitHub (backup + collaboration)
```

## 🔗 Useful Links

- **Repository**: https://github.com/mrdavearms/student-doc-redactor
- **Branches**: https://github.com/mrdavearms/student-doc-redactor/branches
- **Commits**: https://github.com/mrdavearms/student-doc-redactor/commits
- **Settings**: https://github.com/mrdavearms/student-doc-redactor/settings

---

**You're all set!** Your code is safely on GitHub with proper branch structure.
