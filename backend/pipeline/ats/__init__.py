"""ATS: score the candidate dossier against one job and say what is missing.

On demand, per job. It reads the dossier (the only source of truth about the
candidate) and the job description, and returns a structured verdict: a score,
the requirements matched and missing, strengths, gaps and concrete suggestions.
It does not touch the term-based scoring engine that highlights jobs.
"""
