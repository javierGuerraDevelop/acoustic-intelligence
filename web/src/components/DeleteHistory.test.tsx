import {
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { DeleteHistory } from "@/components/DeleteHistory";
import {
  deleteHistory,
  getJob,
} from "@/services/api";

vi.mock("@/services/api", () => ({
  deleteHistory: vi.fn(),
  getJob: vi.fn(),
}));

const mockedDeleteHistory = vi.mocked(deleteHistory);
const mockedGetJob = vi.mocked(getJob);

describe("DeleteHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("opens a confirmation dialog", async () => {
    const user = userEvent.setup();

    render(
      <DeleteHistory onDeleted={() => {}} />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Delete History",
      })
    );

    expect(
      screen.getByRole("alertdialog")
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        "Delete all detection history?"
      )
    ).toBeInTheDocument();

    expect(
      screen.getByText(
        /This permanently deletes your stored detection history/i
      )
    ).toBeInTheDocument();
  });

  it("deletes history and calls onDeleted when the job completes", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();

    mockedDeleteHistory.mockResolvedValue({
      schema_version: 1,
      job_id: "job-test-001",
      kind: "delete",
      state: "complete",
      updated_at: "2026-09-26T20:00:05.000Z",
      result: {
        local: "complete",
        atlas: "complete",
        snowflake: "complete",
      },
      error: null,
    });

    render(
      <DeleteHistory onDeleted={onDeleted} />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Delete History",
      })
    );

    const dialog = screen.getByRole("alertdialog");

    const confirmButton = within(dialog).getByRole(
      "button",
      {
        name: "Delete History",
      }
    );

    await user.click(confirmButton);

    await waitFor(() => {
      expect(
        mockedDeleteHistory
      ).toHaveBeenCalledOnce();
    });

    await waitFor(() => {
      expect(onDeleted).toHaveBeenCalledOnce();
    });

    expect(mockedGetJob).not.toHaveBeenCalled();
  });

  it("shows an error when deletion fails", async () => {
    const user = userEvent.setup();

    mockedDeleteHistory.mockRejectedValue(
      new Error("Delete failed")
    );

    render(
      <DeleteHistory onDeleted={() => {}} />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Delete History",
      })
    );

    const dialog = screen.getByRole("alertdialog");

    const confirmButton = within(dialog).getByRole(
      "button",
      {
        name: "Delete History",
      }
    );

    await user.click(confirmButton);

    expect(
      await screen.findByText(
        "Unable to delete detection history."
      )
    ).toBeInTheDocument();
  });

  it("treats a failed remote deletion as pending when local history is gone", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();

    mockedDeleteHistory.mockResolvedValue({
      schema_version: 1,
      job_id: "job-delete-002",
      kind: "delete",
      state: "failed",
      updated_at: "2026-10-02T20:00:05.000Z",
      result: {
        local: "complete",
        atlas: "complete",
        snowflake: "pending",
      },
      error: {
        code: "UNAVAILABLE",
        retryable: true,
        message:
          "Snowflake analytics is unavailable.",
      },
    });

    render(
      <DeleteHistory onDeleted={onDeleted} />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Delete History",
      })
    );

    const dialog = screen.getByRole("alertdialog");

    await user.click(
      within(dialog).getByRole("button", {
        name: "Delete History",
      })
    );

    await waitFor(() => {
      expect(onDeleted).toHaveBeenCalledOnce();
    });

    expect(
      await screen.findByText(/Local history was deleted/)
    ).toBeInTheDocument();

    expect(
      screen.queryByRole("alertdialog")
    ).not.toBeInTheDocument();

    expect(
      screen.queryByText(
        "Unable to delete detection history."
      )
    ).not.toBeInTheDocument();
  });

  it("keeps the error state when the local deletion never completed", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();

    mockedDeleteHistory.mockResolvedValue({
      schema_version: 1,
      job_id: "job-delete-003",
      kind: "delete",
      state: "failed",
      updated_at: "2026-10-02T20:00:05.000Z",
      result: null,
      error: {
        code: "INTERNAL",
        retryable: true,
        message: "The job failed unexpectedly.",
      },
    });

    render(
      <DeleteHistory onDeleted={onDeleted} />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Delete History",
      })
    );

    const dialog = screen.getByRole("alertdialog");

    await user.click(
      within(dialog).getByRole("button", {
        name: "Delete History",
      })
    );

    expect(
      await screen.findByText(
        "Unable to delete detection history."
      )
    ).toBeInTheDocument();

    expect(onDeleted).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/Local history was deleted/)
    ).not.toBeInTheDocument();
  });
});