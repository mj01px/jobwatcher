import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import {
  queryKeys,
  useArchiveJob,
  useCreateApplication,
  useDeleteApplication,
  useRestoreJob,
  useVisitJob,
} from "../api/hooks";
import type { Job, ManualArchiveReason } from "../api/types";
import { useI18n } from "../i18n/I18nProvider";
import { APPLICATION_DETECTED_EVENT, getDesktopBridge, isApplicationDetectedDetail } from "../lib/desktopBridge";
import { readStorage, writeStorage } from "../lib/storage";
import { ArchiveModal } from "./ArchiveModal";
import { JobDetailDrawer } from "./JobDetailDrawer";
import { useToasts } from "./Toasts";

export const LAST_OPENED_STORAGE_KEY = "job-watcher-last-opened";
export const PROMPT_DISMISSED_STORAGE_KEY = "job-watcher-apply-prompt-dismissed";
/** Only recent dismissals matter: the prompt follows the last opened job. */
const PROMPT_DISMISSED_LIMIT = 200;

export type FunnelEntry = "applied" | "interest";

/** A mounted job list listens so it can animate rows out and back in. */
export interface RowListener {
  remove: (jobId: number) => void;
  restore: (jobId: number) => void;
}

interface JobActionsValue {
  lastOpenedId: string | null;
  /**
   * Records the visit and the last opened job. Returns true when the desktop app
   * took over opening it, so the caller must not follow the link.
   */
  openJob: (job: Job) => boolean;
  /** Creates the application and slides the row out, with Undo. */
  moveToFunnel: (job: Job, status: FunnelEntry) => Promise<void>;
  openArchiveModal: (job: Job) => void;
  restoreJob: (job: Job) => Promise<void>;
  openJobDetail: (job: Job) => void;
  isPromptDismissed: (jobId: number) => boolean;
  dismissPrompt: (jobId: number) => void;
  subscribeRows: (listener: RowListener) => () => void;
}

const JobActionsContext = createContext<JobActionsValue | null>(null);

function readDismissed(): number[] {
  const raw = readStorage(PROMPT_DISMISSED_STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((item): item is number => Number.isInteger(item)) : [];
  } catch {
    return [];
  }
}

