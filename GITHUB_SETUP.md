# GitHub Repository Setup Guide

This guide will help you check this code into GitHub as a portfolio project.

## Pre-Commit Checklist

✅ **Already Done:**
- `.gitignore` file created to exclude sensitive files
- No hardcoded secrets found in code (all use environment variables)
- `env.example` file exists for configuration reference

## Files That Should NOT Be Checked In

The following will be automatically excluded by `.gitignore`:

- ❌ `.venv/` directory (virtual environment)
- ❌ `__pycache__/` directories (Python bytecode)
- ❌ `*.log` files (log files)
- ❌ `.env` files (environment variables with secrets)
- ❌ `*.pyc` files (compiled Python)
- ❌ IDE files (`.vscode/`, `.idea/`, etc.)
- ❌ OS files (`.DS_Store`, etc.)

## Files That WILL Be Checked In

✅ **Source Code:**
- `test-project/src/main.py` (main application)
- `test-project/src/bootstrap_user.py` (user creation script)
- `test-project/src/pyrit_test_nexus.py` (PyRIT integration)
- `pyrit_test_nexus.py` (root level PyRIT test)
- `test-project/src/requirements.txt` (dependencies)

✅ **Documentation:**
- `README.md` (main documentation)
- `ARCHITECTURE.md` (architecture documentation)
- `test-project/AUTHENTICATION.md` (authentication guide)
- `test-project/env.example` (environment variable template)

✅ **Configuration:**
- `.gitignore` (Git ignore rules)
- `test-project/requirements.txt` (project requirements)

## Step-by-Step Instructions

### 1. Initialize Git Repository (if not already done)

```bash
cd /Users/mehdeep/Repositories/FastAPI
git init
```

### 2. Verify .gitignore is Working

```bash
# Check what files Git will track (should NOT include .venv, logs, etc.)
git status

# If you see .venv or log files, verify .gitignore is in place
ls -la .gitignore
```

### 3. Stage Files for Commit

```bash
# Add all files (respecting .gitignore)
git add .

# Review what will be committed
git status
```

**Important:** Verify that you don't see:
- `.venv/` directory
- `*.log` files
- `.env` files
- `__pycache__/` directories

### 4. Create Initial Commit

```bash
git commit -m "Initial commit: Nexus AI Gateway - FastAPI security gateway for Azure OpenAI

- PII detection and anonymization with Presidio
- Content safety filtering with Azure Content Safety
- API key authentication with user management
- Rate limiting and cost tracking
- Comprehensive metrics and logging
- PyRIT integration for security testing"
```

### 5. Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `nexus-ai-gateway` (or your preferred name)
3. Description: Use the description provided in `GITHUB_DESCRIPTION.txt`
4. Set to **Public** (for portfolio)
5. **DO NOT** initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

### 6. Connect Local Repository to GitHub

```bash
# Add the remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/nexus-ai-gateway.git

# Or if using SSH:
# git remote add origin git@github.com:YOUR_USERNAME/nexus-ai-gateway.git
```

### 7. Push to GitHub

```bash
# Rename default branch to main (if needed)
git branch -M main

# Push to GitHub
git push -u origin main
```

### 8. Verify on GitHub

1. Visit your repository on GitHub
2. Verify all files are present
3. Verify `.venv/`, logs, and other excluded files are NOT visible
4. Check that the README displays correctly

## Post-Setup Recommendations

### Add Repository Topics/Tags

On GitHub, add these topics to help with discoverability:
- `fastapi`
- `azure-openai`
- `security`
- `pii-detection`
- `api-gateway`
- `python`
- `portfolio`

### Update README if Needed

Consider adding:
- Screenshots or diagrams (if you have them)
- Live demo link (if deployed)
- License information
- Contact information

### Security Reminder

⚠️ **IMPORTANT:** Before pushing, double-check:
- No `.env` files are committed
- No API keys or secrets are hardcoded
- No real credentials in any files
- All sensitive data uses environment variables

You can verify with:
```bash
# Search for potential secrets (should return nothing or only examples)
grep -r "sk-" . --exclude-dir=.venv --exclude-dir=.git
grep -r "AZURE.*KEY" . --exclude-dir=.venv --exclude-dir=.git
```

## Troubleshooting

### If .venv files are showing up:

```bash
# Remove from Git cache
git rm -r --cached test-project/.venv/

# Verify .gitignore is correct
cat .gitignore | grep venv

# Re-add files
git add .
git status  # Should not show .venv now
```

### If you accidentally committed secrets:

1. **DO NOT** just delete and recommit (secrets remain in Git history)
2. Use `git filter-branch` or BFG Repo-Cleaner to remove from history
3. Rotate all exposed credentials immediately
4. Consider making the repo private until cleaned

## Next Steps

After pushing to GitHub:
1. Add a license file (MIT, Apache 2.0, etc.)
2. Enable GitHub Actions for CI/CD (if desired)
3. Add GitHub Pages for documentation (optional)
4. Star your own repo to add it to your starred list
5. Share on LinkedIn/Twitter to showcase your work!

