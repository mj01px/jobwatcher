import type { Application, Board, Job } from "../api/types";

export function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 42,
    sourceId: 3,
    sourceKind: "inhire",
    sourceName: "Cora",
    companyName: "Cora",
    externalId: "abc-123",
    title: "Backend Developer",
    url: "https://cora.inhire.app/vagas/abc-123/backend-developer",
    status: "active",
    archiveSource: null,
    archiveReason: null,
    archiveNote: null,
    isHighlighted: true,
    isNew: false,
    firstSeenAt: "2026-09-12T09:00:00Z",
    lastSeenAt: "2026-09-12T09:00:00Z",
    archivedAt: null,
    reopenedAt: null,
    firstVisitedAt: null,
    lastVisitedAt: null,
    location: "",
    workMode: "unknown",
    seniority: "unknown",
    publishedAt: null,
    score: 34,
    scoreTags: ["python"],
    scoreGroups: ["core"],
    application: null,
    ...overrides,
  };
}

export function makeApplication(overrides: Partial<Application> = {}): Application {
  return {
    id: 1,
    job: makeJob(),
    status: "applied",
    priority: 3,
    appliedOn: "2026-09-10",
    nextStep: "",
    nextStepOn: null,
    contact: "",
    hasReferral: false,
    notes: "",
    isOverdue: false,
    daysIdle: 0,
    interactionsCount: 0,
    createdAt: "2026-09-10T10:00:00Z",
    updatedAt: "2026-09-10T10:00:00Z",
    ...overrides,
  };
}

export function makeBoard(applications: Application[]): Board {
  const statuses = ["interest", "applied", "screening", "challenge", "interview", "offer"] as const;
  const counts: Board["counts"] = {
    interest: 0,
    applied: 0,
    screening: 0,
    challenge: 0,
    interview: 0,
    offer: 0,
    rejected: 0,
    withdrawn: 0,
  };
  for (const application of applications) counts[application.status] += 1;
  return {
    columns: statuses.map((status) => ({
      status,
      applications: applications.filter((application) => application.status === status),
    })),
    overdue: applications.filter((application) => application.isOverdue),
    counts,
  };
}