export function JobActionsProvider({ children }: { children: ReactNode }) {
  const { t } = useI18n();
  const { showToast } = useToasts();
  const queryClient = useQueryClient();
  const { mutateAsync: archiveAsync } = useArchiveJob();
  const { mutateAsync: restoreAsync } = useRestoreJob();
  const { mutateAsync: createApplicationAsync } = useCreateApplication();
  const { mutateAsync: deleteApplicationAsync } = useDeleteApplication();
  const { mutate: visit } = useVisitJob();

  const listeners = useRef(new Set<RowListener>());
  const [lastOpenedId, setLastOpenedId] = useState<string | null>(() => readStorage(LAST_OPENED_STORAGE_KEY));
  const [dismissed, setDismissed] = useState<number[]>(readDismissed);
  const [archiveJob, setArchiveJob] = useState<Job | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [detailJob, setDetailJob] = useState<Job | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const subscribeRows = useCallback((listener: RowListener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  const notifyRemove = useCallback((jobId: number) => {
    listeners.current.forEach((listener) => listener.remove(jobId));
  }, []);

  const notifyRestore = useCallback((jobId: number) => {
    listeners.current.forEach((listener) => listener.restore(jobId));
  }, []);

  const moveToFunnel = useCallback(
    async (job: Job, status: FunnelEntry) => {
      let applicationId: number;
      try {
        const result = await createApplicationAsync({ jobId: job.id, status });
        applicationId = result.data.id;
      } catch (error) {
        showToast(t("toast.actionFailed"));
        throw error;
      }
      notifyRemove(job.id);
      const message = t(status === "applied" ? "toast.applied" : "toast.interested", { title: job.title });
      showToast(message, {
        onUndo: async () => {
          await deleteApplicationAsync(applicationId);
        },
        onUndoSuccess: () => notifyRestore(job.id),
      });
    },
    [createApplicationAsync, deleteApplicationAsync, notifyRemove, notifyRestore, showToast, t],
  );

  const openArchiveModal = useCallback((job: Job) => {
    setArchiveJob(job);
    setArchiveOpen(true);
  }, []);

  const confirmArchive = useCallback(
    async (reason: ManualArchiveReason, note: string) => {
      if (!archiveJob) return;
      const job = archiveJob;
      await archiveAsync({ id: job.id, input: { reason, note } });
      setArchiveOpen(false);
      notifyRemove(job.id);
      showToast(t("toast.archived", { title: job.title }), {
        onUndo: async () => {
          await restoreAsync(job.id);
        },
        onUndoSuccess: () => notifyRestore(job.id),
      });
    },
    [archiveAsync, archiveJob, notifyRemove, notifyRestore, restoreAsync, showToast, t],
  );

  const openJob = useCallback(
    (job: Job) => {
      const id = String(job.id);
      writeStorage(LAST_OPENED_STORAGE_KEY, id);
      setLastOpenedId(id);
      visit(job.id);

      // Inside the desktop app an InHire job opens in its own window, where the
      // application submit is detected and recorded automatically.
      const bridge = job.sourceKind === "inhire" ? getDesktopBridge() : null;
      if (!bridge) return false;
      bridge.openJob(job.id).catch(() => {
        window.open(job.url, "_blank", "noopener,noreferrer");
      });
      return true;
    },
    [visit],
  );

  const isPromptDismissed = useCallback((jobId: number) => dismissed.includes(jobId), [dismissed]);

  const dismissPrompt = useCallback((jobId: number) => {
    setDismissed((current) => {
      if (current.includes(jobId)) return current;
      const next = [...current, jobId].slice(-PROMPT_DISMISSED_LIMIT);
      writeStorage(PROMPT_DISMISSED_STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const restoreJob = useCallback(
    async (job: Job) => {
      await restoreAsync(job.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.jobs }),
        queryClient.invalidateQueries({ queryKey: queryKeys.overview }),
      ]);
    },
    [queryClient, restoreAsync],
  );

  const openJobDetail = useCallback((job: Job) => {
    setDetailJob(job);
    setDetailOpen(true);
  }, []);

  // The desktop app announces applications it detected in its job window.
  useEffect(() => {
    const handleDetected = (event: Event) => {
      if (!(event instanceof CustomEvent) || !isApplicationDetectedDetail(event.detail)) return;
      notifyRemove(event.detail.jobId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobs });
      void queryClient.invalidateQueries({ queryKey: queryKeys.overview });
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications });
      void queryClient.invalidateQueries({ queryKey: queryKeys.applicationAll });
      void queryClient.invalidateQueries({ queryKey: queryKeys.jobDetailAll });
      void queryClient.invalidateQueries({ queryKey: queryKeys.sources });
      showToast(t("toast.applicationDetected"));
    };
    window.addEventListener(APPLICATION_DETECTED_EVENT, handleDetected);
    return () => window.removeEventListener(APPLICATION_DETECTED_EVENT, handleDetected);
  }, [notifyRemove, queryClient, showToast, t]);

  const closeArchive = useCallback(() => setArchiveOpen(false), []);
  const closeDetail = useCallback(() => setDetailOpen(false), []);

  const value = useMemo<JobActionsValue>(
    () => ({
      lastOpenedId,
      openJob,
      moveToFunnel,
      openArchiveModal,
      restoreJob,
      openJobDetail,
      isPromptDismissed,
      dismissPrompt,
      subscribeRows,
    }),
    [
      lastOpenedId,
      openJob,
      moveToFunnel,
      openArchiveModal,
      restoreJob,
      openJobDetail,
      isPromptDismissed,
      dismissPrompt,
      subscribeRows,
    ],
  );

  return (
    <JobActionsContext.Provider value={value}>
      {children}
      <ArchiveModal job={archiveJob} open={archiveOpen} onClose={closeArchive} onConfirm={confirmArchive} />
      <JobDetailDrawer job={detailJob} open={detailOpen} onClose={closeDetail} />
    </JobActionsContext.Provider>
  );
}

export function useJobActions(): JobActionsValue {
  const value = useContext(JobActionsContext);
  if (!value) throw new Error("useJobActions must be used inside JobActionsProvider");
  return value;
}
