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
      job_id: "job-test-001",
      status: "completed",
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
});