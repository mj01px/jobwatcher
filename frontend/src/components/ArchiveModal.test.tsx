import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "../i18n/I18nProvider";
import { makeApplication, makeJob } from "../test/fixtures";
import { JobActionsProvider } from "./JobActionsProvider";
import { JobList } from "./JobList";
import { ToastProvider } from "./Toasts";

const job = makeJob();

function envelope(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, error: null, meta: { requestId: "test" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function renderList() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <ToastProvider>
            <JobActionsProvider>
              <JobList jobs={[job]} />
            </JobActionsProvider>
          </ToastProvider>
        </QueryClientProvider>
      </I18nProvider>
    </MemoryRouter>,
  );
}

function requestOf(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>, index: number) {
  const [url, init] = fetchMock.mock.calls[index] ?? [];
  return { url: String(url), method: init?.method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
}

describe("job row actions", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    document.cookie = "csrftoken=csrf-test; path=/";
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows the score, source kind and facts", () => {
    fetchMock.mockImplementation(async () => envelope(null));
    renderList();

    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.getByText("InHire")).toBeInTheDocument();
  });

  it("requires a reason, archives with the note, and restores on undo", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/archive")) return envelope({ ...job, status: "archived", archiveReason: "remote" });
      if (url.endsWith("/restore")) return envelope(job);
      return envelope(null);
    });

    renderList();
    await user.click(screen.getByRole("button", { name: "Archive" }));

    const dialog = await screen.findByRole("dialog", { name: "Archive job" });
    expect(within(dialog).getByText("Backend Developer · Cora")).toBeInTheDocument();
    // Applied moved to the funnel, so it is no longer an archive reason.
    expect(within(dialog).queryByRole("radio", { name: "Already applied" })).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Confirm archive" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("Choose a reason to continue.");
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("radio", { name: "Remote role" }));
    expect(within(dialog).getByRole("radio", { name: "Remote role" }).closest("label")).toHaveClass("is-selected");
    await user.type(within(dialog).getByRole("textbox"), "Prefer hybrid");
    await user.click(within(dialog).getByRole("button", { name: "Confirm archive" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Backend Developer" })).not.toBeInTheDocument());
    expect(requestOf(fetchMock, 0)).toEqual({
      url: "/api/v1/jobs/42/archive",
      method: "POST",
      body: { reason: "remote", note: "Prefer hybrid" },
    });
    expect((fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>)["X-CSRFToken"]).toBe("csrf-test");

    expect(screen.getByText("Backend Developer archived.")).toBeInTheDocument();
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));

    expect(await screen.findByRole("button", { name: "Backend Developer" })).toBeInTheDocument();
    expect(requestOf(fetchMock, 1).url).toBe("/api/v1/jobs/42/restore");
    await waitFor(() => expect(screen.queryByText("Backend Developer archived.")).not.toBeInTheDocument());
  });

  it("shows an error and keeps the modal open when archiving fails", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ data: null, error: { code: "INTERNAL_ERROR", message: "boom" }, meta: { requestId: "x" } }),
        { status: 500, headers: { "Content-Type": "application/json" } },
      ),
    );

    renderList();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog", { name: "Archive job" });
    await user.click(within(dialog).getByRole("radio", { name: "Other" }));
    await user.click(within(dialog).getByRole("button", { name: "Confirm archive" }));

    expect(await within(dialog).findByText("Something went wrong. Try again.")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Confirm archive" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Backend Developer" })).toBeInTheDocument();
  });

  it("Applied creates the application, and Undo deletes it", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/jobs/42/application")) return envelope(makeApplication({ id: 77 }), 201);
      if (url.endsWith("/applications/77")) return new Response(null, { status: 204 });
      return envelope(null);
    });

    renderList();
    await user.click(screen.getByRole("button", { name: "Applied" }));

    expect(await screen.findByText("Backend Developer moved to Applications.")).toBeInTheDocument();
    expect(requestOf(fetchMock, 0)).toEqual({
      url: "/api/v1/jobs/42/application",
      method: "POST",
      body: { status: "applied" },
    });
    expect(screen.queryByRole("button", { name: "Backend Developer" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Undo" }));

    expect(await screen.findByRole("button", { name: "Backend Developer" })).toBeInTheDocument();
    const undo = fetchMock.mock.calls.map((call) => ({ url: String(call[0]), method: call[1]?.method }));
    expect(undo).toContainEqual({ url: "/api/v1/applications/77", method: "DELETE" });
  });

  it("Interested saves the job at the interest stage", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation(async () => envelope(makeApplication({ id: 78, status: "interest" }), 201));

    renderList();
    await user.click(screen.getByRole("button", { name: "Interested" }));

    expect(await screen.findByText("Backend Developer saved as Interested.")).toBeInTheDocument();
    expect(requestOf(fetchMock, 0).body).toEqual({ status: "interest" });
  });
});
