# Git Workflow Standards

**Version:** 1.0  
**Status:** Approved  
**Owner:** BVR Group Engineering  
**Last Updated:** 2026-06-29  
**Review Cycle:** Quarterly

---

# Purpose

This document defines the Git workflow for the BVR Nexus project. It establishes a consistent branching strategy, commit process, review workflow, and release methodology to ensure stability, traceability, and maintainability throughout the software lifecycle.

---

# Branch Model

The repository follows a structured branching model.

```text
main
│
develop
│
├── epic/*
├── feature/*
├── bugfix/*
├── hotfix/*
├── docs/*
├── release/*
└── experiment/* (never merged directly)
```

## Branch Definitions

### main

- Production-ready code only
- Protected branch
- Only release merges are allowed

### develop

- Integration branch
- All completed features merge here first
- Used for integration and testing

### epic/*

Used for large initiatives spanning multiple feature branches.

Example:

```
epic/authentication
```

### feature/*

Used for implementing a single feature.

Examples:

```
feature/auth-login
feature/auth-audit
feature/rbac
```

### bugfix/*

Used for non-critical defects.

Example:

```
bugfix/redis-timeout
```

### hotfix/*

Used for urgent production fixes.

Example:

```
hotfix/jwt-validation
```

### docs/*

Used for documentation only.

Example:

```
docs/engineering-governance
```

### release/*

Used to stabilize a production release.

Example:

```
release/v1.2.0
```

### experiment/*

Used for research and prototypes.

These branches are never merged directly into long-lived branches.

---

# Branch Naming Convention

Format

```
<type>/<short-description>
```

Examples

```
feature/auth-login
feature/auth-audit
feature/rbac
bugfix/postgres-connection
hotfix/jwt-validation
docs/git-workflow
release/v1.0.0
experiment/ollama-routing
```

Use lowercase letters.

Separate words using hyphens.

Branch names should clearly describe a single objective.

---

# Feature Development Workflow

## 1. Update develop

```bash
git checkout develop
git pull origin develop
```

## 2. Create feature branch

```bash
git checkout -b feature/short-description
```

## 3. Implement feature

- Keep commits small.
- Test locally.
- Update documentation when required.

## 4. Push branch

```bash
git push -u origin feature/short-description
```

## 5. Open Pull Request

Target:

```
develop
```

---

# Commit Message Convention

BVR Nexus follows Conventional Commits.

Format

```
<type>(<scope>): <description>
```

Types

- feat
- fix
- docs
- refactor
- perf
- test
- style
- chore

Examples

```
feat(auth): add JWT validation

fix(api): resolve Redis timeout

docs(standards): add Git workflow

refactor(workers): simplify event processing
```

Rules

- One logical change per commit.
- Keep commits atomic.
- Avoid mixing unrelated work.

---

# Pull Request Process

Every Pull Request must include:

- Clear summary
- Scope of change
- Testing performed
- Deployment impact
- Rollback considerations (if applicable)

Requirements

- Target develop
- CI checks pass
- Human approval required
- Conflicts resolved before merge

---

# AI Review Process

The project uses AI-assisted development.

Workflow

1. Requirements defined.
2. Gemini implements the approved scope.
3. Human reviews generated changes.
4. High-risk changes require Claude audit.
5. Human approves final changes.
6. Human performs Git operations.

---

# High-Risk Changes

Claude review is required for changes involving:

- Authentication
- Authorization
- Security
- Database schema
- Infrastructure
- Deployment
- Docker
- Kubernetes
- Public APIs
- AI execution pipeline
- Encryption
- Secrets management

Low-risk changes include:

- Documentation
- Comments
- Formatting
- README updates

These may proceed after human review.

---

# Merge Strategy

## Feature branches

Merge into develop using:

```
Squash and Merge
```

Purpose

- Clean history
- One commit per feature

## Releases

Merge into main using:

```
Merge Commit
```

Purpose

- Preserve release history
- Maintain traceability

---

# Hotfix Workflow

1. Branch from main

```bash
git checkout main
git pull origin main
git checkout -b hotfix/short-description
```

2. Implement fix.

3. Test locally.

4. Create Pull Request targeting main.

5. Merge.

6. Backport the fix to develop.

---

# Release Workflow

1. Freeze develop.
2. Create release branch.
3. Perform integration testing.
4. Fix release issues.
5. Merge release into main.
6. Tag release.

Example

```
v1.0.0
```

7. Deploy.
8. Merge release back into develop.

---

# Rollback Strategy

If production issues occur:

1. Identify the faulty release.
2. Revert using:

```bash
git revert
```

3. Redeploy previous stable version.
4. Investigate root cause.
5. Create corrective feature or hotfix branch.

---

# Repository Protection

Rules

- Never commit directly to main.
- Never commit directly to develop.
- Every branch must have one objective.
- Keep commits atomic.

AI assistants must never:

- Execute git add
- Execute git commit
- Execute git push
- Execute git merge
- Access production infrastructure
- Access virtual machines
- Access production credentials
- Deploy software

Only a human may:

- Commit
- Push
- Merge
- Deploy
- Approve production releases

---

# Best Practices

- Keep branches short-lived.
- Rebase or update regularly.
- Delete merged branches.
- Review every Pull Request.
- Document significant architectural decisions.
- Test before every merge.
- Keep documentation synchronized with implementation.

---

# Document Maintenance

This document is a living engineering standard.

Changes require:

- Human review
- Documentation update
- Version increment
- Commit to the governance branch

---

# Revision History

| Version | Date | Description |
|----------|------------|-----------------------------|
| 1.0 | 2026-06-29 | Initial Git workflow standard |
