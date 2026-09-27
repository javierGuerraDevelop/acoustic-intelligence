import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SettingsPrivacy } from "@/components/SettingsPrivacy";
import type { Settings } from "@/types/contracts";

const mockSettings: Settings = {
  schema_version: 1,
  revision: 1,
  capture_enabled: false,
  cloud_storage_enabled: false,
  analytics_enabled: false,
  speech_enabled: false,
  retention_days: 1,
  cooldown_seconds: 10,
  muted_until: null,
};

describe("SettingsPrivacy", () => {
  it("renders the privacy controls", () => {
    render(
      <SettingsPrivacy
        settings={mockSettings}
        isUpdating={false}
        onChange={() => {}}
        onHistoryDeleted={() => {}}
      />
    );

    expect(
      screen.getByText("Settings & Privacy")
    ).toBeInTheDocument();

    expect(
      screen.getByRole("switch", {
        name: "Enable cloud storage",
      })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("switch", {
        name: "Enable analytics",
      })
    ).toBeInTheDocument();

    expect(
      screen.getByRole("switch", {
        name: "Enable speech",
      })
    ).toBeInTheDocument();
  });

  it("enables cloud storage", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SettingsPrivacy
        settings={mockSettings}
        isUpdating={false}
        onChange={onChange}
        onHistoryDeleted={() => {}}
      />
    );

    await user.click(
      screen.getByRole("switch", {
        name: "Enable cloud storage",
      })
    );

    expect(onChange).toHaveBeenCalledWith({
      cloud_storage_enabled: true,
    });
  });

  it("enables analytics", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SettingsPrivacy
        settings={mockSettings}
        isUpdating={false}
        onChange={onChange}
        onHistoryDeleted={() => {}}
      />
    );

    await user.click(
      screen.getByRole("switch", {
        name: "Enable analytics",
      })
    );

    expect(onChange).toHaveBeenCalledWith({
      analytics_enabled: true,
    });
  });

  it("enables speech", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SettingsPrivacy
        settings={mockSettings}
        isUpdating={false}
        onChange={onChange}
        onHistoryDeleted={() => {}}
      />
    );

    await user.click(
      screen.getByRole("switch", {
        name: "Enable speech",
      })
    );

    expect(onChange).toHaveBeenCalledWith({
      speech_enabled: true,
    });
  });

  it("disables all switches while settings are updating", () => {
    render(
      <SettingsPrivacy
        settings={mockSettings}
        isUpdating={true}
        onChange={() => {}}
        onHistoryDeleted={() => {}}
      />
    );

    expect(
      screen.getByRole("switch", {
        name: "Enable cloud storage",
      })
    ).toBeDisabled();

    expect(
      screen.getByRole("switch", {
        name: "Enable analytics",
      })
    ).toBeDisabled();

    expect(
      screen.getByRole("switch", {
        name: "Enable speech",
      })
    ).toBeDisabled();
  });
});