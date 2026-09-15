import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Application } from "../api/types";
import { JobActionsProvider } from "../components/JobActionsProvider";
import { ToastProvider } from "../components/Toasts";
import { I18nProvider } from "../i18n/I18nProvider";
import { makeApplication, makeBoard, makeJob } from "../test/fixtures";
import { ApplicationsPage, type ApplicationsView } from "./ApplicationsPage";

function envelope(data: unknown, status = 200) {
  return new Response(JSON.stringify({ data, error: null, meta: { requestId: "test" } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const APPLICATIONS: Application[] = [
  makeApplication({ id: 1, status: "applied", daysIdle: 11, job: makeJob({ id: 11, title: "Java Developer", companyName: "Anbima" }) }),
  makeApplication({ id: 2, status: "interview", daysIdle: 4, job: makeJob({ id: 12, title: "Data Analyst", companyName: "Finnet" }) }),
  makeApplication({ id: 3, status: "applied", daysIdle: 0, job: makeJob({ id: 13, title: "SRE Junior", companyName: "PagBank" }) }),
];

function renderPage(view: ApplicationsView) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <MemoryRouter>
      <I18nProvider>
        <QueryClientProvider client={queryClient}>
          <ToastProvider>
            <JobActionsProvider>
              <ApplicationsPage view={view} />
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
    method: init?.method ?? "GET",
    body: init?.body ? JSON.parse(String(init.body)) : undefined,
  }));
}

describe("applications list", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    document.cookie = "csrftoken=csrf-test; path=/";
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.includes("/applications/board")) return envelope(makeBoard(APPLICATIONS));
      if (url.includes("/applications/closed")) return envelope([makeApplication({ id: 9, status: "withdrawn" })]);
      if (/\/applications\/\d+\/interactions$/.test(url)) {
        return envelope({ id: 70, applicationId: 1, date: "2026-09-15", title: "x", detail: "", createdAt: "" }, 201);
      }
      const detail = /\/applications\/(\d+)$/.exec(url);
      if (detail) {
        const found = APPLICATIONS.find((item) => item.id === Number(detail[1])) ?? APPLICATIONS[0];
        if (method === "PATCH") return envelope({ ...found, status: "screening" });
        return envelope({ ...found, interactions: [] });
      }
      return envelope(null);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("groups by wait with counts on every tab", async () => {
    renderPage("active");

    const late = await screen.findByRole("region", { name: "10+ DAYS WITHOUT AN ANSWER" });
    expect(within(late).getByRole("button", { name: "Java Developer" })).toBeInTheDocument();
    const recent = screen.getByRole("region", { name: "2 TO 9 DAYS" });
    expect(within(recent).getByRole("button", { name: "Data Analyst" })).toBeInTheDocument();
    const fresh = screen.getByRole("region", { name: "TODAY AND YESTERDAY" });
    expect(within(fresh).getByText("today")).toBeInTheDocument();

    const tabs = screen.getByRole("navigation", { name: "Application views" });
    await waitFor(() => expect(within(tabs).getByRole("link", { name: /Closed/ })).toHaveTextContent("1"));
    expect(within(tabs).getByRole("link", { name: /Active/ })).toHaveTextContent("3");
    expect(within(tabs).getByRole("link", { name: /Stalled/ })).toHaveTextContent("1");
    expect(within(tabs).getByRole("link", { name: /In progress/ })).toHaveTextContent("1");
    expect(screen.getByText("1 NEED A FOLLOW-UP")).toBeInTheDocument();
  });

  it("filters the stalled and in progress tabs", async () => {
    const view = renderPage("stalled");
    expect(await screen.findByRole("button", { name: "Java Developer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Data Analyst" })).not.toBeInTheDocument();
    view.unmount();

    renderPage("inProgress");
    expect(await screen.findByRole("button", { name: "Data Analyst" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Java Developer" })).not.toBeInTheDocument();
    // Past the answer: no "Got an answer" on an interview.
    expect(screen.queryByRole("button", { name: "Got an answer" })).not.toBeInTheDocument();
  });

  it("Got an answer moves to screening and logs the answer", async () => {
    const user = userEvent.setup();
    renderPage("active");

    const row = (await screen.findByRole("button", { name: "Java Developer" })).closest("article") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Got an answer" }));

    expect(await screen.findByText("Java Developer moved to Screening.")).toBeInTheDocument();
    const sent = calls(fetchMock);
    expect(sent).toContainEqual({ url: "/api/v1/applications/1", method: "PATCH", body: { status: "screening" } });
    expect(sent).toContainEqual({
      url: "/api/v1/applications/1/interactions",
      method: "POST",
      body: expect.objectContaining({ title: "Answer received" }),
    });
  });

  it("Set opens the drawer with the next step field focused", async () => {
    const user = userEvent.setup();
    renderPage("active");

    await user.click(await screen.findByRole("button", { name: "Set the next step for Java Developer" }));

    const dialog = await screen.findByRole("dialog");
    const input = within(dialog).getByRole("textbox", { name: "Next step" });
    await waitFor(() => expect(input).toHaveFocus());
  });

  it("drawer stage blocks change the stage and follow-up is logged", async () => {
    const user = userEvent.setup();
    renderPage("active");

    await user.click(await screen.findByRole("button", { name: "Java Developer" }));
    const dialog = await screen.findByRole("dialog");

    expect(within(dialog).getByRole("button", { name: /Applied/, pressed: true })).toBeInTheDocument();
    expect(within(dialog).getByText("NO ANSWER")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /Log follow-up/ }));
    await waitFor(() =>
      expect(calls(fetchMock)).toContainEqual({
        url: "/api/v1/applications/1/interactions",
        method: "POST",
        body: expect.objectContaining({ title: "Follow-up sent" }),
      }),
    );
    expect(await screen.findByText("Follow-up logged. Set the next step date.")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /Interview/ }));
    await waitFor(() =>
      expect(calls(fetchMock)).toContainEqual({ url: "/api/v1/applications/1", method: "PATCH", body: { status: "interview" } }),
    );
  });
});
