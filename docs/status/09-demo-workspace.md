# Clean demo workspace
Updated 5 October 2026.

Removed the SQL/ML sample chooser. Alice has a persisted fictional Alex Tan profile with a data/backend engineering background. Fresh Alice accounts receive this profile only on creation; normal startup never overwrites profile edits.

The explicit setup_demo_workspace.py maintenance command backs up Alice's profile, resumes and applications under /data/demo-backups, then configures the sample Backend Engineer application at fictional Meridian Labs with a complete reviewed resume PDF and cover letter. It is marked applied only as a demonstration; notes explicitly state that nothing was submitted.

25 named QA/sample resumes were changed to kind archived_test, excluding them from the resume library while preserving their records and exports. Unrelated user-created resumes were preserved. This is an internal recovery mechanism, not a user-facing archive/restore feature.

The setup command is intentionally explicit, local-only and does overwrite Alice's profile/application when invoked. It is not run on normal startup. The old two-resume sample script was removed. Use a disposable database for integration tests to avoid creating QA clutter again.

Verification: 15 frontend tests and production build pass, including absence of the chooser and profile save/refresh behaviour.
