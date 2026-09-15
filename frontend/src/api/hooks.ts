import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { moveInBoard, todayIso } from "../lib/board";
import { startVisitPings, visitJustStarted } from "../lib/visits";
import { api } from "./client";
import type {
  ApplicationStatus,
  ArchiveJobInput,
  Board,
  CreateJobInput,
  CreateSourceInput,
  InteractionInput,
  JobView,
  SaveProfileInput,
  SaveScoringInput,
  SecretsInput,
  UpdateApplicationInput,
  UpdateSourceInput,
} from "./types";

export const RUNNING_POLL_MS = 3000;
export const IDLE_POLL_MS = 30000;
export const ACTIVITY_HISTORY_LIMIT = 20;

export const queryKeys = {
  status: ["status"] as const,
  overview: ["overview"] as const,
  jobs: ["jobs"] as const,
  jobList: (view: JobView, page: number) => ["jobs", view, page] as const,
  jobDetail: (id: number) => ["job", id] as const,
  jobDetailAll: ["job"] as const,
  pitch: (jobId: number) => ["pitch", jobId] as const,
  sources: ["sources"] as const,
  checkRuns: (limit: number) => ["check-runs", limit] as const,
  checkRunsAll: ["check-runs"] as const,
  board: ["applications", "board"] as const,
  closedApplications: ["applications", "closed"] as const,
  applications: ["applications"] as const,
  application: (id: number) => ["application", id] as const,
  applicationAll: ["application"] as const,
  scoring: ["settings", "scoring"] as const,
  profile: ["settings", "profile"] as const,
};

export function useStatus() {
  return useQuery({
    queryKey: queryKeys.status,
    queryFn: async ({ signal }) => (await api.status(signal)).data,
    refetchInterval: (query) => (query.state.data?.isRunning ? RUNNING_POLL_MS : IDLE_POLL_MS),
    // A dashboard left in a background tab must still notice when a check ends.
    refetchIntervalInBackground: true,
  });
}

/** Whether a check is queued or running, as last reported by the status poll. */
export function useIsRunning(): boolean {
  const { data } = useStatus();
  return data?.isRunning ?? false;
}

/**
 * Refreshes every data view once a run finishes, so lists never show the
 * state from before the check.
 */
export function useRunCompletionRefresh(isRunning: boolean | undefined): void {
  const queryClient = useQueryClient();
  const previous = useRef<boolean | undefined>(undefined);

  useEffect(() => {
    if (previous.current === true && isRunning === false) {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources });
      void queryClient.invalidateQueries({ queryKey: queryKeys.checkRunsAll });
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications });
    }
    previous.current = isRunning;
  }, [isRunning, queryClient]);
}

/**
 * Tells the backend the dashboard is being looked at (docs/API-v3.md, section 5).
 * When a ping opens a new visit, "new" moved, so job lists and counts refetch.
 */
export function useVisitPings(): void {
  const queryClient = useQueryClient();

  useEffect(() => {
    let lastVisitStartedAt: string | null = null;
    const ping = () => {
      const requestedAt = Date.now();
      api
        .visit()
        .then(({ data }) => {
          const changed = lastVisitStartedAt !== null && data.visitStartedAt !== lastVisitStartedAt;
          lastVisitStartedAt = data.visitStartedAt;
          if (changed || visitJustStarted(data.visitStartedAt, requestedAt)) {
            void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
            void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
          }
        })
        .catch(() => {
          // A missed ping only delays when "new" moves; the next one retries.
        });
    };
    return startVisitPings(ping);
  }, [queryClient]);
}

export function useOverview() {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: async ({ signal }) => (await api.overview(signal)).data,
  });
}

export function useJobs(view: JobView, page: number) {
  return useQuery({
    queryKey: queryKeys.jobList(view, page),
    queryFn: async ({ signal }) => api.jobs(view, page, signal),
    // Keep the previous page on screen while paginating, but never show another view's jobs.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === view ? keepPreviousData(previous) : undefined,
  });
}

export function useJobDetail(id: number | null) {
  return useQuery({
    queryKey: queryKeys.jobDetail(id ?? 0),
    queryFn: async ({ signal }) => (await api.job(id ?? 0, signal)).data,
    enabled: id !== null,
  });
}

export function useSources(poll = false) {
  return useQuery({
    queryKey: queryKeys.sources,
    queryFn: async ({ signal }) => (await api.sources(signal)).data,
    refetchInterval: poll ? RUNNING_POLL_MS : false,
    refetchIntervalInBackground: poll,
  });
}

export function useCheckRuns(limit: number, poll = false) {
  return useQuery({
    queryKey: queryKeys.checkRuns(limit),
    queryFn: async ({ signal }) => (await api.checkRuns(limit, signal)).data,
    refetchInterval: poll ? RUNNING_POLL_MS : false,
    refetchIntervalInBackground: poll,
  });
}

/**
 * Marks job related data stale without refetching mounted lists, so a row
 * that is animating out (or back in) is not yanked away by a refetch.
 */
function markJobsStale(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.jobs, refetchType: "none" });
  void queryClient.invalidateQueries({ queryKey: queryKeys.overview, refetchType: "none" });
  void queryClient.invalidateQueries({ queryKey: queryKeys.sources, refetchType: "none" });
  void queryClient.invalidateQueries({ queryKey: queryKeys.jobDetailAll });
}

function refreshApplications(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.applications });
  void queryClient.invalidateQueries({ queryKey: queryKeys.applicationAll });
  void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
}

export function useArchiveJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: ArchiveJobInput }) => api.archiveJob(id, input),
    onSuccess: () => markJobsStale(queryClient),
  });
}

