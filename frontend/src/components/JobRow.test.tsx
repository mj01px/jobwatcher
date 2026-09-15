import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Job } from "../api/types";
import { I18nProvider } from "../i18n/I18nProvider";
import { APPLICATION_DETECTED_EVENT } from "../lib/desktopBridge";
import { makeApplication, makeJob } from "../test/fixtures";
import { JobActionsProvider, PROMPT_DISMISSED_STORAGE_KEY } from "./JobActionsProvider";
import { JobList } from "./JobList";
import { ToastProvider } from "./Toasts";

function envelope(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, error: null, meta: { requestId: "test" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderList(jobs: Job[]) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <ToastProvider>
            <JobActionsProvider>
              <JobList jobs={jobs} />
            </JobActionsProvider>
          </ToastProvider>
        </QueryClientProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
}

function calls(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  return fetchMock.mock.calls.map(([url, init]) => ({
    url: String(url),
    method: init?.method,
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}

describe("open job, inline prompt and desktop bridge", () => {
  const fetchMock = vi.fn<typeof fetch>();
  // jsdom cannot navigate: record whether the app prevented the link, then stop it.
  let lastClickPrevented: boolean | null = null;
  const recordClick = (event: MouseEvent) => {
    lastClickPrevented = event.defaultPrevented;
    event.preventDefault();
  };

  beforeEach(() => {
    document.cookie = "csrftoken=csrf-test; path=/";
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/visit")) return envelope(makeJob());
      if (url.endsWith("/application")) return envelope(makeApplication({ id: 90 }), 201);
      return envelope(null);
    });
    vi.stubGlobal("fetch", fetchMock);
    lastClickPrevented = null;
    document.addEventListener("click", recordClick);
  });

  afterEach(() => {
    document.removeEventListener("click", recordClick);
    Reflect.deleteProperty(window, "pywebview");
    vi.unstubAllGlobals();
  });

  it("asks on the opened row, and Not now dismisses it for good", async () => {
    const user = userEvent.setup();
    const view = renderList([makeJob()]);

    expect(screen.queryByText("Did you apply?")).not.toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Open job/ }));

    expect(lastClickPrevented).toBe(false);
    expect(await screen.findByText("Did you apply?")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(calls(fetchMock)).toContainEqual({ url: "/api/v1/jobs/42/visit", method: "POST", body: undefined }));

    await user.click(screen.getByRole("button", { name: "Not now" }));
    expect(screen.queryByText("Did you apply?")).not.toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(PROMPT_DISMISSED_STORAGE_KEY) ?? "[]")).toEqual([42]);

    view.unmount();
    renderList([makeJob()]);
    expect(screen.getByText("Last opened")).toBeInTheDocument();
    expect(screen.queryByText("Did you apply?")).not.toBeInTheDocument();
  });

  it("Applied from the prompt creates the application and removes the row", async () => {
    const user = userEvent.setup();
    renderList([makeJob()]);

    await user.click(screen.getByRole("link", { name: /Open job/ }));
    const prompt = await screen.findByRole("group", { name: "Did you apply?" });
    await user.click(prompt.querySelector("button") as HTMLButtonElement);

    expect(await screen.findByText("Backend Developer moved to Applications.")).toBeInTheDocument();
    expect(calls(fetchMock)).toContainEqual({ url: "/api/v1/jobs/42/application", method: "POST", body: { status: "applied" } });
    expect(screen.queryByRole("button", { name: "Backend Developer" })).not.toBeInTheDocument();
  });

  it("never asks for a job that is already in the funnel", async () => {
    const user = userEvent.setup();
    renderList([makeJob({ application: { id: 5, status: "applied" } })]);

    await user.click(screen.getByRole("link", { name: /Open job/ }));
    expect(screen.getByText("Last opened")).toBeInTheDocument();
    expect(screen.queryByText("Did you apply?")).not.toBeInTheDocument();
  });

  it("inside the desktop app an InHire job opens through the bridge instead of the link", async () => {
    const user = userEvent.setup();
    const openJob = vi.fn(() => Promise.resolve(null));
    Reflect.set(window, "pywebview", { api: { open_job: openJob } });
    renderList([makeJob()]);

    await user.click(screen.getByRole("link", { name: /Open job/ }));

    expect(openJob).toHaveBeenCalledWith(42);
    expect(lastClickPrevented).toBe(true);
    expect(await screen.findByText("Did you apply?")).toBeInTheDocument();
    await waitFor(() => expect(calls(fetchMock).some((call) => call.url === "/api/v1/jobs/42/visit")).toBe(true));
  });

  it("other sources keep the normal link even inside the desktop app", async () => {
    const user = userEvent.setup();
    const openJob = vi.fn(() => Promise.resolve(null));
    Reflect.set(window, "pywebview", { api: { open_job: openJob } });
    renderList([makeJob({ id: 7, sourceKind: "gupy", url: "https://portal.gupy.io/job/7" })]);

    await user.click(screen.getByRole("link", { name: /Open job/ }));

    expect(openJob).not.toHaveBeenCalled();
    expect(lastClickPrevented).toBe(false);
  });

  it("falls back to a new window when the desktop call fails", async () => {
    const user = userEvent.setup();
    const windowOpen = vi.fn(() => null);
    vi.stubGlobal("open", windowOpen);
    Reflect.set(window, "pywebview", { api: { open_job: () => Promise.reject(new Error("closed")) } });
    renderList([makeJob()]);

    await user.click(screen.getByRole("link", { name: /Open job/ }));

    await waitFor(() =>
      expect(windowOpen).toHaveBeenCalledWith(
        "https://cora.inhire.app/vagas/abc-123/backend-developer",
        "_blank",
        "noopener,noreferrer",
      ),
    );
  });

  it("an application detected by the desktop app removes the row and shows a toast", async () => {
    renderList([makeJob(), makeJob({ id: 43, title: "Frontend Developer", externalId: "def" })]);

    act(() => {
      window.dispatchEvent(
        new CustomEvent(APPLICATION_DETECTED_EVENT, { detail: { jobId: 42, applicationId: 9, changed: true } }),
      );
    });

    expect(await screen.findByText("Application recorded. The job moved to Applications.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: "Backend Developer" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Frontend Developer" })).toBeInTheDocument();
  });

  it("ignores malformed detection events", () => {
    renderList([makeJob()]);

    act(() => {
      window.dispatchEvent(new CustomEvent(APPLICATION_DETECTED_EVENT, { detail: { jobId: "42" } }));
    });

    expect(screen.queryByText("Application recorded. The job moved to Applications.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backend Developer" })).toBeInTheDocument();
  });
});
