import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ListeningStatus } from "@/components/ListeningStatus";

describe("ListeningStatus", () => {
  it("shows Start Listening when capture is stopped", () => {
    render(
      <ListeningStatus
        status="stopped"
        onToggle={() => {}}
      />
    );

    expect(
      screen.getByRole("button", {
        name: "Start Listening",
      })
    ).toBeInTheDocument();
  });

  it("shows Stop Listening when capture is running", () => {
    render(
      <ListeningStatus
        status="running"
        onToggle={() => {}}
      />
    );

    expect(
      screen.getByRole("button", {
        name: "Stop Listening",
      })
    ).toBeInTheDocument();
  });

  it("calls onToggle when Start Listening is clicked", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();

    render(
      <ListeningStatus
        status="stopped"
        onToggle={onToggle}
      />
    );

    await user.click(
      screen.getByRole("button", {
        name: "Start Listening",
      })
    );

    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("disables the control while capture is starting", () => {
    render(
      <ListeningStatus
        status="starting"
        onToggle={() => {}}
      />
    );

    expect(
      screen.getByRole("button")
    ).toBeDisabled();
  });

  it("disables the control while capture is stopping", () => {
    render(
      <ListeningStatus
        status="stopping"
        onToggle={() => {}}
      />
    );

    expect(
      screen.getByRole("button")
    ).toBeDisabled();
  });
});