export function useRestoreJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.restoreJob(id),
    onSuccess: () => markJobsStale(queryClient),
  });
}

export function useVisitJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.visitJob(id),
    onSuccess: () => markJobsStale(queryClient),
  });
}

export function useCreateJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateJobInput) => api.createJob(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
    },
  });
}

export function useCreateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, status }: { jobId: number; status: "interest" | "applied" }) =>
      api.createApplication(jobId, status),
    onSuccess: () => {
      markJobsStale(queryClient);
      refreshApplications(queryClient);
    },
  });
}

export function useDeleteApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteApplication(id),
    onSuccess: () => {
      markJobsStale(queryClient);
      refreshApplications(queryClient);
    },
  });
}

export function useBoard() {
  return useQuery({
    queryKey: queryKeys.board,
    queryFn: async ({ signal }) => (await api.board(signal)).data,
  });
}

export function useClosedApplications() {
  return useQuery({
    queryKey: queryKeys.closedApplications,
    queryFn: async ({ signal }) => (await api.closedApplications(signal)).data,
  });
}

export function useApplicationDetail(id: number | null) {
  return useQuery({
    queryKey: queryKeys.application(id ?? 0),
    queryFn: async ({ signal }) => (await api.application(id ?? 0, signal)).data,
    enabled: id !== null,
  });
}

export function useUpdateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: UpdateApplicationInput }) => api.updateApplication(id, input),
    onSuccess: () => {
      refreshApplications(queryClient);
      markJobsStale(queryClient);
    },
  });
}

/**
 * Moves an application to another stage right away and lets the PATCH confirm
 * it. The list, its tabs and the drawer all read the board query, so they
 * follow at once; a failure rolls the board back.
 */
export function useMoveApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: number; status: ApplicationStatus }) => api.updateApplication(id, { status }),
    onMutate: async ({ id, status }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.board });
      const previous = queryClient.getQueryData<Board>(queryKeys.board);
      if (previous) queryClient.setQueryData(queryKeys.board, moveInBoard(previous, id, status));
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKeys.board, context.previous);
    },
    onSettled: () => refreshApplications(queryClient),
  });
}

/**
 * "Recebi resposta": the company answered, so the application goes to
 * screening and the timeline records the answer. Optimistic like a move.
 */
export function useReceiveAnswer() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, title }: { id: number; title: string }) => {
      await api.updateApplication(id, { status: "screening" });
      return api.createInteraction(id, { date: todayIso(), title });
    },
    onMutate: async ({ id }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.board });
      const previous = queryClient.getQueryData<Board>(queryKeys.board);
      if (previous) queryClient.setQueryData(queryKeys.board, moveInBoard(previous, id, "screening"));
      return { previous };
    },
    onError: (_error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKeys.board, context.previous);
    },
    onSettled: () => {
      refreshApplications(queryClient);
      markJobsStale(queryClient);
    },
  });
}

export function useCreateInteraction(applicationId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: InteractionInput) => api.createInteraction(applicationId, input),
    onSuccess: () => refreshApplications(queryClient),
  });
}

export function useUpdateInteraction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: Partial<InteractionInput> }) => api.updateInteraction(id, input),
    onSuccess: () => refreshApplications(queryClient),
  });
}

export function useDeleteInteraction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteInteraction(id),
    onSuccess: () => refreshApplications(queryClient),
  });
}

export function usePitch(jobId: number | null) {
  return useQuery({
    queryKey: queryKeys.pitch(jobId ?? 0),
    queryFn: async ({ signal }) => (await api.pitch(jobId ?? 0, signal)).data,
    enabled: jobId !== null,
  });
}

export function useGeneratePitch(jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (instruction: string) => api.generatePitch(jobId, instruction),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.pitch(jobId), result.data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobDetail(jobId) });
    },
  });
}

function useInvalidateSources() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.sources }),
      queryClient.invalidateQueries({ queryKey: queryKeys.overview }),
      queryClient.invalidateQueries({ queryKey: queryKeys.jobs }),
    ]);
  };
}

export function useCreateSource() {
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (input: CreateSourceInput) => api.createSource(input),
    onSuccess: invalidate,
  });
}

export function useUpdateSource() {
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: ({ id, input }: { id: number; input: UpdateSourceInput }) => api.updateSource(id, input),
    onSuccess: invalidate,
  });
}

export function useDeleteSource() {
  const invalidate = useInvalidateSources();
  return useMutation({
    mutationFn: (id: number) => api.deleteSource(id),
    onSuccess: invalidate,
  });
}

export function useScoring() {
  return useQuery({
    queryKey: queryKeys.scoring,
    queryFn: async ({ signal }) => (await api.scoring(signal)).data,
  });
}

export function useSaveScoring() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SaveScoringInput) => api.saveScoring(input),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.scoring, result.data);
      // Saving rescores every job, so every list and count may change.
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources });
    },
  });
}

export function useProfileSettings() {
  return useQuery({
    queryKey: queryKeys.profile,
    queryFn: async ({ signal }) => (await api.profile(signal)).data,
  });
}

export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SaveProfileInput) => api.saveProfile(input),
    onSuccess: (result) => queryClient.setQueryData(queryKeys.profile, result.data),
  });
}

export function useSaveSecrets() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: SecretsInput) => api.saveSecrets(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.profile });
    },
  });
}

export function useStartCheck() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.startCheck(),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.status }),
        queryClient.invalidateQueries({ queryKey: queryKeys.checkRunsAll }),
      ]);
    },
  });
}
